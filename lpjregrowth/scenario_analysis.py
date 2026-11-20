"""Named, matched-site scenario comparisons and regional plots."""
import csv
import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from .instructions import ConfigError
from .config import atomic_json
from .scenarios import identifier, region_sites, child
from .workflow import Store
from .collect import read_table, verify_archive


def signature(study):
    return hashlib.sha256(json.dumps({'experiments':study.experiments,'regions':study.config.get('regions',{}),
        'comparisons':study.config.get('comparisons',{}),'analysis':study.config.get('analysis',{}),
        'outputs':study.outputs,'biomass':study.config['biomass']},sort_keys=True).encode()).hexdigest()


def comparisons(study):
    ids={e['id'] for e in study.experiments}
    specs=study.config.get('comparisons')
    if not specs:
        specs={'all':{'experiments':[e['id'] for e in study.experiments],'baseline':study.experiments[0]['id']}}
    specs={name:{**spec,'regions':spec.get('regions',list(study.config.get('regions',{})) or ['all'])} for name,spec in specs.items()}
    for name,spec in specs.items():
        identifier(name)
        if set(spec)-{'experiments','baseline','regions','axis','vary'}:raise ConfigError('Unknown comparison field')
        selected=spec['experiments']
        if not selected or len(set(selected))!=len(selected) or set(selected)-ids or spec['baseline'] not in selected:
            raise ConfigError(f'Invalid comparison experiments: {name}')
        if spec.get('axis','calendar_year') not in ('calendar_year','years_since_cut'):raise ConfigError('Invalid comparison axis')
        if set(spec.get('regions',['all']))-({'all'}|set(study.config.get('regions',{}))):raise ConfigError('Unknown comparison region')
    return specs


def total(row,spec):
    values=[row[k] for k in spec['values']]
    op=spec.get('component_aggregation','sum')
    if op=='sum':return sum(values)
    if op=='mean':return sum(values)/len(values)
    if op=='single' and len(values)==1:return values[0]
    raise ConfigError('component_aggregation must be sum, mean, or single (one column)')


def area_weights(study):
    options=study.config.get('analysis',{})
    areas={}
    if options.get('cell_areas'):
        from .config import resolve_path
        with resolve_path(options['cell_areas'],study.path.parent).open() as f:
            for row in csv.DictReader(f):
                site=(float(row['longitude']),float(row['latitude']));a=float(row['area_m2'])
                if site in areas or not math.isfinite(a) or a<=0:raise ConfigError('Invalid/duplicate cell area')
                areas[site]=a
    elif options.get('grid_resolution_degrees'):
        dx,dy=map(float,options['grid_resolution_degrees'])
        if not 0<dx<=360 or not 0<dy<=180:raise ConfigError('Invalid grid resolution')
        for line in study.records:
            x,y=map(float,line.split()[:2])
            areas[x,y]=6371008.8**2*math.radians(dx)*(math.sin(math.radians(min(90,y+dy/2)))-math.sin(math.radians(max(-90,y-dy/2))))
    return areas


def analyze(study,ids=None):
    from .analysis import biomass_value
    study.validate()
    specs=comparisons(study)
    selected={e['id'] for e in study.selected(ids)}
    active={k:v for k,v in specs.items() if set(v['experiments'])<=selected}
    if not active:raise ConfigError('No complete comparison group selected')
    if any(set(v['experiments'])&selected and not set(v['experiments'])<=selected for v in specs.values()):
        raise ConfigError('Select every experiment in each requested comparison')
    chosen={r['experiment']:r for r in Store(study.root).rows() if r['status']=='complete' and r['experiment'] in selected}
    if selected-chosen.keys():raise ConfigError(f'Missing validated experiments: {selected-chosen.keys()}')
    dest=study.root/'results';dest.mkdir(parents=True,exist_ok=True)
    (dest/'analysis.json').unlink(missing_ok=True)
    import tempfile, os
    with tempfile.TemporaryDirectory(prefix='.scenario-',dir=dest) as temp:
        pending=Path(temp);manifests={};provenance=[]
        with closing(sqlite3.connect(pending/'data.sqlite')) as db, (pending/'timeseries.csv').open('w',newline='') as f:
            db.execute('CREATE TABLE data (experiment TEXT,lon REAL,lat REAL,year INTEGER,age INTEGER,variable TEXT,value REAL,unit TEXT,basis TEXT,PRIMARY KEY(experiment,lon,lat,year,variable))')
            writer=csv.writer(f);writer.writerow(['experiment_id','longitude','latitude','calendar_year','years_since_cut','variable','value','unit','area_basis'])
            for exp in study.selected(ids):
                m=json.loads(Path(chosen[exp['id']]['manifest']).read_text());manifests[exp['id']]=m
                expected=child(study,exp)
                if m['experiment']!=expected.experiments[0]:raise ConfigError('Scenario changed since execution; prepare a new run')
                if m['outputs']!=study.outputs or m['study']['biomass']!=study.config['biomass']:
                    raise ConfigError('Output/biomass definitions changed since execution')
                if m['sites']!=[list(map(float,r.split()[:2])) for r in expected.records] or m['first_year']!=study.first_year or m['last_year']!=study.last_year:
                    raise ConfigError('Sites or simulation period changed since execution')
                archive=Path(m['archive_dir']);verify_archive(archive)
                provenance.append({'experiment':exp['id'],'execution':m['execution_id'],'archive':str(archive)})
                for output in m['outputs']:
                    for _,row,_ in read_table(archive/(output['file']+'.gz')):
                        year=int(row[output['year_column']]);value,unit=biomass_value(total(row,output),output,m['study']['biomass'])
                        values=(exp['id'],row['Lon'],row['Lat'],year,year-m['cut_year'],output['variable'],value,unit,output['area_basis'])
                        try:db.execute('INSERT INTO data VALUES (?,?,?,?,?,?,?,?,?)',values)
                        except sqlite3.IntegrityError as exc:raise ConfigError('Scenario analysis requires one annual record per site/variable') from exc
                        writer.writerow(values)
                db.commit()
            areas=area_weights(study)
            region_config={'all':{'weighting':'equal'},**study.config.get('regions',{})}
            regions={name:{tuple(map(float,r.split()[:2])) for r in region_sites(study.records,config)} for name,config in region_config.items()}
            atomic_json(pending/'region_sites.json',{k:sorted(v) for k,v in regions.items()})
            floor=float(study.config.get('analysis',{}).get('percentage_floor',1e-8))
            with (pending/'regional_summary.csv').open('w',newline='') as rf,(pending/'comparison_differences.csv').open('w',newline='') as df,(pending/'site_differences.csv').open('w',newline='') as sf:
                rw=csv.writer(rf);dw=csv.writer(df);sw=csv.writer(sf)
                rw.writerow(['comparison','region','experiment_id','variable','unit','area_basis','time','axis','sites','weight_sum','mean','minimum','maximum','weighting','status'])
                dw.writerow(['comparison','region','experiment_id','variable','unit','time','axis','difference','percent_difference','status'])
                sw.writerow(['comparison','region','experiment_id','longitude','latitude','variable','unit','time','axis','difference','percent_difference'])
                for name,spec in active.items():
                    baseline=spec['baseline'];reference=manifests[baseline];axis=spec.get('axis','calendar_year');column='year' if axis=='calendar_year' else 'age'
                    # Different inputs/settings must be named deliberately as comparison factors.
                    allowed=set(spec.get('vary',['climate','co2','pft_overrides','management','landuse']))
                    if allowed-{'climate','co2','pft_overrides','management','landuse'}:raise ConfigError('Unknown comparison vary factor')
                    for eid in spec['experiments']:
                        m=manifests[eid]
                        # Supplied input metadata must match except declared input treatments.
                        ignored=set()
                        if 'landuse' in allowed:
                            for manifest in (m,reference):
                                lu=manifest['scenario'].get('landuse',{})
                                ignored.update(lu.get('files',{}));ignored.update(lu.get('freeze_inputs',[]));ignored.update(lu.get('zero_inputs',[]))
                        if 'co2' in allowed:ignored.add('file_co2')
                        inputs=lambda manifest: [i for i in manifest.get('input_files',[]) if i['parameter'] not in ignored]
                        if inputs(m)!=inputs(reference):raise ConfigError('Undeclared source input changes between executions')
                        if m['executable_sha256']!=reference['executable_sha256'] or m['source_files']!=reference['source_files']:
                            raise ConfigError('Comparison requires identical executable and original instructions')
                        if 'management' not in allowed and m.get('generated_management')!=reference.get('generated_management'):
                            raise ConfigError('Undeclared management difference')
                        for factor in {'climate','co2','pft_overrides','management','landuse'}-allowed:
                            if m['scenario'].get(factor)!=reference['scenario'].get(factor):raise ConfigError(f'Undeclared treatment difference: {factor}')
                        if axis=='years_since_cut' and m['study'].get('experiment_mode')=='landuse_change':raise ConfigError('Land-use comparisons require calendar_year axis')
                    for region in spec.get('regions',['all']):
                        if not regions[region]:
                            # Only geometrically empty ranges receive synthetic zeros.
                            # Build the timeline from validated data, including converted units.
                            timeline=None
                            for eid in spec['experiments']:
                                current=set(db.execute(f'SELECT DISTINCT {column},variable,unit,basis FROM data WHERE experiment=?'+(' AND age>=0' if axis=='years_since_cut' else ''),(eid,)))
                                if timeline is not None and timeline!=current:raise ConfigError('Comparison time/variable coverage differs')
                                timeline=current
                            for eid in spec['experiments']:
                                for t,var,unit,basis in sorted(timeline):
                                    rw.writerow([name,region,eid,var,unit,basis,t,axis,0,0,0,0,0,region_config[region].get('weighting','equal'),'empty_region'])
                                    dw.writerow([name,region,eid,var,unit,t,axis,0,'','empty_region'])
                            continue
                        matched=None
                        for eid in spec['experiments']:
                            sites={tuple(x) for x in manifests[eid]['sites']}&regions[region]
                            if not sites or (matched is not None and sites!=matched):raise ConfigError(f'{name}/{region}: comparisons need identical nonempty site sets; use separate comparison groups for different site groups')
                            matched=sites
                        weighting=region_config[region].get('weighting','equal')
                        if weighting in ('cell_area','forest_area') and matched-areas.keys():raise ConfigError('cell_area weighting requires cell_areas or grid_resolution_degrees')
                        records={}
                        for eid in spec['experiments']:
                            records[eid]={(lon,lat,t,var):(value,unit,basis) for lon,lat,t,var,value,unit,basis in db.execute(f'SELECT lon,lat,{column},variable,value,unit,basis FROM data WHERE experiment=?',(eid,)) if (lon,lat) in matched and (axis=='calendar_year' or t>=0)}
                        keys=set(records[baseline])
                        if any(set(r)!=keys for r in records.values()):raise ConfigError('Comparison time/variable coverage differs')
                        summaries={}
                        for eid,rows in records.items():
                            grouped=defaultdict(list)
                            for (lon,lat,t,var),(value,unit,basis) in rows.items():
                                weight=areas[lon,lat] if weighting in ('cell_area','forest_area') else 1.
                                if weighting=='forest_area':
                                    output=next(o for o in study.outputs if o['variable']==var)
                                    fraction_var=output.get('area_fraction_variable')
                                    if not fraction_var:raise ConfigError(f'forest_area weighting requires area_fraction_variable for {var}')
                                    try:fraction=rows[lon,lat,t,fraction_var][0]
                                    except KeyError as exc:raise ConfigError('Missing area fraction output') from exc
                                    if not 0<=fraction<=1:raise ConfigError('Forest fraction must be in [0,1]')
                                    weight*=fraction
                                grouped[t,var,unit,basis].append((value,weight))
                                ref,refunit,refbasis=records[baseline][lon,lat,t,var]
                                if (unit,basis)!=(refunit,refbasis):raise ConfigError('Comparison units/area basis differ')
                                sw.writerow([name,region,eid,lon,lat,var,unit,t,axis,value-ref,'' if abs(ref)<=floor else 100*(value-ref)/ref])
                            for (t,var,unit,basis),values in sorted(grouped.items()):
                                den=sum(w for _,w in values)
                                if den<=0:raise ConfigError(f'Zero aggregation area for {name}/{region}/{eid}/{t}/{var}')
                                mean=sum(v*w for v,w in values)/den
                                summaries[eid,t,var]=(mean,unit)
                                rw.writerow([name,region,eid,var,unit,basis,t,axis,len(values),den,mean,min(v for v,_ in values),max(v for v,_ in values),weighting,'ok'])
                        for (eid,t,var),(mean,unit) in summaries.items():
                            ref=summaries[baseline,t,var][0]
                            dw.writerow([name,region,eid,var,unit,t,axis,mean-ref,'' if abs(ref)<=floor else 100*(mean-ref)/ref,'ok'])
        selected_ages=set(study.config.get('analysis',{}).get('summary_ages',[0,20,40,60,80,100,120]))
        with (pending/'timeseries.csv').open() as source,(pending/'selected_ages.csv').open('w',newline='') as target:
            reader=csv.DictReader(source);writer=csv.DictWriter(target,fieldnames=reader.fieldnames);writer.writeheader()
            for row in reader:
                if int(row['years_since_cut']) in selected_ages and manifests[row['experiment_id']]['study'].get('experiment_mode')!='landuse_change':writer.writerow(row)
        atomic_json(pending/'analysis.json',{'scenario_signature':signature(study),'executions':provenance,'comparisons':active,
            'empty_regions':[name for name,sites in regions.items() if not sites],
            'empty_region_policy':'Zero summaries for ranges with no supplied grid points; sites=0, weight_sum=0, status=empty_region. Percentage differences are undefined.',
            'note':'Regional ranges describe spatial variation, not uncertainty. cell_area weights locations; forest_area uses the explicitly configured fraction variable and reports the changing denominator.'})
        for path in pending.iterdir():
            if path.suffix!='.sqlite' and path.name!='analysis.json':os.replace(path,dest/path.name)
        os.replace(pending/'analysis.json',dest/'analysis.json')
    return str(dest)


def palette(study):
    from matplotlib import colormaps
    from matplotlib.colors import to_hex
    cmap=colormaps[study.config.get('analysis',{}).get('plot_colormap','jet')]
    ids=[e['id'] for e in study.experiments]
    colors={eid:to_hex(cmap(float(i/(len(ids)-1) if len(ids)>1 else .5))) for i,eid in enumerate(ids)}
    families=defaultdict(list)
    for e in study.experiments:
        if 'sweep_family' in e['scenario']:families[e['scenario']['sweep_family']].append(e)
    for family,exps in families.items():
        vals=[e['scenario']['sweep_value'] for e in exps];lo=min(vals);hi=max(vals)
        for e,v in zip(exps,vals):colors[e['id']]=to_hex(cmap(float((v-lo)/(hi-lo) if hi>lo else .5)))
    # Numeric management-only comparisons retain the original numeric color logic.
    from .plotstyle import experiment_palette
    candidates=[]
    for spec in comparisons(study).values():
        exps=[child(study,e).experiments[0] for e in study.experiments if e['id'] in spec['experiments']]
        scientific=[{k:v for k,v in e.items() if k not in ('scenario','forcing')} for e in exps]
        numeric,detail=experiment_palette(scientific,study.config.get('analysis',{}).get('plot_colormap','jet'))
        if detail['mode']=='numeric' and all(e['scenario'].get('climate')==exps[0]['scenario'].get('climate') and e['scenario'].get('co2')==exps[0]['scenario'].get('co2') and e['scenario'].get('pft_overrides')==exps[0]['scenario'].get('pft_overrides') and e['scenario'].get('landuse')==exps[0]['scenario'].get('landuse') for e in exps):candidates.append(numeric)
    # A shared baseline cannot carry two contradictory numeric color scales.
    proposed=defaultdict(set)
    for candidate in candidates:
        for eid,color in candidate.items():proposed[eid].add(color)
    for candidate in candidates:
        if all(len(proposed[eid])==1 for eid in candidate):colors.update(candidate)
    return colors


def plot(study):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    root=study.root/'results';meta=json.loads((root/'analysis.json').read_text())
    if meta.get('scenario_signature')!=signature(study):raise ConfigError('Configuration changed; rerun analyze')
    dest=study.root/'figures';dest.mkdir(exist_ok=True);colors=palette(study);files=[]
    labels={e['id']:e['scenario'].get('label',e['id']) for e in study.experiments}
    def save(fig,name):
        from matplotlib.ticker import MaxNLocator
        for ax in fig.axes:
            ax.spines[['top','right']].set_visible(False)
            if 'year' in ax.get_xlabel().lower():ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        fig.tight_layout()
        for suffix in ('png','pdf'):
            path=dest/(name+'.'+suffix);fig.savefig(path,dpi=180,bbox_inches='tight');files.append(str(path))
        plt.close(fig)
    def draw(rows,key,y,titleprefix):
        groups=defaultdict(list)
        for r in rows:
            if r[y]!='':groups[tuple(r[k] for k in key)].append(r)
        for keys,group in groups.items():
            fig,ax=plt.subplots(figsize=(9,5))
            for eid in sorted({r['experiment_id'] for r in group}):
                series=sorted((r for r in group if r['experiment_id']==eid),key=lambda r:float(r['time']))
                ax.plot([float(r['time']) for r in series],[float(r[y]) for r in series],color=colors[eid],label=labels[eid])
            ax.set(xlabel=group[0]['axis'].replace('_',' '),ylabel=('%' if y=='percent_difference' else group[0]['unit']),title=titleprefix+' / '.join(keys))
            ax.grid(alpha=.2);ax.legend(fontsize=8);save(fig,titleprefix.replace(' ','_')+'_'.join(keys))
    with (root/'regional_summary.csv').open() as f:regional=list(csv.DictReader(f))
    draw(regional,['comparison','region','variable'],'mean','Regional ')
    with (root/'comparison_differences.csv').open() as f:diff=list(csv.DictReader(f))
    draw(diff,['comparison','region','variable'],'difference','Difference ')
    draw(diff,['comparison','region','variable'],'percent_difference','Percent ')
    options=study.config.get('analysis',{})
    # Every plotted observation is now an aggregated region, never a grid cell.
    from .plotstyle import component_palette
    regioncolors=component_palette(sorted({r['region'] for r in regional}),options.get('plot_colormap','jet'))
    groups=defaultdict(list)
    for r in regional:
        groups[r['comparison'],r['experiment_id'],r['variable'],r['axis']].append(r)
    for (comparison,eid,var,axis),group in groups.items():
        fig,ax=plt.subplots(figsize=(9,5))
        for region in sorted({r['region'] for r in group}):
            series=sorted((r for r in group if r['region']==region),key=lambda r:float(r['time']))
            ax.plot([float(r['time']) for r in series],[float(r['mean']) for r in series],label=region,color=regioncolors[region])
        ax.set(xlabel=axis.replace('_',' '),ylabel=group[0]['unit'],title=f'{labels[eid]}: {var} across regions')
        ax.legend(fontsize=8);ax.grid(alpha=.2);save(fig,f'cross_region_{comparison}_{eid}_{var}')
    # Parameter responses use the same regional means as the time-series plots.
    families=defaultdict(dict)
    for e in study.experiments:
        if 'sweep_family' in e['scenario']:families[e['scenario']['sweep_family']][e['id']]=e['scenario']['sweep_value']
    cutyears={e['id']:child(study,e).cut_year for e in study.experiments}
    wanted=set(options.get('summary_ages',[0,20,40,60,80,100,120]))
    for family,values in families.items():
        grouped=defaultdict(dict)
        for r in regional:
            eid=r['experiment_id']
            if eid not in values:continue
            age=int(r['time'])-(cutyears[eid] if r['axis']=='calendar_year' else 0)
            if age in wanted:grouped[r['region'],r['variable']][eid,age]=(r,age)
        for (region,var),items in grouped.items():
            group=list(items.values());fig,ax=plt.subplots(figsize=(9,5))
            ages=sorted({age for r,age in group})
            ac=component_palette([str(a) for a in ages],options.get('plot_colormap','jet'))
            for age in ages:
                series=sorted([r for r,a in group if a==age],key=lambda r:values[r['experiment_id']])
                ax.plot([values[r['experiment_id']] for r in series],[float(r['mean']) for r in series],marker='o',label=f'Age {age}',color=ac[str(age)])
            ax.set(xlabel='Sweep value (multiplier or absolute, as configured)',ylabel=group[0][0]['unit'],title=f'{family}: {var} in {region}')
            ax.legend(fontsize=8);ax.grid(alpha=.2);save(fig,f'response_{family}_{region}_{var}')
    fig,ax=plt.subplots(figsize=(10,5))
    regions=json.loads((root/'region_sites.json').read_text())
    for name,points in regions.items():
        if name=='all' and len(regions)>1:continue
        ax.scatter([p[0] for p in points],[p[1] for p in points],s=18,label=name,alpha=.7,color=regioncolors.get(name))
    ax.set(xlabel='Longitude',ylabel='Latitude',title='Selected grid-cell centres by region');ax.legend();ax.grid(alpha=.2);save(fig,'region_sites')
    # Remove only obsolete plots recorded as owned by the previous plotting run.
    scope=dest/'plot_scope.json'
    if scope.exists():
        previous=json.loads(scope.read_text())
        current={Path(f).resolve() for f in files}
        for old in previous.get('files',[]):
            path=Path(old).resolve()
            if path.parent==dest.resolve() and path.suffix in ('.png','.pdf') and path not in current:
                path.unlink(missing_ok=True)
    atomic_json(scope,{'files':files,'experiment_colors':colors,'region_colors':regioncolors,
        'individual_sites':[],'aggregation':'Regional means using configured area weights; selected cells only, excluding rectangle gaps.',
        'scenario_signature':signature(study)})
    return files
