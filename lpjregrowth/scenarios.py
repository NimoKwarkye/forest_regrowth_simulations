"""Explicit scenario expansion; original instructions remain immutable."""
import copy
import math
import re
from pathlib import Path
from .instructions import ConfigError


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,59}', value):
        raise ConfigError(f'Invalid identifier: {value}')
    return value


def region_sites(records, region):
    allowed = {'longitude', 'latitude', 'sites', 'weighting'}
    if set(region) - allowed:
        raise ConfigError('Unknown region settings')
    lon = region.get('longitude', [-180, 180]); lat = region.get('latitude', [-90, 90])
    if len(lon) != 2 or len(lat) != 2 or not all(math.isfinite(float(v)) for v in lon+lat):
        raise ConfigError('Region bounds must contain two finite coordinates')
    if not all(-180 <= v <= 180 for v in lon) or not -90 <= lat[0] <= lat[1] <= 90:
        raise ConfigError('Invalid region bounds')
    explicit = {tuple(map(float, x)) for x in region['sites']} if 'sites' in region else None
    available = {tuple(map(float, line.split()[:2])) for line in records}
    if explicit is not None and not explicit <= available:
        raise ConfigError('Region contains sites absent from gridlist')
    result = []
    for line in records:
        x,y = map(float,line.split()[:2])
        inside = lon[0] <= x <= lon[1] if lon[0] <= lon[1] else x >= lon[0] or x <= lon[1]
        if inside and lat[0] <= y <= lat[1] and (explicit is None or (x,y) in explicit):
            result.append(line)
    if region.get('weighting','equal') not in ('equal','cell_area','forest_area'):
        raise ConfigError('Region weighting must be equal, cell_area, or forest_area')
    return result


def climate_settings(climate, co2, first, last):
    settings = dict(extend_climate=0, fixed_co2=0, fixed_spinup_climate=0, restart=0, save_state=0)
    for spec, allowed in [(climate, {'mode','window_start','window_end','apply_from'}),
                          (co2, {'mode','reference_year','ppm','apply_from'})]:
        if set(spec)-allowed:
            raise ConfigError(f'Unknown forcing fields: {set(spec)-allowed}')
    mode = climate.get('mode','historical')
    if mode == 'recycle':
        a,b,start = (climate[k] for k in ('window_start','window_end','apply_from'))
        if any(type(v) is not int for v in (a,b,start)) or not (1850 <= a <= b <= 2500 and b-a < 100 and first <= start <= last):
            raise ConfigError('Invalid climate window/switch year (maximum 100 years)')
        settings.update(extend_climate=1,extend_climate_nyears=b-a+1,extend_climate_startyear=b,climate_recycle_from_year=start)
    elif mode != 'historical':
        raise ConfigError('Climate mode must be historical or recycle')
    mode = co2.get('mode','historical')
    if mode in ('fixed_year','fixed_ppm'):
        start = co2['apply_from']
        if type(start) is not int or not first <= start <= last:
            raise ConfigError('CO2 apply_from must fall within simulation period')
        if mode == 'fixed_year':
            year = co2['reference_year']
            if type(year) is not int or not 0 <= year <= 10000:
                raise ConfigError('Invalid CO2 reference year')
            settings.update(fixed_co2=1,fixed_co2_year=year,fixed_co2_from_year=start)
        elif not math.isfinite(float(co2['ppm'])) or float(co2['ppm']) <= 0:
            raise ConfigError('CO2 ppm must be positive and finite')
    elif mode != 'historical':
        raise ConfigError('CO2 mode must be historical, fixed_year, or fixed_ppm')
    return settings


def effective_sla(ins, name):
    p = ins.resolve('pft',name)
    if ins.scalar('ifcalcsla','0') == '1' and not (p.get('phenology') == ['cropgreen'] and ins.scalar('ifnlim','0') == '1'):
        leaflong = float(p['leaflong'][0])
        physiognomy = p['leafphysiognomy'][0].lower()
        if physiognomy not in ('broadleaf','needleleaf') or leaflong <= 0:
            raise ConfigError(f'Cannot resolve calculated SLA for {name}')
        a,b = (2.41,.38) if physiognomy == 'broadleaf' else (2.29,.4)
        return .2 * 10**(a-b*math.log10(12*leaflong))
    return float(p['sla'][0])


def expand(study):
    c=study.config
    if c.get('forcing_experiment') is not None:
        raise ConfigError('Use scenarios or forcing_experiment, not both')
    regions=c.get('regions',{})
    for name,r in regions.items():
        identifier(name); region_sites(study.records,r)
    bases={e['id']:e for e in study.experiments}
    result=[]
    allowed={'id','base','sites','climate','co2','pft_overrides','sweep','management','landuse','mode','label'}
    for raw in c['scenarios']:
        if set(raw)-allowed:
            raise ConfigError(f'Unknown scenario fields: {set(raw)-allowed}')
        identifier(raw['id'])
        base=raw.get('base',c.get('baseline','baseline'))
        if base not in bases: raise ConfigError(f'Unknown management base: {base}')
        variants=[copy.deepcopy(raw)]
        if 'sweep' in raw:
            sweep=copy.deepcopy(raw['sweep'])
            if sweep.get('pfts') == 'NATURAL_TREE_PFTS':
                sweep['pfts'] = [name for kind,name in study.ins.definitions if kind == 'pft'
                    and study.ins.resolve(kind,name).get('include') == ['1']
                    and study.ins.resolve(kind,name).get('lifeform') == ['tree']
                    and study.ins.resolve(kind,name).get('landcover') == ['natural']]
            if set(sweep)-{'parameter','pfts','values','multipliers'} or sweep['parameter'] not in ('sla','k_latosa'):
                raise ConfigError('Sweep supports sla or k_latosa only')
            if ('values' in sweep)==('multipliers' in sweep) or not sweep['pfts']:
                raise ConfigError('Sweep needs pfts and exactly one of values/multipliers')
            variants=[]
            for i,value in enumerate(sweep.get('values',sweep.get('multipliers'))):
                if not math.isfinite(float(value)) or float(value)<=0: raise ConfigError('Invalid sweep value')
                v=copy.deepcopy(raw);v['id']=identifier(f'{raw["id"]}_{i+1}')
                v['sweep_value']=float(value);v['sweep_parameter']=sweep['parameter'];v['sweep_family']=raw['id']
                overrides=v.setdefault('pft_overrides',{})
                for pft in sweep['pfts']:
                    original=effective_sla(study.ins,pft) if sweep['parameter']=='sla' else float(study.ins.resolve('pft',pft)[sweep['parameter']][0])
                    overrides.setdefault(pft,{})[sweep['parameter']]=float(value)*(original if 'multipliers' in sweep else 1)
                variants.append(v)
        for v in variants:
            v.pop('sweep',None)
            mode=v.get('mode','controlled_regrowth')
            if mode not in ('controlled_regrowth','landuse_change'): raise ConfigError('Unknown scenario mode')
            v['mode']=mode
            settings=climate_settings(v.get('climate',{}),v.get('co2',{}),study.first_year,study.last_year)
            if study.config.get('input_module','cfx')!='cfx': raise ConfigError('Scenarios require patched cfx input')
            for pft,overrides in v.get('pft_overrides',{}).items():
                study.ins.resolve('pft',pft)
                for key,value in overrides.items():
                    bounds={'sla':(1,1000),'k_latosa':(100,100000)}
                    if key not in bounds or not bounds[key][0]<=float(value)<=bounds[key][1]:
                        raise ConfigError(f'Invalid PFT override: {pft}.{key}={value}')
            result.append({**bases[base], 'id':v['id'], 'scenario':v,
                           'forcing':{'settings':settings}})
    if not result or len({e['id'] for e in result})!=len(result): raise ConfigError('Scenarios must have unique ids')
    return result


def child(study, exp):
    s=copy.copy(study);s.config=copy.deepcopy(study.config);s.cluster=copy.deepcopy(study.cluster)
    s.scenario_child=True;s.experiments=[copy.deepcopy(exp)]
    v=exp['scenario'];s.config['baseline']=exp['id'];s.config['experiment_mode']=v['mode']
    if 'sites' in v:
        if v['sites'] not in study.config.get('regions',{}): raise ConfigError('Scenario sites must name a region')
        s.records=region_sites(study.records,study.config['regions'][v['sites']])
        if not s.records:raise ConfigError('Scenario simulation subset is empty; omit scenario sites to simulate the supplied gridlist. Empty analysis regions are allowed.')
    management=v.get('management',{})
    if set(management)-{'selection','densities','twig_removal','reestab','cut_year','stand','management'}:
        raise ConfigError('Unknown management profile field')
    for field in ('densities','twig_removal','reestab'):
        if field in management:s.experiments[0][field]=management[field]
    s.pfts=management.get('selection',study.pfts)
    s.cut_year=int(management.get('cut_year',study.cut_year))
    s.stand=management.get('stand',study.stand);s.management=management.get('management',study.management)
    s.config['selection']=s.pfts;s.config['cut_year']=s.cut_year
    # No empty MPI ranks: keep the established nodes x ranks-per-node layout.
    if s.processes>len(s.records):
        s.cluster['nodes']=1;s.cluster['processes_per_node']=len(s.records)
    if v['mode']=='landuse_change':s.cut_year=s.first_year;s.config['cut_year']=s.first_year
    return s


def pft_text(study, exp):
    overrides=copy.deepcopy(exp['scenario'].get('pft_overrides',{}))
    if not overrides:return '',set()
    sla=any('sla' in values for values in overrides.values())
    if sla:
        for kind,name in study.ins.definitions:
            if kind=='pft':
                overrides.setdefault(name,{})
                overrides[name].setdefault('sla',effective_sla(study.ins,name))
    chunks=['ifcalcsla 0\n'] if sla else []
    for name,changes in overrides.items():
        values=study.ins.resolve('pft',name)
        values.update({k:[str(v)] for k,v in changes.items()})
        chunks.append(f'pft "{name}" (\n'+''.join('    '+k+' '+ ' '.join('"'+t+'"' if not re.fullmatch(r'[-+0-9.eE]+',t) else t for t in tokens)+'\n' for k,tokens in values.items())+')\n')
    return ''.join(chunks),{('pft',n) for n in overrides}


def input_overrides(study, exp, dest):
    """Build explicit annual input products, retaining pre-treatment years."""
    from .config import resolve_path, write_text
    v=exp.get('scenario',{'mode':study.config.get('experiment_mode','controlled_regrowth')}); replacements={}
    prepared=study.config.get('prepared_landuse',{})
    if prepared:
        import shutil
        key='dynamic' if v.get('mode')=='landuse_change' else 'forest_only'
        if key not in prepared:raise ConfigError(f'Missing prepared_landuse.{key}')
        source=resolve_path(prepared[key],study.path.parent)
        target=dest/'inputs'/'prepared_landuse.txt';target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target);replacements['file_lu']=target.as_posix()
        if key=='forest_only':
            # Controlled all-forest runs must not retain external land transitions.
            for name in study.ins.params:
                if name!='file_lu' and (name.startswith('file_lu') or 'grossluc' in name.lower() or 'grossstc' in name.lower() or 'woodharv' in name.lower()):replacements[name]=''
    co2=v.get('co2',{})
    if co2.get('mode')=='fixed_ppm':
        path,parent=study.ins.params.get('file_co2',('',study.path.parent))
        if not path:raise ConfigError('fixed_ppm requires file_co2')
        values={}
        for line in resolve_path(path,parent).read_text().splitlines():
            if not line.strip() or line.lstrip().startswith(('#','!')):continue
            fields=line.split()
            if len(fields)!=2:raise ConfigError('CO2 input must be year concentration pairs')
            year=int(fields[0]);value=float(fields[1])
            if year in values or not math.isfinite(value) or value<=0:raise ConfigError('Invalid CO2 series')
            values[year]=value
        start=co2['apply_from']
        if any(y not in values for y in range(study.first_year,start)):raise ConfigError('CO2 history is incomplete')
        values.update({y:float(co2['ppm']) for y in range(start,study.last_year+1)})
        target=dest/'inputs'/'co2.txt';write_text(target,''.join(f'{y} {x:.12g}\n' for y,x in sorted(values.items())))
        replacements['file_co2']=target.as_posix()
    land=v.get('landuse',{})
    if land:
        if v['mode']!='landuse_change':raise ConfigError('Land-use treatments require landuse_change mode')
        if set(land)-{'mode','files','reference_year','apply_from','freeze_inputs','zero_inputs','audit_confirmed'}:
            raise ConfigError('Unknown landuse settings')
        if not land.get('audit_confirmed'):raise ConfigError('Land-use input/transition audit must be confirmed')
        mode=land.get('mode','supplied')
        if mode not in ('supplied','fixed_year'):raise ConfigError('Unknown landuse mode')
        for key,path in land.get('files',{}).items():
            if key not in study.ins.params or not key.startswith('file_'):raise ConfigError(f'Unknown landuse input {key}')
            if path:
                import shutil
                source=resolve_path(path,study.path.parent)
                target=dest/'inputs'/(key+source.suffix)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,target)
                replacements[key]=target.as_posix()
            else:replacements[key]=''
        if mode=='fixed_year':
            start=land['apply_from'];ref=land['reference_year']
            if type(start) is not int or type(ref) is not int or not study.first_year<=start<=study.last_year:raise ConfigError('Invalid landuse years')
            freeze=set(land.get('freeze_inputs',[]));zero=set(land.get('zero_inputs',[]))
            if not freeze or freeze&zero:raise ConfigError('Fixed landuse needs disjoint freeze_inputs and zero_inputs')
            active={k for k,(value,_) in study.ins.params.items() if value and (k.startswith('file_lu') or 'grossluc' in k.lower() or 'grossstc' in k.lower() or 'woodharv' in k.lower())}
            active |= {k for k,value in replacements.items() if value and k != 'file_co2'}
            active -= {k for k,value in replacements.items() if not value}
            if active-(freeze|zero):raise ConfigError(f'Fixed landuse must explicitly freeze or zero all active landuse/transition inputs: {active-(freeze|zero)}')
            for key in freeze|zero:
                if not (key.startswith('file_lu') or 'grossluc' in key.lower() or 'grossstc' in key.lower() or 'woodharv' in key.lower()):raise ConfigError(f'Not a supported landuse input: {key}')
                if key not in study.ins.params:raise ConfigError(f'Unknown input {key}')
                path,parent=study.ins.params[key]
                source=Path(replacements[key]) if key in replacements else resolve_path(path,parent)
                target=dest/'inputs'/f'{key}.txt'
                freeze_table(source,target,study,ref,start,key in zero)
                replacements[key]=target.as_posix()
    return replacements


def freeze_table(source,target,study,reference,start,zero):
    from .collect import read_table
    from .config import write_text
    sites={tuple(map(float,r.split()[:2])) for r in study.records}; rows={};header=None
    for header,row,_ in read_table(source):
        if header[:3]!=['Lon','Lat','Year']:raise ConfigError('Land-use transformation supports annual Lon Lat Year tables only; provide prepared files for other formats')
        site=(row['Lon'],row['Lat']);year=row['Year']
        if site not in sites:continue
        if year!=int(year) or (*site,int(year)) in rows:raise ConfigError('Invalid/duplicate landuse year')
        rows[(*site,int(year))]=[row[k] for k in header[3:]]
    if header is None:raise ConfigError('Empty landuse table')
    lines=[' '.join(header)]
    for site in sorted(sites):
        if (*site,reference) not in rows:raise ConfigError(f'Landuse reference year absent at {site}')
        years=set(y for x,z,y in rows if (x,z)==site)|set(range(study.first_year,study.last_year+1))
        for year in sorted(years):
            values=([0.]*(len(header)-3) if zero else rows[(*site,reference)]) if year>=start else rows.get((*site,year))
            if values is None:raise ConfigError(f'Incomplete landuse history: {site}, {year}')
            lines.append(' '.join(map(str,(*site,year,*values))))
    write_text(target,'\n'.join(lines)+'\n')
