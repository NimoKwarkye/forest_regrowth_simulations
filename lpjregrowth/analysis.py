"""Analysis of validated archives with explicit carbon/dry-mass semantics."""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from .collect import read_table, verify_archive
from .config import atomic_json
from .instructions import ConfigError
from .workflow import Store
from .forcing import labels as forcing_labels, check_snapshot

FIELDS = ['experiment_id','execution_id','longitude','latitude','calendar_year','years_since_cut',
          'component','variable','value','unit','area_basis']


def biomass_value(value, spec, biomass):
    if spec.get('role') != 'biomass' or biomass['kind'] == 'carbon':
        return value, spec['unit']
    if spec['unit'] != 'kg C m-2':
        raise ConfigError('Dry-mass conversion currently requires biomass source unit kg C m-2')
    fraction = float(biomass['carbon_fraction'])
    if not 0 < fraction <= 1:
        raise ConfigError('Invalid carbon fraction')
    if biomass.get('output_unit') == 'kg dry matter m-2':
        return value / fraction, 'kg dry matter m-2'
    return value * 10 / fraction, 'Mg dry matter ha-1'


def analyze(study, ids=None):
    if study.config.get("scenarios") is not None:
        from .scenario_analysis import analyze as scenario_analyze
        return scenario_analyze(study,ids)
    import sqlite3
    import uuid
    import os
    from contextlib import closing
    selected = {e['id'] for e in study.selected(ids)}
    if study.config.get('forcing_experiment') is not None and selected != {e['id'] for e in study.experiments}:
        raise ConfigError('Forcing comparison analysis requires all configured treatments')
    chosen = {}
    for row in Store(study.root).rows():
        if row['status'] == 'complete' and row['experiment'] in selected:
            chosen[row['experiment']] = row
    if selected - chosen.keys():
        raise ConfigError(f'Experiments have no validated complete execution: {selected-chosen.keys()}')
    baseline = study.config.get('baseline','baseline')
    if baseline not in chosen:
        raise ConfigError('Include the baseline experiment in comparative analysis')
    dest = study.root / 'results'
    dest.mkdir(parents=True, exist_ok=True)
    pending = dest / ('.pending-' + uuid.uuid4().hex[:10])
    pending.mkdir()
    # Invalidating the marker prevents plotting a partially replaced result set.
    (dest/'analysis.json').unlink(missing_ok=True)
    provenance = []
    compatibility = None
    threshold = float(study.config.get('analysis',{}).get('percentage_floor',1e-8))
    with closing(sqlite3.connect(pending/'totals.sqlite')) as db, (pending/'timeseries.csv').open('w',encoding='utf-8',newline='') as handle:
        db.execute('CREATE TABLE totals (experiment TEXT, lon REAL, lat REAL, year INTEGER, variable TEXT, value REAL, unit TEXT, basis TEXT, PRIMARY KEY(experiment,lon,lat,year,variable))')
        db.execute('CREATE TABLE precut (experiment TEXT, lon REAL, lat REAL, variable TEXT, value REAL, unit TEXT, PRIMARY KEY(experiment,lon,lat,variable))')
        writer = csv.DictWriter(handle,fieldnames=FIELDS)
        writer.writeheader()
        for exp_id, execution in sorted(chosen.items()):
            m=json.loads(Path(execution['manifest']).read_text())
            check_snapshot(study, m)
            archive=Path(m['archive_dir'])
            verify_archive(archive)
            signature=json.dumps({'sites':m['sites'],'first':m['first_year'],'last':m['last_year'],
                 'cut':m['cut_year'],'exe':m['executable_sha256'],'outputs':m['outputs'],
                 'biomass':m['study']['biomass'],'forcing_design':m['study'].get('forcing_experiment'), 'management':m.get('generated_management') if m['study'].get('forcing_experiment') else None, 'forcing_metadata':m.get('input_files',[]),'sources':[(x['path'],x['sha256']) for x in m['source_files']]},sort_keys=True)
            if compatibility is not None and signature != compatibility:
                raise ConfigError('Selected executions differ in sites, period, executable, outputs, biomass definition, or source inputs')
            compatibility=signature
            provenance.append({'experiment':exp_id,'execution':m['execution_id'],'archive':str(archive), 'forcing':m['experiment'].get('forcing')})
            for spec in m['outputs']:
                for _,row,_ in read_table(archive/(spec['file']+'.gz')):
                    year=int(row[spec['year_column']])
                    if year < m['cut_year']:
                        if year == m['cut_year']-1:
                            before,unit=biomass_value(sum(row[col] for col in spec['values']),spec,m['study']['biomass'])
                            db.execute('INSERT INTO precut VALUES (?,?,?,?,?,?)',(exp_id,row['Lon'],row['Lat'],spec['variable'],before,unit))
                        continue
                    base=dict(experiment_id=exp_id,execution_id=m['execution_id'],longitude=row['Lon'],latitude=row['Lat'],
                         calendar_year=year,years_since_cut=year-m['cut_year'],variable=spec['variable'],area_basis=spec['area_basis'])
                    for col in spec['values']:
                        value,unit=biomass_value(row[col],spec,m['study']['biomass'])
                        writer.writerow({**base,'component':col,'value':value,'unit':unit})
                    total,unit=biomass_value(sum(row[col] for col in spec['values']),spec,m['study']['biomass'])
                    writer.writerow({**base,'component':'__sum__','value':total,'unit':unit})
                    try:
                        db.execute('INSERT INTO totals VALUES (?,?,?,?,?,?,?,?)',(exp_id,row['Lon'],row['Lat'],year,spec['variable'],total,unit,spec['area_basis']))
                    except sqlite3.IntegrityError as exc:
                        raise ConfigError('Comparison plots require annual outputs with one record per site/year') from exc
                db.commit()
        pre_cut_differences=0
        pre_cut_rows=0
        pre_cut_tolerance=float(study.config.get('analysis',{}).get('precut_tolerance',1e-6))
        with (pending/'pre_cut_comparison.csv').open('w',encoding='utf-8',newline='') as output:
            writer=csv.writer(output)
            writer.writerow(['experiment_id','longitude','latitude','variable','precut_value','baseline_precut_value','difference','unit'])
            query='SELECT a.experiment,a.lon,a.lat,a.variable,a.value,b.value,a.unit FROM precut a JOIN precut b ON a.lon=b.lon AND a.lat=b.lat AND a.variable=b.variable WHERE b.experiment=?'
            for exp,lon,lat,var,value,ref,unit in db.execute(query,(baseline,)):
                writer.writerow([exp,lon,lat,var,value,ref,value-ref,unit])
                pre_cut_rows+=1
                pre_cut_differences+=int(abs(value-ref)>pre_cut_tolerance)
        if study.config.get('analysis',{}).get('require_equal_precut',False) and (pre_cut_differences or not pre_cut_rows):
            raise ConfigError(f'Pre-cut states differ or are unavailable; see {pending}/pre_cut_comparison.csv')
        with (pending/'differences.csv').open('w',encoding='utf-8',newline='') as output:
            writer=csv.writer(output)
            writer.writerow(['experiment_id','longitude','latitude','calendar_year','variable','difference','percent_difference','unit','area_basis'])
            query='SELECT a.experiment,a.lon,a.lat,a.year,a.variable,a.value,b.value,a.unit,a.basis FROM totals a JOIN totals b ON a.lon=b.lon AND a.lat=b.lat AND a.year=b.year AND a.variable=b.variable WHERE b.experiment=? ORDER BY a.experiment,a.lon,a.lat,a.variable,a.year'
            for exp,lon,lat,year,var,value,ref,unit,basis in db.execute(query,(baseline,)):
                writer.writerow([exp,lon,lat,year,var,value-ref,'' if abs(ref)<=threshold else 100*(value-ref)/ref,unit,basis])
        with (pending/'site_summary.csv').open('w',encoding='utf-8',newline='') as output:
            writer=csv.writer(output)
            writer.writerow(['experiment_id','calendar_year','variable','unit','area_basis','sites','mean','minimum','maximum','weighting'])
            query='SELECT experiment,year,variable,unit,basis,count(*),avg(value),min(value),max(value) FROM totals GROUP BY experiment,year,variable,unit,basis ORDER BY experiment,variable,year'
            for row in db.execute(query):
                writer.writerow([*row,'equal weight per simulated site; not area weighted'])
    (pending/'totals.sqlite').unlink()
    atomic_json(pending/'analysis.json',{'executions':provenance,'cut_year':study.cut_year,
       'forcing_experiment':study.config.get('forcing_experiment'),
       'time_convention':'Cutting year is age zero; output is year-end state.',
       'site_weighting':'Equal weight per simulated site. Range is spatial variation, not confidence interval.',
       'biomass':study.config['biomass'],'percentage_floor':threshold,
       'precut_comparison_rows':pre_cut_rows,'precut_differences_above_tolerance':pre_cut_differences,
       'precut_note':'Independent spin-ups can differ because management/PFT eligibility can affect initial conditions; inspect pre_cut_comparison.csv.'})
    for name in ('timeseries.csv','differences.csv','site_summary.csv','pre_cut_comparison.csv','analysis.json'):
        os.replace(pending/name,dest/name)
    pending.rmdir()
    return str(dest)


def plot(study):
    if study.config.get("scenarios") is not None:
        from .scenario_analysis import plot as scenario_plot
        return scenario_plot(study)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    results = study.root / 'results'
    if not (results / 'analysis.json').is_file():
        raise ConfigError('Run analyze first')
    metadata=json.loads((results/'analysis.json').read_text())
    if metadata.get('forcing_experiment') != study.config.get('forcing_experiment'):
        raise ConfigError('Forcing configuration changed; rerun analyze before plotting')
    labels=forcing_labels(study.experiments) if metadata.get('forcing_experiment') else {}
    options=study.config.get('analysis',{})
    from .plotstyle import experiment_palette, component_palette
    compared_ids={entry['experiment'] for entry in metadata['executions']}
    compared_experiments=[exp for exp in study.experiments if exp['id'] in compared_ids]
    colors, color_details = experiment_palette(compared_experiments, options.get('plot_colormap','jet'))
    component_colors = component_palette([c for spec in study.outputs if spec.get('role')=='biomass' for c in spec['values']], options.get('plot_colormap','jet'))
    if options.get('plot_sites'):
        plot_sites={tuple(map(float,site)) for site in options['plot_sites']}
    else:
        limit=int(options.get('plot_max_sites',10))
        if limit < 1: raise ConfigError('plot_max_sites must be positive')
        plot_sites={tuple(map(float,line.split()[:2])) for line in study.records[:limit]}
    with (results/'timeseries.csv').open(encoding='utf-8') as source:
        rows=[r for r in csv.DictReader(source) if (float(r['longitude']),float(r['latitude'])) in plot_sites]
    dest = study.root / 'figures'
    dest.mkdir(parents=True,exist_ok=True)
    output = []
    def save(fig, name):
        for ax in fig.axes:
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
        fig.tight_layout()
        for suffix in ('png','pdf'):
            path = dest / f'{name}.{suffix}'
            fig.savefig(path,dpi=180,bbox_inches='tight')
            output.append(str(path))
        plt.close(fig)
    groups = defaultdict(list)
    for row in rows:
        if row['component'] == '__sum__':
            groups[(row['longitude'],row['latitude'],row['variable'],row['unit'])].append(row)
    for (lon,lat,var,unit), group in sorted(groups.items()):
        fig,ax=plt.subplots(figsize=(8,4.8))
        for exp in sorted({r['experiment_id'] for r in group}):
            series=sorted((r for r in group if r['experiment_id']==exp),key=lambda r:float(r['years_since_cut']))
            ax.plot([float(r['years_since_cut']) for r in series],[float(r['value']) for r in series],label=labels.get(exp, exp),color=colors[exp])
        ax.set(xlabel='Years since clear-cut (year-end records)',ylabel=f'{var.replace("_"," ")} [{unit}]',title=f'{lon}, {lat}')
        ax.grid(alpha=.2); ax.legend(fontsize=8)
        save(fig,f'{var}_{lon}_{lat}')
    # Explicit forcing comparison: absolute biomass and treatment-minus-baseline.
    if metadata.get('forcing_experiment'):
        biomass_names={spec['variable'] for spec in study.outputs if spec.get('role')=='biomass'}
        for (lon,lat,var,unit), group in sorted(groups.items()):
            if var not in biomass_names: continue
            series={exp:{int(r['calendar_year']):float(r['value']) for r in group if r['experiment_id']==exp} for exp in labels}
            if not all(series.values()):
                raise ConfigError('Forcing comparison plots require all configured treatments')
            fig,axes=plt.subplots(2,1,figsize=(9,7),sharex=True)
            for exp, values in series.items():
                years=sorted(values)
                x=[y-study.cut_year for y in years]
                axes[0].plot(x,[values[y] for y in years],label=labels[exp],color=colors[exp])
                if exp != 'baseline':
                    axes[1].plot(x,[values[y]-series['baseline'][y] for y in years],label=labels[exp],color=colors[exp])
            axes[0].set(ylabel=f'{var.replace("_"," ")} [{unit}]',title=f'Reference {study.experiments[0]["forcing"]["reference_year"]}; treatment starts {study.experiments[0]["forcing"]["start_year"]}; site {lon}, {lat}')
            axes[1].set(xlabel='Years since clear-cut (year-end records)',ylabel=f'Treatment minus baseline [{unit}]')
            axes[1].axhline(0,color='black',linewidth=.7)
            for ax in axes:
                ax.grid(alpha=.2); ax.legend(fontsize=8)
            save(fig,f'forcing_comparison_{var}_{lon}_{lat}')
    # Biomass PFT contributions remain distinct from aggregate curves.
    biomass_vars={s['variable'] for s in study.outputs if s.get('role')=='biomass'}
    compositions=defaultdict(list)
    for row in rows:
        if row['variable'] in biomass_vars and row['component']!='__sum__':
            compositions[(row['experiment_id'],row['longitude'],row['latitude'],row['variable'],row['unit'])].append(row)
    for (exp,lon,lat,var,unit),group in compositions.items():
        fig,ax=plt.subplots(figsize=(8,4.8))
        for component in sorted({r['component'] for r in group}):
            series=sorted((r for r in group if r['component']==component),key=lambda r:float(r['years_since_cut']))
            if not any(float(r['value']) for r in series):
                continue
            ax.plot([float(r['years_since_cut']) for r in series],[float(r['value']) for r in series],label=component,color=component_colors[component])
        ax.set(xlabel='Years since clear-cut',ylabel=f'{var.replace("_"," ")} [{unit}]',title=f'{exp}: PFT contributions at {lon}, {lat}')
        ax.legend(fontsize=8); ax.grid(alpha=.2)
        save(fig,f'composition_{exp}_{lon}_{lat}_{var}')
    with (results/'differences.csv').open(encoding='utf-8') as source:
        differences=[r for r in csv.DictReader(source) if (float(r['longitude']),float(r['latitude'])) in plot_sites]
    for metric in ('difference','percent_difference'):
        diff_groups=defaultdict(list)
        for row in differences:
            if row['variable'] in biomass_vars and row[metric] != '' and row['experiment_id'] != study.config.get('baseline','baseline'):
                diff_groups[(row['longitude'],row['latitude'],row['variable'],row['unit'])].append(row)
        for (lon,lat,var,unit),group in diff_groups.items():
            fig,ax=plt.subplots(figsize=(8,4.8))
            for exp in sorted({r['experiment_id'] for r in group}):
                series=sorted((r for r in group if r['experiment_id']==exp),key=lambda r:int(r['calendar_year']))
                ax.plot([int(r['calendar_year'])-study.cut_year for r in series],[float(r[metric]) for r in series],label=labels.get(exp, exp),color=colors[exp])
            ax.axhline(0,color='black',linewidth=.7)
            ax.set(xlabel='Years since clear-cut',ylabel=f'{metric.replace("_"," ")} [{"%" if metric=="percent_difference" else unit}]',title=f'{var}: {lon}, {lat}')
            ax.legend(fontsize=8); ax.grid(alpha=.2)
            save(fig,f'{metric}_{var}_{lon}_{lat}')
    with (results/'site_summary.csv').open(encoding='utf-8') as source:
        summaries=list(csv.DictReader(source))
    for var in biomass_vars:
        group=[r for r in summaries if r['variable']==var]
        if not group: continue
        fig,ax=plt.subplots(figsize=(8,4.8))
        for exp in sorted({r['experiment_id'] for r in group}):
            series=sorted((r for r in group if r['experiment_id']==exp),key=lambda r:int(r['calendar_year']))
            x=[int(r['calendar_year'])-study.cut_year for r in series]
            ax.plot(x,[float(r['mean']) for r in series],label=labels.get(exp, exp),color=colors[exp])
            if int(series[0]['sites'])>1:
                ax.fill_between(x,[float(r['minimum']) for r in series],[float(r['maximum']) for r in series],alpha=.12,color=colors[exp])
        ax.set(xlabel='Years since clear-cut',ylabel=f'{var.replace("_"," ")} [{group[0]["unit"]}]',title='Equal-site means; shading shows site range, not uncertainty')
        ax.legend(fontsize=8); ax.grid(alpha=.2)
        save(fig,f'site_summary_{var}')
    atomic_json(dest/'plot_scope.json',{'individual_sites':sorted(plot_sites),'multi_site_summary':'all validated sites','files':output,'experiment_palette':color_details,'component_colors':component_colors})
    return output
