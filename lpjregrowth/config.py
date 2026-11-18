"""Configuration, validation, and reproducible instruction generation."""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from .instructions import ConfigError, Instructions, block, uncomment
from . import forcing, scenarios

ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.json-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write('\n')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_config(path):
    text = Path(path).read_text(encoding='utf-8-sig')
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise ConfigError('Install requirements.txt for YAML support; JSON also works.') from exc
        value = yaml.safe_load(text)
        if not isinstance(value, dict):
            raise ConfigError(f'Expected a configuration mapping in {path}')
        return value


def resolve_path(value, base):
    value = os.path.expandvars(os.path.expanduser(str(value)))
    path = Path(value)
    return path.resolve() if path.is_absolute() else (Path(base) / path).resolve()


def infer_roots(cluster, instruction_dir):
    """Fill missing roots using the cluster's mirrored data/work layout."""
    directory = Path(instruction_dir)
    for key, value in [('submission_root', directory / 'submissions'),
                       ('archive_root', directory / 'archives')]:
        if not cluster.get(key):
            cluster[key] = str(value)
    if not cluster.get('work_root'):
        data = Path(cluster.get('data_prefix', '/bg/data/lpj'))
        work = Path(cluster.get('work_prefix', '/bg/data/lpj/work'))
        if not data.is_absolute() or not work.is_absolute():
            raise ConfigError('data_prefix and work_prefix must be absolute paths')
        try:
            relative = directory.relative_to(data)
        except ValueError as exc:
            raise ConfigError('Instruction directory is outside data_prefix; set work_root explicitly or configure data_prefix/work_prefix') from exc
        if directory == work or work in directory.parents:
            raise ConfigError('Instruction directory is already beneath work_prefix; supply the original data directory or explicit work_root')
        if not relative.parts:
            raise ConfigError('Instruction directory must be below data_prefix')
        cluster['work_root'] = str(work / relative)
    return cluster


def read_grid(path):
    records, seen = [], set()
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        clean = uncomment(line).strip()
        if not clean or clean.startswith('#'):
            continue
        parts = clean.split()
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except (ValueError, IndexError) as exc:
            raise ConfigError(f'Gridlist must start each record with longitude latitude: {line}') from exc
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ConfigError(f'Invalid coordinates: {line}')
        key = (lon, lat)
        if key in seen:
            raise ConfigError(f'Duplicate grid cell: {key}')
        seen.add(key)
        records.append(clean)
    if not records:
        raise ConfigError('Gridlist has no sites')
    return records


def split_grid(records, processes):
    if processes < 1 or processes > len(records):
        raise ConfigError('Process count must be between 1 and number of grid cells')
    q, r = divmod(len(records), processes)
    result, start = [], 0
    for i in range(processes):
        count = q + (i < r)
        result.append(records[start:start+count])
        start += count
    return result


def experiment_rows(path):
    path = Path(path)
    if path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as handle:
            return list(csv.DictReader(handle))
    value = read_config(path)
    return value['experiments']


class Study:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.config = read_config(self.path)
        c = self.config
        self.cluster = read_config(resolve_path(c['cluster'], self.path.parent))
        self.cluster_path = resolve_path(c['cluster'], self.path.parent)
        instruction_dir = resolve_path(c['ins_directory'], self.path.parent) if c.get('ins_directory') else None
        if c.get('main_ins'):
            self.base = resolve_path(c['main_ins'], instruction_dir or self.path.parent)
        elif instruction_dir:
            candidates = sorted(instruction_dir.glob('*.ins'))
            if len(candidates) != 1:
                raise ConfigError('Set main_ins to the entry filename when ins_directory contains zero or multiple .ins files')
            self.base = candidates[0].resolve()
        else:
            raise ConfigError('Supply main_ins or ins_directory')
        self.instruction_dir = instruction_dir or self.base.parent
        infer_roots(self.cluster, self.instruction_dir)
        self.grid = resolve_path(c['gridlist'], self.path.parent)
        self.root = resolve_path(c['workspace'], self.path.parent) if c.get('workspace') else self.instruction_dir / 'regrowth-workspace'
        self.ins = Instructions(self.base)
        self.records = read_grid(self.grid)
        self.stand = c.get('stand', 'Forest')
        self.management = c.get('management', 'Forest_management')
        self.cut_year = int(c['cut_year'])
        self.first_year = int(c.get('first_year', self.ins.scalar('firsthistyear', 0)))
        self.last_year = int(c.get('last_year', self.ins.scalar('lasthistyear', 0)))
        self.outputs = c['outputs']
        for spec in self.outputs:
            if spec.get('values') == 'TREE_PFTS':
                spec['values'] = [name for kind,name in self.ins.definitions if kind == 'pft' and self.ins.resolve(kind,name).get('include') == ['1'] and self.ins.resolve(kind,name).get('lifeform') == ['tree']]
        self.pfts = c['selection']
        self.experiments = []
        for row in experiment_rows(resolve_path(c['experiments'], self.path.parent)):
            unknown = set(row) - {'id', 'densities', 'reestab', 'twig_removal'}
            if unknown:
                raise ConfigError(f'Unknown experiment fields: {unknown}')
            raw = row['densities']
            dens = list(map(float, raw.split())) if isinstance(raw, str) else list(map(float, raw))
            self.experiments.append(dict(id=row['id'], densities=dens,
                                         reestab=str(row['reestab']).upper(),
                                         twig_removal=float(row['twig_removal'])))
        self.experiments = scenarios.expand(self) if c.get("scenarios") is not None else forcing.expand(c, self.experiments, self.first_year, self.last_year, self.cut_year)

    def cluster_path_value(self, name):
        return resolve_path(self.cluster[name], self.cluster_path.parent)

    @property
    def processes(self):
        return int(self.cluster['nodes']) * int(self.cluster['processes_per_node'])

    def selected(self, ids=None):
        if not ids:
            return self.experiments
        selected = [e for e in self.experiments if e['id'] in ids]
        if set(ids) != {e['id'] for e in selected}:
            raise ConfigError('Unknown experiment selection')
        return selected

    def management_values(self, exp):
        natural = self.config.get("regeneration", "planted") == "natural"
        values = {
            'cutfirstyear': 1, 'clearcut_first_manageyear': 1,
            'firstmanageyear': self.cut_year, 'firstcutyear': self.cut_year,
            'harvest_system': 'clearcut', 'cutinterval': 0,
            'ifclearcut_by_density': 0, 'ifclearcut_optimal_age': 0,
            'ifthin_reineke': 0, 'distribute_patch_ages': 0,
            'distribute_cuttings_among_patches': 0,
            'suppress_fire': 1, 'suppress_disturbance': 1,
            'stochmort': 0, 'stochestab': 0,
            'planting_system': 'SELECTION', 'selection': ' '.join(self.pfts),
            'set_planting_density': 1,
            'plantdensity': ' '.join(f'{d:g}' for d in exp['densities']),
            'reestab': exp['reestab'], 'res_outtake_twig_cc': exp['twig_removal'],
            'killgrass_at_cc': int(self.config.get('killgrass_at_cc', 0)),
        }
        if natural:
            values.update(planting_system='', selection='', set_planting_density=0,
                          plantdensity='', reestab='ALL', relaxed_establishment=0)
        return values

    def validate(self, remote=False):
        c = self.config
        if c.get("scenarios") is not None and not getattr(self,"scenario_child",False):
            from .scenario_analysis import comparisons
            comparisons(self)
            warnings = []
            for exp in self.experiments:
                warnings.extend(scenarios.child(self,exp).validate(remote))
            return sorted(set(warnings))
        warnings = []
        if getattr(self,'scenario_child',False):
            scenarios.pft_text(self,self.experiments[0])
        if c.get('forcing_experiment') is not None:
            warnings.append('Forcing comparison: independent runs use identical management and original inputs; patched cfx executable required.')
            if not self.ins.params.get('file_co2', ('',))[0]:
                raise ConfigError('Forcing comparison requires file_co2 in the supplied instructions')
            if self.experiments[0]['forcing']['start_year'] < self.cut_year:
                warnings.append('Forcing changes begin before cutting; pre-cut ecosystem states may differ.')
        for name in (self.stand, self.management):
            if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
                raise ConfigError('Stand and management names must be simple identifiers')
        if len(self.experiments) == 0:
            raise ConfigError('No experiments defined')
        if not self.first_year <= self.cut_year < self.last_year:
            raise ConfigError('Require first_year <= cut_year < last_year')
        split_grid(self.records, self.processes)
        for name in ('nodes', 'processes_per_node', 'finish_tasks', 'max_active'):
            if int(self.cluster[name]) < 1:
                raise ConfigError(f'{name} must be positive')
        for name in ('partition', 'finish_partition'):
            if not re.fullmatch(r'[A-Za-z0-9_,.-]+', str(self.cluster[name])):
                raise ConfigError(f'Invalid Slurm {name}')
        for name in ('walltime', 'finish_walltime', 'account', 'qos', 'memory'):
            value = self.cluster.get(name)
            if value and not re.fullmatch(r'[A-Za-z0-9_:.,+-]+', str(value)):
                raise ConfigError(f'Invalid Slurm {name}')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', c.get('input_module', 'cfx')):
            raise ConfigError('Invalid input module')
        regeneration = c.get('regeneration', 'planted')
        if regeneration not in ('natural', 'planted'):
            raise ConfigError('regeneration must be natural or planted')
        if regeneration == 'natural' and c.get('experiment_mode') == 'landuse_change':
            raise ConfigError('Natural regeneration override is only supported for controlled_regrowth; landuse_change preserves source management')
        if regeneration == 'planted' and (not self.pfts or len(set(self.pfts)) != len(self.pfts)):
            raise ConfigError('selection must list distinct global tree PFTs')
        for pft in self.pfts:
            values = self.ins.resolve('pft', pft)
            if values.get('include', ['0']) != ['1'] or values.get('lifeform') != ['tree']:
                raise ConfigError(f'{pft} must be included and have lifeform tree')
        ids = set()
        for exp in self.experiments:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,59}', exp['id']) or exp['id'] in ids:
                raise ConfigError(f'Invalid or duplicate experiment ID: {exp["id"]}')
            ids.add(exp['id'])
            if regeneration == 'planted' and (len(exp['densities']) != len(self.pfts) or any(not math.isfinite(x) or x <= 0 for x in exp['densities'])):
                raise ConfigError(f'{exp["id"]}: one positive finite density per PFT is required')
            if exp['reestab'] not in ('NONE', 'ALL', 'RESTRICTED') or not 0 <= exp['twig_removal'] <= 1:
                raise ConfigError(f'{exp["id"]}: invalid recruitment or removal fraction')
        if c.get('baseline', 'baseline') not in ids:
            raise ConfigError('Baseline experiment is missing')
        landuse_mode = c.get('experiment_mode') == 'landuse_change'
        stand = self.ins.resolve('st', self.stand)
        if stand.get('management1') != [self.management]:
            raise ConfigError('Target stand must reference the configured management1')
        if stand.get('landcover') != ['forest']:
            raise ConfigError('Target stand must have landcover forest')
        if not landuse_mode and any(k.startswith(('management2', 'management3', 'mt2_', 'mt3_', 'startman', 'rotation')) for k in stand):
            raise ConfigError('Management rotations require manual removal for the single-cut study')
        for key in (('mt', self.management), ('st', self.stand)):
            if len(self.ins.definitions.get(key, [])) != 1:
                raise ConfigError(f'Require one explicit target definition: {key}')
        for kind, name in self.ins.definitions:
            if kind == 'st' and name != self.stand:
                values = self.ins.resolve(kind, name)
                if not landuse_mode and values.get('stinclude') == ['1'] and values.get('landcover') == ['forest']:
                    raise ConfigError(f'Other active forest stand {name}; isolate this study first')
                if not landuse_mode and values.get('management1') == [self.management]:
                    raise ConfigError('Target management is shared by another stand')
        # Fail on external inputs capable of overriding the single-cut protocol.
        risky = ('cutinterval', 'firstmanage', 'woodharv', 'dist_', 'storm_prob', 'forest_init', 'target', 'grossLUC', 'grossSTC')
        for name, (value, _) in self.ins.params.items():
            prepared_disabled = c.get('prepared_landuse') and not landuse_mode and ('grossluc' in name.lower() or 'grossstc' in name.lower() or 'woodharv' in name.lower())
            if not landuse_mode and not prepared_disabled and value and any(part.lower() in name.lower() for part in risky):
                raise ConfigError(f'External input conflicts with controlled single cut: {name}')
        if self.ins.scalar('storm_mortality', '0') != '0':
            raise ConfigError('Disable storm_mortality explicitly for this study')
        if not c.get('disturbance_audit_confirmed', False):
            warnings.append('Storm/insect and external-disturbance audit needs confirmation before submission.')
        output_ids, output_files = set(), set()
        for spec in self.outputs:
            required = {'variable', 'keyword', 'file', 'unit', 'area_basis', 'key', 'year_column', 'values'}
            if required - set(spec):
                raise ConfigError(f'Incomplete output specification: {spec}')
            if c.get('scenarios') is not None: scenarios.identifier(spec['variable'])
            if spec['variable'] in output_ids or spec['file'] in output_files:
                raise ConfigError('Output variables and filenames must be unique')
            output_ids.add(spec['variable']); output_files.add(spec['file'])
            if not re.fullmatch(r'[A-Za-z0-9_.-]+\.out', spec['file']):
                raise ConfigError('Output filenames must be simple .out basenames')
            if spec['key'][:2] != ['Lon', 'Lat'] or spec['year_column'] not in spec['key']:
                raise ConfigError('Output keys must start with Lon, Lat and include the year column')
            if not spec['values']:
                raise ConfigError('Each output needs at least one selected value column')
        for role in (('biomass',) if landuse_mode else ('biomass', 'harvest_event', 'harvest_total')):
            if not any(s.get('role') == role for s in self.outputs):
                raise ConfigError(f'Missing required output role: {role}')
        biomass = c.get('biomass', {})
        if biomass.get('output_unit','Mg dry matter ha-1') not in ('Mg dry matter ha-1','kg dry matter m-2'):
            raise ConfigError('Unsupported biomass output_unit')
        if biomass.get('kind') not in ('carbon', 'dry_mass'):
            raise ConfigError('biomass.kind must be carbon or dry_mass')
        if biomass['kind'] == 'dry_mass' and not 0 < float(biomass.get('carbon_fraction', 0)) <= 1:
            raise ConfigError('Dry biomass requires an explicit carbon fraction')
        if not biomass.get('definition_reviewed', False):
            warnings.append('Aboveground output definition must be reviewed against the executable before submission.')
        if not self.ins.params.get('file_lu', ('',))[0]:
            warnings.append('No land-cover input supplied; confirm intended forest area fractions.')
        warnings.append('Independent spin-ups may differ across regeneration treatments; review pre-cut comparisons.')
        warnings.append('Stand persistence and land-cover coverage through the recovery period require input audit.')
        if c.get('model_source'):
            source = resolve_path(c['model_source'], self.path.parent)
            text = '\n'.join(p.read_text(encoding='utf-8-sig', errors='replace') for d in ('framework', 'modules', 'cru') for p in (source / d).rglob('*.cpp'))
            names = set(re.findall(r'(?:declareitem|declare_parameter)\s*\(\s*"([^"]+)"', text))
            generated_names = set(self.management_values(self.experiments[0])) | {s['keyword'] for s in self.outputs}
            generated_names |= set().union(*(set(forcing.settings(e)) for e in self.experiments))
            generated_names |= set().union(*(set(v) for e in self.experiments for v in e.get('scenario',{}).get('pft_overrides',{}).values()))
            generated_names |= {'outputdirectory', 'firsthistyear', 'lasthistyear', 'run_landcover', 'run_forest'}
            missing = generated_names - names
            if missing:
                raise ConfigError(f'Generated keywords not found in configured source: {sorted(missing)}')
        else:
            warnings.append('No model_source supplied: generated keywords need executable-specific review.')
        if remote:
            if any(self.cluster[name] == 'CHANGE_ME' for name in ('partition','finish_partition')):
                raise ConfigError('Set the cluster partitions before submission')
            if os.name != 'posix':
                raise ConfigError('Cluster execution must run on Linux/POSIX')
            for flag in ('disturbance_audit_confirmed', 'landcover_audit_confirmed', 'executable_compatibility_confirmed'):
                if not c.get(flag):
                    raise ConfigError(f'Submission requires reviewed setting: {flag}')
            if not biomass.get('definition_reviewed') or not biomass.get('definition'):
                raise ConfigError('Submission requires a documented, reviewed biomass definition')
            exe = self.cluster_path_value('executable')
            if not exe.is_file() or not os.access(exe, os.X_OK):
                raise ConfigError(f'Model executable is missing or not executable: {exe}')
            if not self.cluster_path_value('python').is_file():
                raise ConfigError('cluster.python must identify the cluster Python executable')
            for name, (value, parent) in self.ins.params.items():
                if name.startswith('file_') and value and 'gridlist' not in name:
                    path = resolve_path(value, parent)
                    if not path.is_file():
                        raise ConfigError(f'Missing supplied input {name}: {path}')
        return warnings

    def generated_text(self, exp):
        landuse_mode = self.config.get('experiment_mode') == 'landuse_change'
        pft_text, omitted = scenarios.pft_text(self,exp) if 'scenario' in exp else ('',set())
        if not landuse_mode: omitted |= {('mt',self.management),('st',self.stand)}
        text = self.ins.flatten(omit=omitted)
        text += pft_text
        # Replace the target definitions with fully explicit controlled definitions.
        text += '\n! Generated experiment; see manifest for effective scenario and PFT settings.\n'
        if not landuse_mode:
            text += block('mt', self.management, self.management_values(exp))
            text += block('st', self.stand, {'management1': self.management, 'stinclude': 1,
                                          'landcover': 'forest', 'naturalveg': 'all', 'intercrop': 'nointercrop'})
        text += ('run_landcover 1\n' if landuse_mode else 'run_landcover 1\nrun_forest 1\n') + 'outputdirectory "./"\n'
        text += f'param "file_gridlist" (str "gridlist.txt")\nfirsthistyear {self.first_year}\nlasthistyear {self.last_year}\n'
        if forcing.settings(exp):
            text += '\n! Forcing controls generated from the study configuration\n'
        for name, value in forcing.settings(exp).items():
            text += f'{name} {value}\n'
        for spec in self.outputs:
            text += f'{spec["keyword"]} "{spec["file"]}"\n'
        return text

    def generate(self, ids=None):
        self.validate()
        if self.config.get('scenarios') is not None and not getattr(self,'scenario_child',False):
            return [p for exp in self.selected(ids) for p in scenarios.child(self,exp).generate()]
        result = []
        for exp in self.selected(ids):
            dest = self.root / 'generated' / exp['id']
            text = self.generated_text(exp)
            replacements = {}
            if 'scenario' in exp or self.config.get('prepared_landuse'):
                replacements = scenarios.input_overrides(self,exp,dest)
                for key,value in replacements.items():
                    if value and not Path(value).is_file(): raise ConfigError(f'Missing scenario input: {value}')
                    if any(ch in value for ch in ('\"','\n','\r')): raise ConfigError('Unsafe input path')
                    text += f'param "{key}" (str "{value}")\n'
            target = dest / 'guess.ins'
            # Content is deterministic; submitted work is always a separate immutable copy.
            write_text(target, text)
            if forcing.settings(exp):
                parsed = Instructions(target)
                if any(parsed.scalar(k) != str(v) for k,v in forcing.settings(exp).items()):
                    raise ConfigError('Generated forcing instructions do not match the JSON treatment')
                atomic_json(dest / 'forcing-settings.json', forcing.settings(exp))
            write_text(dest / 'gridlist.txt', '\n'.join(self.records) + '\n')
            provenance = []
            for i, path in enumerate(self.ins.files):
                name = f'{i:03d}_{path.name}'
                write_text(dest / 'source' / name, self.ins.files[path])
                provenance.append({'path': str(path), 'sha256': digest(path), 'copy': f'source/{name}'})
            manifest = {'experiment': exp, 'selection': self.pfts, 'study': self.config,
                        'source_files': provenance, 'main_sha256': digest(target),
                        'grid_sha256': digest(dest / 'gridlist.txt'),
                        'staging_files': ['guess.ins', 'gridlist.txt'],
                        'original_management': self.ins.resolve('mt', self.management),
                        'generated_management': self.ins.resolve('mt',self.management) if self.config.get('experiment_mode')=='landuse_change' else self.management_values(exp),
                        'forcing_settings': forcing.settings(exp),
                        'original_stand': self.ins.resolve('st', self.stand),
                        'global_pft_physiology_changed': bool(exp.get('scenario',{}).get('pft_overrides')),
                        'scenario': exp.get('scenario'),
                        'effective_inputs': {k:str(resolve_path(v,parent)) if v else '' for k,(v,parent) in Instructions(target).params.items() if k.startswith('file_') and 'gridlist' not in k},
                        'scenario_input_hashes': {k:digest(resolve_path(v,parent)) for k,(v,parent) in Instructions(target).params.items() if k in replacements and v and resolve_path(v,parent).is_file()} if 'scenario' in exp or self.config.get('prepared_landuse') else {}}
            atomic_json(dest / 'manifest.json', manifest)
            write_text(dest / 'changes.txt', json.dumps({'before': manifest['original_management'],
                        'after': manifest['generated_management'], 'forcing_settings': forcing.settings(exp), 'stand_before': manifest['original_stand'],
                        'scenario': exp.get('scenario'), 'effective_pft_overrides': exp.get('scenario',{}).get('pft_overrides',{}),
                        'note': 'Original stands preserved.' if self.config.get('experiment_mode')=='landuse_change' else 'Target stand replaced with explicit forest stand; review discarded inherited settings.'}, indent=2) + '\n')
            result.append(str(dest))
        return result
