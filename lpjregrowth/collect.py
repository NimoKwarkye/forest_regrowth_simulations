"""Streaming output merging, scientific checks, and atomic archives."""
from contextlib import closing
import gzip
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
from .config import atomic_json, digest, write_text
from .instructions import ConfigError
from .workflow import Store, now


def open_table(path):
    return gzip.open(path, 'rt', encoding='utf-8') if str(path).endswith('.gz') else open(path, encoding='utf-8-sig')


def read_table(path):
    with open_table(path) as handle:
        header = None
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            if header is None:
                header = line.split()
                if len(set(header)) != len(header):
                    raise ConfigError(f'Duplicate header columns in {path}')
                continue
            fields = line.split()
            if len(fields) != len(header):
                raise ConfigError(f'{path}:{number}: expected {len(header)} columns, got {len(fields)}')
            try:
                numeric = [float(x) for x in fields]
            except ValueError as exc:
                raise ConfigError(f'{path}:{number}: nonnumeric data or duplicate header') from exc
            if not all(math.isfinite(x) for x in numeric):
                raise ConfigError(f'{path}:{number}: nonfinite values')
            yield header, dict(zip(header, numeric)), fields
        if header is None:
            raise ConfigError(f'Empty table: {path}')


def validate_table(path, spec, manifest, db):
    db.execute('DROP TABLE IF EXISTS record_keys')
    db.execute('CREATE TABLE record_keys (record_key TEXT PRIMARY KEY, lon REAL, lat REAL, year INTEGER)')
    expected = {tuple(x) for x in manifest['sites']}
    years = range(manifest['first_year'], manifest['last_year']+1)
    tolerance = manifest['study'].get('validation', {}).get('harvest_tolerance', 1e-8)
    controlled = manifest["study"].get("experiment_mode") != "landuse_change"
    counts = 0
    cut_sites = set()
    biomass_max = {}
    for header, row, fields in read_table(path):
        required = set(spec['key']) | set(spec['values'])
        if required - set(header):
            raise ConfigError(f'{path.name}: missing columns {required-set(header)}')
        site = (row['Lon'], row['Lat'])
        if site not in expected:
            raise ConfigError(f'{path.name}: unexpected site {site}; coordinate rounding must match the gridlist')
        year_float = row[spec['year_column']]
        year = int(year_float)
        if year_float != year or year not in years:
            raise ConfigError(f'{path.name}: unexpected year {year_float}')
        key = json.dumps([row[x] for x in spec['key']])
        try:
            db.execute('INSERT INTO record_keys VALUES (?,?,?,?)', (key, *site, year))
        except sqlite3.IntegrityError as exc:
            raise ConfigError(f'{path.name}: duplicate record {key}') from exc
        value = sum(row[x] for x in spec['values'])
        if spec.get('nonnegative', False) and value < -1e-8:
            raise ConfigError(f'{path.name}: negative {spec["variable"]} at {site}, {year}')
        role = spec.get('role')
        if controlled and role in ('harvest_event', 'harvest_total'):
            if year > manifest['cut_year'] and abs(value) > tolerance:
                raise ConfigError(f'Unexpected later harvest: {path.name}, {site}, {year}, {value}')
            if year == manifest['cut_year'] and value > tolerance:
                cut_sites.add(site)
        if role == 'biomass' and year > manifest['cut_year']:
            biomass_max[site] = max(biomass_max.get(site, 0), value)
        counts += 1
    expected_count = int(spec.get('records_per_site_year', 1))
    covered = 0
    for lon,lat,year,count in db.execute('SELECT lon,lat,year,count(*) FROM record_keys GROUP BY lon,lat,year'):
        if count != expected_count:
            raise ConfigError(f'{path.name}: incomplete coverage {(lon,lat)}, {year}')
        covered += 1
    if covered != len(expected) * len(years):
        raise ConfigError(f'{path.name}: incomplete coverage: {covered} site-years; expected {len(expected)*len(years)}')
    if controlled and spec.get('role') == 'harvest_event' and cut_sites != expected:
        raise ConfigError(f'No measured clear-cut at required sites: {expected-cut_sites}')
    if controlled and spec.get('role') == 'biomass' and any(biomass_max.get(s, 0) <= 0 for s in expected):
        raise ConfigError('No positive post-cut aboveground tree carbon at one or more sites')
    db.commit()
    return {'variable': spec['variable'], 'rows': counts, 'coverage': 'complete', 'role': spec.get('role')}


def merge_table(paths, destination):
    header = None
    with gzip.open(destination, 'wt', encoding='utf-8', newline='\n') as target:
        for path in paths:
            with path.open(encoding='utf-8-sig') as source:
                local_header = None
                for line in source:
                    if not line.strip():
                        continue
                    if local_header is None:
                        local_header = line.split()
                        if header is None:
                            header = local_header
                            target.write(' '.join(header) + '\n')
                        elif local_header != header:
                            raise ConfigError(f'Incompatible header: {path}')
                    else:
                        target.write(line.rstrip() + '\n')
                if local_header is None:
                    raise ConfigError(f'Empty output file: {path}')


def verify_archive(archive):
    archive = Path(archive)
    marker = json.loads((archive / 'COMPLETE.json').read_text())
    checkfile = archive / 'checksums.json'
    if marker.get('checksums_sha256') != digest(checkfile):
        raise ConfigError('Checksum manifest mismatch')
    checks = json.loads(checkfile.read_text())
    for relative, expected in checks.items():
        path = (archive / relative).resolve()
        if not path.is_relative_to(archive.resolve()) or not path.is_file() or digest(path) != expected:
            raise ConfigError(f'Archive missing or corrupted: {relative}')
    if 'validation.json' not in checks or 'execution.json' not in checks:
        raise ConfigError('Missing validation or execution provenance')
    report = json.loads((archive / 'validation.json').read_text())
    if not report.get('passed'):
        raise ConfigError('Archive did not pass validation')
    return marker


def collect(path):
    path = Path(path)
    manifest = json.loads(path.read_text(encoding='utf-8-sig'))
    work = Path(manifest['work_dir'])
    archive = Path(manifest['archive_dir'])
    store = Store(manifest['state_root'])
    eid = manifest['execution_id']
    if archive.exists():
        verify_archive(archive)
        store.update(eid, 'complete', reason=None)
        return str(archive)
    lock = work / '.collection.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ConfigError('Collection already running or interrupted; inspect .collection.lock before recovery') from exc
    with os.fdopen(fd, 'w') as handle:
        handle.write(f'{os.getpid()} {now()}\n')
    partial = archive.with_name(archive.name + '.partial-' + uuid.uuid4().hex[:8])
    try:
        store.update(eid, 'collecting')
        partial.mkdir(parents=True)
        runs = [work / f'run{i}' for i in range(1, manifest['processes']+1)]
        inventories = []
        for run in runs:
            if not run.is_dir() or (run / 'model.exitcode').read_text().strip() != '0' or (run / 'copy.exitcode').read_text().strip() != '0':
                raise ConfigError(f'Missing successful model status: {run}')
            inventory = {p.relative_to(run) for p in run.rglob('*.out')}
            inventories.append(inventory)
        if not inventories[0] or any(inv != inventories[0] for inv in inventories):
            raise ConfigError('Output inventories differ across ranks or are empty')
        for spec in manifest['outputs']:
            if Path(spec['file']) not in inventories[0]:
                raise ConfigError(f'Missing required output: {spec["file"]}')
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=int(manifest['cluster']['finish_tasks'])) as pool:
            futures=[]
            for relative in sorted(inventories[0]):
                dest = partial / relative.with_suffix(relative.suffix + '.gz')
                dest.parent.mkdir(parents=True, exist_ok=True)
                futures.append(pool.submit(merge_table,[run / relative for run in runs],dest))
            for future in futures:
                future.result()
        summaries = {'warning': 0, 'error': 0, 'skip': 0}
        fatal_patterns = manifest['study'].get('validation', {}).get('fatal_log_patterns', [r'\bFATAL\b', r'mass balance error'])
        with gzip.open(partial / 'guess_runs.log.gz', 'wt', encoding='utf-8') as combined:
            for run in runs:
                log = run / 'guess.log'
                if not log.is_file():
                    raise ConfigError(f'Missing model log: {log}')
                combined.write(f'\n--- {run.name}/guess.log ---\n')
                with log.open(encoding='utf-8', errors='replace') as source:
                    for line in source:
                        combined.write(line)
                        for term in summaries:
                            summaries[term] += int(term in line.lower())
                        if any(re.search(pattern, line, re.I) for pattern in fatal_patterns):
                            raise ConfigError(f'Fatal model diagnostic in {run.name}: {line.strip()}')
                # Preserve per-rank diagnostics/inputs without duplicating large output tables.
                for source in run.rglob('*'):
                    if source.is_file() and source.suffix in ('.log', '.txt', '.ins'):
                        dest = partial / 'ranks' / run.name / source.relative_to(run)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, dest)
        store.update(eid, 'validating')
        dbpath = partial / '.validation.sqlite'
        with closing(sqlite3.connect(dbpath)) as db:
            checks = [validate_table(partial / (s['file']+'.gz'), s, manifest, db) for s in manifest['outputs']]
        dbpath.unlink()
        for name in ('guess.ins', 'gridlist.txt', 'guess', 'execution.json', 'submit.sh', 'finishup.sh', 'mpi_run_guess_on_tmp.sh', 'changes.txt'):
            shutil.copy2(work / name, partial / name)
        if (work/'inputs').is_dir():shutil.copytree(work/'inputs',partial/'inputs')
        shutil.copytree(work / 'source', partial / 'source')
        shutil.copytree(work / 'runtime', partial / 'runtime', ignore=shutil.ignore_patterns('__pycache__'))
        for source in work.iterdir():
            if source.is_file() and (source.name.startswith(('guess_x.', 'finish_')) or source.name.endswith('-submission.json')):
                shutil.copy2(source, partial / source.name)
        atomic_json(partial / 'validation.json', {'passed': True, 'checks': checks, 'log_counts': summaries,
                    'limitations': ['Positive post-cut biomass is checked; exact planting density and species filtering require pilot inspection.',
                                    'Input ecology and source/executable correspondence depend on recorded user reviews.']})
        hashes = {p.relative_to(partial).as_posix(): digest(p) for p in partial.rglob('*') if p.is_file()}
        atomic_json(partial / 'checksums.json', hashes)
        atomic_json(partial / 'COMPLETE.json', {'execution_id': eid, 'completed': now(),
                    'checksums_sha256': digest(partial / 'checksums.json')})
        verify_archive(partial)
        partial.rename(archive)
        store.update(eid, 'complete', reason=None)
        return str(archive)
    except Exception as exc:
        store.update(eid, 'failed', reason=f'Collection failed: {exc}; retained {partial}')
        raise
    finally:
        lock.unlink(missing_ok=True)
