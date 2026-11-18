"""Slurm orchestration with durable execution records and conservative retries."""
from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import uuid
from .config import ROOT, atomic_json, digest, split_grid, write_text, resolve_path
from .instructions import ConfigError

TERMINAL = {'complete', 'failed', 'cancelled'}
ACTIVE = {'submitting', 'submission_unknown', 'submitted', 'running', 'collecting', 'validating', 'finish_submission_failed'}
FAILED_SLURM = {'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY', 'NODE_FAIL', 'PREEMPTED', 'BOOT_FAIL', 'DEADLINE'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class Store:
    def __init__(self, root):
        if (Path(root)/'.cleaning').exists():
            raise ConfigError('Workspace cleanup is in progress or was interrupted')
        Path(root).mkdir(parents=True, exist_ok=True)
        self.path = Path(root) / 'status.sqlite'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS executions (id TEXT PRIMARY KEY, experiment TEXT, status TEXT, manifest TEXT, sim_job TEXT, finish_job TEXT, updated TEXT, reason TEXT)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def add(self, manifest):
        with self.connect() as db:
            db.execute('INSERT INTO executions VALUES (?,?,?,?,?,?,?,?)',
                       (manifest['execution_id'], manifest['experiment']['id'], 'prepared',
                        manifest['manifest_path'], None, None, now(), None))

    def update(self, execution_id, status=None, **fields):
        if status:
            fields['status'] = status
        fields['updated'] = now()
        if not set(fields) <= {'status', 'updated', 'sim_job', 'finish_job', 'reason'}:
            raise ValueError('Invalid state fields')
        with self.connect() as db:
            db.execute('UPDATE executions SET ' + ','.join(k+'=?' for k in fields) + ' WHERE id=?',
                       [*fields.values(), execution_id])

    def rows(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM executions ORDER BY updated, id')]

    def reserve(self, execution_id, maximum):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if (self.path.parent/'.cleaning').exists():
                raise ConfigError('Workspace cleanup is in progress')
            row = db.execute('SELECT * FROM executions WHERE id=?', (execution_id,)).fetchone()
            count = db.execute('SELECT count(*) FROM executions WHERE status IN (' + ','.join('?' for _ in ACTIVE) + ')', tuple(ACTIVE)).fetchone()[0]
            if row['status'] != 'prepared':
                raise ConfigError('Only a prepared execution may be submitted; reconcile ambiguous submissions first')
            if count >= maximum:
                return False
            db.execute('UPDATE executions SET status=?,updated=? WHERE id=?', ('submitting', now(), execution_id))
        return True


def header(cluster, finish=False):
    lines = ['#!/bin/bash']
    opts = {'partition': cluster['finish_partition'] if finish else cluster['partition'],
            'nodes': 1 if finish else cluster['nodes'],
            'ntasks': cluster['finish_tasks'] if finish else int(cluster['nodes'])*int(cluster['processes_per_node']),
            'time': cluster['finish_walltime'] if finish else cluster['walltime'],
            'output': 'finish_%j.out' if finish else 'guess_x.o%j',
            'error': 'finish_%j.err' if finish else 'guess_x.e%j'}
    if not finish:
        opts['ntasks-per-node'] = cluster['processes_per_node']
    for name in ('account', 'qos', 'memory'):
        if cluster.get(name):
            opts['mem' if name == 'memory' else name] = cluster[name]
    lines += [f'#SBATCH --{k}={v}' for k,v in opts.items()]
    lines += ['set -euo pipefail']
    # This is an explicitly trusted cluster administrator/user shell snippet.
    lines += cluster.get('environment', [])
    return '\n'.join(lines) + '\n'


def prepare(study, ids=None, retry=False):
    study.validate()
    if study.config.get("scenarios") is not None and not getattr(study,"scenario_child",False):
        from .scenarios import child
        return [p for exp in study.selected(ids) for p in prepare(child(study,exp),retry=retry)]
    store = Store(study.root)
    generated = study.generate(ids)
    results = []
    for folder in generated:
        folder = Path(folder)
        gen = json.loads((folder / 'manifest.json').read_text())
        exp = gen['experiment']
        previous = [r for r in store.rows() if r['experiment'] == exp['id']]
        if previous and not retry:
            raise ConfigError(f'{exp["id"]} already has an execution; use --retry for a new execution')
        if any(r['status'] not in TERMINAL for r in previous):
            raise ConfigError(f'{exp["id"]} has an unfinished execution; resume it instead')
        exe = study.cluster_path_value('executable')
        if not exe.is_file():
            raise ConfigError(f'Executable missing: {exe}')
        execution_id = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:10]
        work = study.cluster_path_value('work_root') / exp['id'] / execution_id
        submission = study.cluster_path_value('submission_root') / exp['id'] / execution_id
        archive = study.cluster_path_value('archive_root') / exp['id'] / execution_id
        if len({work,submission,archive}) != 3:
            raise ConfigError('Submission, work and archive execution paths must differ')
        if archive.exists() or work.exists() or submission.exists():
            raise ConfigError('Execution path collision')
        for path in (work, submission):
            shutil.copytree(folder, path)
        if 'scenario' in exp or study.config.get('prepared_landuse'):
            # Pin derived inputs to the execution copy, never mutable generated/.
            for directory in (work,submission):
                text=(directory/'guess.ins').read_text(encoding='utf-8')
                text=text.replace((folder/'inputs').as_posix()+'/',(work/'inputs').as_posix()+'/')
                write_text(directory/'guess.ins',text)
        shutil.copy2(exe.resolve(), work / 'guess')
        (work / 'guess').chmod(0o755)
        # Snapshot controller runtime so later edits cannot change queued collection jobs.
        runtime = work / 'runtime'
        shutil.copytree(ROOT / 'lpjregrowth', runtime / 'lpjregrowth', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(ROOT / 'regrowth.py', runtime / 'regrowth.py')
        wrapper = work / 'mpi_run_guess_on_tmp.sh'
        write_text(wrapper, (ROOT / 'templates' / wrapper.name).read_text(encoding='utf-8-sig'))
        wrapper.chmod(0o755)
        chunks = split_grid(study.records, study.processes)
        for rank, records in enumerate(chunks, 1):
            run = work / f'run{rank}'
            run.mkdir()
            shutil.copy2(work / 'guess.ins', run / 'guess.ins')
            write_text(run / 'gridlist.txt', '\n'.join(records) + '\n')
        manifest = {**gen, 'execution_id': execution_id, 'created': now(),
                    'work_dir': str(work), 'archive_dir': str(archive),
                    'submission_dir': str(submission), 'state_root': str(study.root),
                    'manifest_path': str(work / 'execution.json'),
                    'cluster': study.cluster, 'processes': study.processes,
                    'sites': [[float(x.split()[0]),float(x.split()[1])] for x in study.records],
                    'rank_sites': [[[float(x.split()[0]),float(x.split()[1])] for x in chunk] for chunk in chunks],
                    'first_year': study.first_year, 'last_year': study.last_year, 'cut_year': study.cut_year,
                    'outputs': study.outputs, 'executable_sha256': digest(work / 'guess'),
                    'source_binary_relationship': 'User review required; checksum does not establish source provenance.',
                    'python': str(study.cluster_path_value('python')),
                    'input_files': [{'parameter':name,'path':str(resolve_path(value,parent)),
                                     'size': resolve_path(value,parent).stat().st_size if resolve_path(value,parent).is_file() else None,
                                     'mtime_ns': resolve_path(value,parent).stat().st_mtime_ns if resolve_path(value,parent).is_file() else None}
                                    for name,(value,parent) in study.ins.params.items()
                                    if name.startswith('file_') and value and 'gridlist' not in name]}
        manifest['prepared_files'] = {str(p.relative_to(work)):digest(p) for p in work.rglob('*')
                                      if p.is_file() and ('runtime' not in p.parts or '__pycache__' not in p.parts)}
        atomic_json(work / 'execution.json', manifest)
        atomic_json(submission / 'execution.json', manifest)
        q = shlex.quote
        launch = f'srun --label {q(str(wrapper))} {q(str(work / "guess"))} -parallel -input {q(study.config.get("input_module", "cfx"))} guess.ins'
        write_text(work / 'submit.sh', header(study.cluster).replace('set -euo pipefail', f'#SBATCH --job-name=rg_{exp["id"]}_{execution_id[-10:]}\nset -euo pipefail') + f'cd {q(str(work))}\n' + launch + '\n')
        finish = f'{q(manifest["python"])} {q(str(runtime / "regrowth.py"))} collect --execution {q(str(work / "execution.json"))}'
        write_text(work / 'finishup.sh', header(study.cluster, True).replace('set -euo pipefail', f'#SBATCH --job-name=collect_{exp["id"]}_{execution_id[-10:]}\nset -euo pipefail') + f'cd {q(str(work))}\n' + finish + '\n')
        # Explicit entry point; Python owns IDs, concurrency and submission journaling.
        write_text(work / 'startguess.sh', '#!/bin/bash\nset -euo pipefail\n' +
                   f'exec {q(manifest["python"])} {q(str(runtime / "regrowth.py"))} submit --execution {q(str(work / "execution.json"))}\n')
        for script in ('submit.sh', 'finishup.sh', 'startguess.sh'):
            (work / script).chmod(0o755)
        for filename in ('submit.sh','finishup.sh','startguess.sh'):
            manifest['prepared_files'][filename] = digest(work / filename)
        atomic_json(work/'execution.json',manifest)
        atomic_json(submission/'execution.json',manifest)
        store.add(manifest)
        results.append(manifest['manifest_path'])
    return results


def slurm_submit(script, work, dependency=None, runner=subprocess.run):
    cmd = ['sbatch', '--parsable']
    if dependency:
        cmd += [f'--dependency=afterok:{dependency}']
    cmd.append(str(script))
    result = runner(cmd, cwd=work, text=True, capture_output=True, check=True)
    job = result.stdout.strip().split(';')[0]
    if not re.fullmatch(r'[0-9]+', job):
        raise ConfigError(f'Unrecognized sbatch response; reconcile with Slurm before retry: {result.stdout!r}')
    return job


def submit_execution(path, runner=subprocess.run):
    path = Path(path)
    manifest = json.loads(path.read_text(encoding='utf-8-sig'))
    if os.name != 'posix' and runner is subprocess.run:
        raise ConfigError('Submit only on the cluster')
    c = manifest['study']
    if not all(c.get(flag) for flag in ('disturbance_audit_confirmed', 'landcover_audit_confirmed', 'executable_compatibility_confirmed')) or not c['biomass'].get('definition_reviewed'):
        raise ConfigError('Required study/executable reviews are not confirmed in this execution snapshot')
    store = Store(manifest['state_root'])
    eid = manifest['execution_id']
    work = Path(manifest['work_dir'])
    for file, expected in (('guess',manifest['executable_sha256']), ('guess.ins',manifest['main_sha256']), ('gridlist.txt',manifest['grid_sha256'])):
        if digest(work / file) != expected:
            raise ConfigError(f'Prepared file changed: {file}')
    for relative, expected in manifest.get('prepared_files',{}).items():
        if digest(work / relative) != expected:
            raise ConfigError(f'Prepared file changed: {relative}')
    if runner is subprocess.run:
        if not os.access(work/'guess', os.X_OK) or not Path(manifest['python']).is_file():
            raise ConfigError('Executable/Python unavailable on submission host')
        for entry in manifest.get('input_files',[]):
            path = Path(entry['path'])
            if not path.is_file():
                raise ConfigError(f'Supplied input missing: {path}')
            if entry['size'] is not None and (path.stat().st_size != entry['size'] or path.stat().st_mtime_ns != entry['mtime_ns']):
                raise ConfigError(f'Supplied input changed after preparation: {path}')
    if not store.reserve(eid, int(manifest['cluster']['max_active'])):
        return {'execution_id': eid, 'status': 'deferred', 'reason': 'concurrency limit reached'}
    try:
        sim = slurm_submit(work / 'submit.sh', work, runner=runner)
        atomic_json(work / 'simulation-submission.json', {'job_id': sim, 'time': now()})
        store.update(eid, 'submitted', sim_job=sim)
    except Exception as exc:
        store.update(eid, 'submission_unknown', reason=str(exc))
        raise
    try:
        finish = slurm_submit(work / 'finishup.sh', work, dependency=sim, runner=runner)
        atomic_json(work / 'finish-submission.json', {'job_id': finish, 'time': now()})
        store.update(eid, finish_job=finish)
    except Exception as exc:
        store.update(eid, 'finish_submission_failed', reason=str(exc))
        raise
    return {'execution_id': eid, 'simulation_job': sim, 'finish_job': finish}


def refresh(store, runner=subprocess.run):
    for row in store.rows():
        if row['status'] in TERMINAL or not row['sim_job']:
            continue
        jobs = [j for j in (row['sim_job'], row['finish_job']) if j]
        result = runner(['sacct', '-n', '-P', '-j', ','.join(jobs), '--format=JobIDRaw,State,ExitCode'],
                        text=True, capture_output=True, check=True)
        states = {}
        for line in result.stdout.splitlines():
            fields = line.split('|')
            if len(fields) >= 3 and fields[0] in jobs:
                states[fields[0]] = (fields[1].split()[0].rstrip('+'), fields[2])
        sim = states.get(row['sim_job'])
        finish = states.get(row['finish_job'])
        if sim and (sim[0] in FAILED_SLURM or (sim[0] == 'COMPLETED' and sim[1] != '0:0')):
            # Cancel only the owned dependent job, which otherwise cannot satisfy afterok.
            if row['finish_job']:
                runner(['scancel', row['finish_job']], text=True, capture_output=True, check=True)
            store.update(row['id'], 'cancelled' if sim[0] == 'CANCELLED' else 'failed',
                         reason=f'Simulation {sim}; dependent finish-up cancelled')
        elif finish and (finish[0] in FAILED_SLURM or (finish[0] == 'COMPLETED' and finish[1] != '0:0')):
            store.update(row['id'], 'failed', reason=f'Finish-up {finish}')
        elif finish and finish[0] == 'COMPLETED':
            manifest = json.loads(Path(row['manifest']).read_text())
            from .collect import verify_archive
            try:
                verify_archive(Path(manifest['archive_dir']))
                store.update(row['id'], 'complete', reason=None)
            except Exception as exc:
                store.update(row['id'], 'failed', reason=f'Finish-up completed without valid archive: {exc}')
        elif finish and finish[0] == 'RUNNING':
            store.update(row['id'], 'collecting')
        elif sim and sim[0] == 'RUNNING':
            store.update(row['id'], 'running')
    return store.rows()
