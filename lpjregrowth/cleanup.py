"""Conservative cleanup of tracked study executions; preview by default."""
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
from .config import ROOT, resolve_path, atomic_json
from .instructions import ConfigError


def inside(path, parent):
    return path == parent or parent in path.parents


def safe_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ConfigError(f'Cleanup refuses linked paths: {part}')
    return path.resolve()


def clean(study, execute=False, include_archives=False, runner=subprocess.run):
    root = safe_path(study.root)
    dbpath = root/'status.sqlite'
    rows=[]
    receipt=safe_path(root.parent/('.'+root.name+'-cleanup.json'))
    history=json.loads(receipt.read_text()) if receipt.is_file() else {}
    if history and Path(history.get('state_root','')).resolve()!=root:
        raise ConfigError('Cleanup receipt belongs to another workspace')
    db=None
    try:
        if dbpath.exists():
            db=sqlite3.connect(dbpath, timeout=5)
            db.row_factory=sqlite3.Row
            # Serialize with submission reservation while planning and removing files.
            db.execute('BEGIN IMMEDIATE' if execute else 'BEGIN')
            rows=[dict(r) for r in db.execute('SELECT * FROM executions')]
        current={r['id'] for r in rows}
        rows.extend(r for r in history.get('rows',[]) if r['id'] not in current)
        roots={k:safe_path(study.cluster_path_value(k)) for k in ('work_root','submission_root','archive_root')}
        records={m['execution_id']:m for m in history.get('manifests',[]) if Path(m.get('state_root','')).resolve()==root}
        # Discover copies as well as DB paths, but never infer ownership from names alone.
        candidates=[Path(r['manifest']) for r in rows]
        for folder in roots.values():
            if folder.is_dir(): candidates.extend(folder.glob('*/*/execution.json'))
        for path in candidates:
            if not path.is_file(): continue
            try: m=json.loads(path.read_text(encoding='utf-8-sig'))
            except (ValueError,OSError) as exc:
                raise ConfigError(f'Cannot inspect cleanup manifest: {path}') from exc
            if Path(m.get('state_root','')).resolve()!=root: continue
            eid=m['execution_id']
            if eid in records:
                keys=('work_dir','submission_dir','archive_dir','state_root')
                if any(m.get(k)!=records[eid].get(k) for k in keys):
                    raise ConfigError(f'Conflicting execution copies: {eid}')
            records[eid]=m
        tracked={r['id'] for r in rows}
        if set(records)-tracked:
            raise ConfigError('Owned execution directories have no tracking records. Restore the original workspace database before automatic cleanup.')
        if tracked-set(records):
            raise ConfigError('Tracked executions are missing all manifest copies; cleanup cannot verify their paths')
        blocked=[r for r in rows if r['status'] not in ('prepared','complete','failed','cancelled')]
        if blocked:
            raise ConfigError('Cleanup blocked by active/uncertain executions: '+', '.join(r['id']+':'+r['status'] for r in blocked))
        # Without a DB, require generated manifests to establish workspace ownership.
        generated=list((root/'generated').glob('*/manifest.json')) if root.exists() else []
        if root.exists() and not dbpath.exists() and not history:
            if not generated or any(json.loads(p.read_text())['study'] != study.config for p in generated):
                raise ConfigError('Workspace has no tracking database or matching generated manifests; refusing unverified directory deletion')
        targets=[]; retained=[]; job_ids=[]
        for row in rows:
            m=records[row['id']]
            exp=m['experiment']['id'];eid=row['id']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', exp) or not re.fullmatch(r'[A-Za-z0-9_-]+', eid):
                raise ConfigError('Invalid execution path components')
            for field,key in [('work_dir','work_root'),('submission_dir','submission_root'),('archive_dir','archive_root')]:
                path=safe_path(m[field]);expected=roots[key]/exp/eid
                if path!=expected:
                    raise ConfigError(f'Execution path is outside the current configured root: {path}')
                destinations=[path]
                if field=='archive_dir':
                    destinations+=list(path.parent.glob(path.name+'.partial-*'))
                for destination in destinations:
                    destination=safe_path(destination)
                    if destination.exists():
                        (retained if field=='archive_dir' and not include_archives else targets).append(destination)
            for key in ('sim_job','finish_job'):
                if row.get(key):
                    if not re.fullmatch(r'[0-9]+',row[key]): raise ConfigError('Invalid stored Slurm job id')
                    job_ids.append(row[key])
        if root.exists(): targets.append(root)
        targets=sorted(set(targets),key=lambda p:(p==root,str(p)))
        if any(a!=b and inside(a,b) for a in targets for b in targets):
            raise ConfigError('Cleanup targets overlap; configure separate execution roots and workspace')
        protected=[receipt,study.path,study.cluster_path,study.base,study.grid,ROOT,study.instruction_dir]
        protected += [study.cluster_path_value('executable')]
        if study.config.get('model_source'):
            protected.append(resolve_path(study.config['model_source'],study.path.parent))
        protected.append(resolve_path(study.config['experiments'],study.path.parent))
        protected += [resolve_path(v,parent) for k,(v,parent) in study.ins.params.items() if k.startswith('file_') and v]
        protected += list(study.ins.files)
        protected += list(roots.values())
        for target in targets:
            if target==Path(target.anchor) or any(inside(Path(p).resolve(),target) for p in protected):
                raise ConfigError(f'Cleanup target contains protected inputs, code or storage roots: {target}')
            if any(inside(p,target) for p in retained):
                raise ConfigError('Retained archives overlap a cleanup target; use separate roots')
        result={'mode':'delete' if execute else 'preview','remove':[str(p) for p in targets],
                'retain_archives':[str(p) for p in retained], 'cleanup_receipt':str(receipt),
                'note':'Does not cancel jobs or remove node-local scratch. Stop other controllers for this workspace before deletion.'}
        if not execute: return result
        if job_ids:
            response=runner(['squeue','--noheader','--format=%i'],text=True,capture_output=True,check=True)
            queued={line.strip().split('_')[0].split('.')[0] for line in response.stdout.splitlines() if line.strip()}
            if queued.intersection(job_ids):
                raise ConfigError('Slurm jobs are still present; cleanup refused: '+', '.join(sorted(queued.intersection(job_ids))))
        # All targets have now been resolved and checked before any recursive removal.
        atomic_json(receipt,{'state_root':str(root),'rows':rows,'manifests':list(records.values()),'last_plan':result})
        marker=root/'.cleaning'
        if root.exists(): marker.write_text('Cleanup in progress; do not submit or prepare.\n')
        for target in targets:
            if target!=root:
                shutil.rmtree(target)
                # Remove only empty experiment parents, never the configured root.
                try: target.parent.rmdir()
                except OSError: pass
        if db:
            db.commit();db.close();db=None
        if root in targets: shutil.rmtree(root)
        return result
    finally:
        if db: db.close()
