"""Select forest-rich sites and prepare annual LPJ-GUESS land fractions.

Standard library only. Run: python prepare_sites.py --study study.json
"""
import argparse
import copy
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from lpjregrowth.config import read_grid, resolve_path, atomic_json, write_text
from lpjregrowth.instructions import ConfigError
from lpjregrowth.scenarios import identifier, region_sites


def select_rectangle(points,forest,shape,resolution):
    rows,columns=shape;dx,dy=resolution
    lookup={(round(x,8),round(y,8)):(x,y) for x,y in points}
    best=None
    for x,y in sorted(points):
        keys=[(round(x+j*dx,8),round(y+i*dy,8)) for i in range(rows) for j in range(columns)]
        if any(key not in lookup for key in keys):continue
        block=[lookup[key] for key in keys]
        values=[forest[p] for p in block]
        score=(sum(values)/len(values),min(values),-x,-y)
        if best is None or score>best[0]:best=(score,block)
    if best is None:return [],{}
    block=best[1];xs=[p[0] for p in block];ys=[p[1] for p in block]
    return block,{'longitude':[min(xs)-dx/2,max(xs)+dx/2],'latitude':[min(ys)-dy/2,max(ys)+dy/2],
                  'rows':rows,'columns':columns,'minimum_forest_fraction':min(forest[p] for p in block),
                  'mean_forest_fraction':sum(forest[p] for p in block)/len(block)}


def select_cluster(points,forest,minimum,resolution):
    """Smallest compact grid-aligned rectangle with at least minimum eligible points.

    Gaps are allowed. Prefix sums keep the search independent of rectangle area.
    """
    if len(points)<minimum:return [],{}
    dx,dy=resolution;x0=min(p[0] for p in points);y0=min(p[1] for p in points)
    indexed={}
    for x,y in points:
        col=round((x-x0)/dx);row=round((y-y0)/dy)
        if not math.isclose(x,x0+col*dx,abs_tol=1e-7) or not math.isclose(y,y0+row*dy,abs_tol=1e-7):raise ConfigError('Grid points do not align with grid_resolution_degrees')
        indexed[row,col]=(x,y)
    height=max(r for r,c in indexed)+1;width=max(c for r,c in indexed)+1
    counts=[[0]*(width+1) for _ in range(height+1)];sums=[[0.]*(width+1) for _ in range(height+1)]
    for r in range(height):
        for c in range(width):
            point=indexed.get((r,c));n=1 if point else 0;value=forest[point] if point else 0.
            counts[r+1][c+1]=n+counts[r][c+1]+counts[r+1][c]-counts[r][c]
            sums[r+1][c+1]=value+sums[r][c+1]+sums[r+1][c]-sums[r][c]
    def rect(prefix,r,c,h,w):return prefix[r+h][c+w]-prefix[r][c+w]-prefix[r+h][c]+prefix[r][c]
    best=None
    for h in range(1,height+1):
        for w in range(1,width+1):
            area=h*w
            if area<minimum or (best is not None and area>best[0][0]):continue
            for r in range(height-h+1):
                for c in range(width-w+1):
                    n=rect(counts,r,c,h,w)
                    if n<minimum:continue
                    score=(area,max(h,w)/min(h,w),-round(rect(sums,r,c,h,w)/n,12),-n,c,r)
                    if best is None or score<best[0]:best=(score,r,c,h,w)
    if best is None:return [],{}
    _,r,c,h,w=best
    block=sorted(point for (i,j),point in indexed.items() if r<=i<r+h and c<=j<c+w)
    values=[forest[p] for p in block]
    return block,{'longitude':[x0+(c-.5)*dx,x0+(c+w-.5)*dx],'latitude':[y0+(r-.5)*dy,y0+(r+h-.5)*dy],
                  'rows':h,'columns':w,'rectangle_slots':h*w,'selected_points':len(block),'unselected_slots':h*w-len(block),
                  'minimum_forest_fraction':min(values),'mean_forest_fraction':sum(values)/len(values)}


def read_rows(path):
    with Path(path).open(encoding='utf-8-sig') as f:
        header=next(f).split()
        if header[:3]!=['Lon','Lat','Year'] or 'FOREST' not in header:
            raise ConfigError('Expected Lon Lat Year and FOREST in the land-use header')
        if len(set(header))!=len(header):raise ConfigError('Duplicate land-use columns')
        yield header,None
        for number,line in enumerate(f,2):
            fields=line.split()
            if not fields:continue
            if len(fields)!=len(header):raise ConfigError(f'Invalid land-use column count at line {number}')
            yield header,fields


def fractions(fields,header):
    values=list(map(float,fields[3:]))
    if any(not math.isfinite(v) or v < -1e-8 or v > 1+1e-8 for v in values) or not math.isclose(sum(values),1,abs_tol=1e-6):
        raise ConfigError(f'Invalid land fractions at {fields[:3]}: expected fractions in [0,1] summing to one')
    return values


def prepare(study_path,source_gridlist=None,source_landuse=None,output_dir=None):
    study_path=Path(study_path).resolve();config=json.loads(study_path.read_text(encoding='utf-8-sig'))
    spec=config['site_preparation'];base=study_path.parent
    grid=resolve_path(source_gridlist or spec['source_gridlist'],base)
    land=resolve_path(source_landuse or spec['source_landuse'],base)
    out=resolve_path(output_dir or spec.get('output_directory','prepared-sites'),base)
    if out==base:raise ConfigError('Use a separate output_directory to preserve the source study')
    if {out/name for name in ('gridlist.txt','landuse_dynamic.txt','landuse_forest1.txt','study.json')} & {grid,land,study_path}:raise ConfigError('Generated outputs must not overwrite source inputs')
    first=int(config['first_year']);last=int(config['last_year']);reference=int(spec.get('reference_year',config.get('cut_year',first)-1))
    if first>last:raise ConfigError('first_year exceeds last_year')
    threshold=float(spec.get('minimum_forest_fraction',.3))
    if not 0<=threshold<=1:raise ConfigError('Invalid forest threshold')
    policy=spec.get('outside_source_years','error')
    if policy not in ('error','hold_boundary'):raise ConfigError('outside_source_years must be error or hold_boundary')
    dx,dy=map(float,spec.get('grid_resolution_degrees',[.5,.5]))
    if not (0<dx<=360 and 0<dy<=180):raise ConfigError('Invalid grid resolution')
    records=read_grid(grid)
    zones=spec['zones'];zone_points={}
    for name,z in zones.items():
        identifier(name)
        zone_points[name]={tuple(map(float,r.split()[:2])) for r in region_sites(records,{k:z[k] for k in ('longitude','latitude','sites') if k in z})}
    candidates=set().union(*zone_points.values());forest={};source_years=set()
    print('Scanning land-use reference year...',flush=True)
    for header,fields in read_rows(land):
        if fields is None:continue
        yf=float(fields[2]);year=int(yf)
        if yf!=year:raise ConfigError('Non-integer land-use year')
        source_years.add(year)
        if year!=reference:continue
        point=tuple(map(float,fields[:2]))
        if point not in candidates:continue
        values=fractions(fields,header)
        if point in forest:raise ConfigError(f'Duplicate reference-year record: {point}')
        forest[point]=values[header.index('FOREST')-3]
    if not source_years or reference not in source_years:raise ConfigError('Selection reference year absent from land-use input')
    shape=spec.get('rectangle_shape',[3,3])
    if len(shape)!=2 or any(type(v) is not int or v<1 for v in shape):raise ConfigError('rectangle_shape must be [rows, columns] of positive integers')
    mode=spec.get('selection_mode','complete_rectangle')
    if mode not in ('complete_rectangle','rectangle_minimum_points'):raise ConfigError('Unknown selection_mode')
    minimum=spec.get('minimum_points_per_zone',50)
    if type(minimum) is not int or minimum<1:raise ConfigError('minimum_points_per_zone must be positive')
    selected={};used=set();selection_rows=[];counts={};rectangles={}
    for name,points in zone_points.items():
        eligible={p for p in points if forest.get(p,-1)>=threshold}
        zone_shape=zones[name].get('rectangle_shape',shape)
        if len(zone_shape)!=2 or any(type(v) is not int or v<1 for v in zone_shape):raise ConfigError(f'Invalid rectangle_shape for {name}')
        if mode=='rectangle_minimum_points':
            chosen,bounds=select_cluster(eligible-used,forest,minimum,[dx,dy])
            if not chosen:raise ConfigError(f'{name} has fewer than {minimum} eligible points; expand its search bounds or lower the forest threshold')
        else:
            chosen,bounds=select_rectangle(eligible-used,forest,zone_shape,[dx,dy])
            if not chosen:raise ConfigError(f'No complete {zone_shape[0]} x {zone_shape[1]} forest-rich rectangle in {name}; reduce rectangle_shape or threshold, or expand its search bounds')
        selected[name]=chosen;used.update(chosen);rectangles[name]=bounds
        counts[name]={'in_gridlist':len(points),'with_reference_landuse':len(points&forest.keys()),'above_threshold':len(eligible),'selected':len(chosen)}
        for x,y in chosen:selection_rows.append((name,x,y,forest[x,y],reference,zones[name].get('description',name)))
    if not used:raise ConfigError('No sites meet the configured forest threshold and zone bounds')
    if spec.get('target_total_points') is not None and len(used)!=spec['target_total_points']:raise ConfigError(f'Selected {len(used)} points, expected target_total_points={spec["target_total_points"]}')
    print(f'Selected {len(used)} points; extracting their annual land use...',flush=True)
    history={p:{} for p in used}
    for header,fields in read_rows(land):
        if fields is None:continue
        point=tuple(map(float,fields[:2]))
        if point not in used:continue
        year=int(float(fields[2]))
        if year in history[point]:raise ConfigError(f'Duplicate land-use record: {point}, {year}')
        history[point][year]=fractions(fields,header)
    start=min(first,min(source_years)) if spec.get('include_source_history',True) else first
    dynamic=[' '.join(header)];pure=[' '.join(header)];filled=[]
    pure_values=[1. if name=='FOREST' else 0. for name in header[3:]]
    for point in sorted(used):
        available=history[point]
        if not available:raise ConfigError(f'Missing selected site: {point}')
        low,high=min(available),max(available)
        for year in range(start,last+1):
            source_year=year
            if year not in available:
                if low<year<high:raise ConfigError(f'Internal land-use gap: {point}, {year}')
                if policy=='error':raise ConfigError(f'Land use unavailable for {point}, {year}; choose an explicit boundary-hold policy or shorten the run')
                source_year=low if year<low else high
                filled.append((point[0],point[1],year,source_year))
            prefix=f'{point[0]:g} {point[1]:g} {year}'
            dynamic.append(prefix+' '+' '.join(f'{v:.12g}' for v in available[source_year]))
            pure.append(prefix+' '+' '.join(f'{v:g}' for v in pure_values))
    out.mkdir(parents=True,exist_ok=True)
    write_text(out/'gridlist.txt',''.join(f'{x:g} {y:g}\n' for x,y in sorted(used)))
    write_text(out/'landuse_dynamic.txt','\n'.join(dynamic)+'\n')
    write_text(out/'landuse_forest1.txt','\n'.join(pure)+'\n')
    def table(name,header,rows):
        with (out/name).open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(header);w.writerows(rows)
    table('selected_sites.csv',['zone','longitude','latitude','forest_fraction','reference_year','climate_stratum'],selection_rows)
    table('cell_areas.csv',['longitude','latitude','area_m2'],[(x,y,6371008.8**2*math.radians(dx)*(math.sin(math.radians(min(90,y+dy/2)))-math.sin(math.radians(max(-90,y-dy/2))))) for x,y in sorted(used)])
    table('extended_years.csv',['longitude','latitude','simulation_year','source_year'],filled)
    for name,points in selected.items():write_text(out/'zones'/f'{name}.txt',''.join(f'{x:g} {y:g}\n' for x,y in points))
    ready=copy.deepcopy(config)
    # Rebase existing config references when writing the companion study elsewhere.
    for key in ('cluster','experiments','workspace','model_source','ins_directory'):
        if ready.get(key) and not (str(ready[key]).startswith('/') or Path(ready[key]).is_absolute()):ready[key]=Path(os.path.relpath(resolve_path(ready[key],base),out)).as_posix()
    if ready.get('main_ins') and not ready.get('ins_directory') and not (str(ready['main_ins']).startswith('/') or Path(ready['main_ins']).is_absolute()):ready['main_ins']=Path(os.path.relpath(resolve_path(ready['main_ins'],base),out)).as_posix()
    ready['gridlist']='gridlist.txt'
    ready['prepared_landuse']={'forest_only':'landuse_forest1.txt','dynamic':'landuse_dynamic.txt'}
    ready.setdefault('analysis',{})['cell_areas']='cell_areas.csv'
    ready['regions']={name:{'longitude':rectangles[name]['longitude'],'latitude':rectangles[name]['latitude'],'sites':[list(p) for p in points],'weighting':zones[name].get('weighting','cell_area')} for name,points in selected.items()}
    atomic_json(out/'rectangles.json',rectangles)
    # Optional zone-specific management creates independent, ecologically appropriate jobs.
    if spec.get('zone_management',False):
        originals=ready.get('scenarios',[]);expanded=[];comparisons={}
        for name,points in selected.items():
            if not points:continue
            profile=zones[name].get('management',{})
            for scenario in originals:
                item=copy.deepcopy(scenario);item['id']=identifier(name+'_'+scenario['id']);item['sites']=name
                item['management']={**profile,**item.get('management',{})}
                if item.get('sweep') and 'selection' in profile:item['sweep']['pfts']=profile['selection']
                expanded.append(item)
            for key,comparison in ready.get('comparisons',{}).items():
                item=copy.deepcopy(comparison)
                item['experiments']=[name+'_'+eid for eid in item['experiments']];item['baseline']=name+'_'+item['baseline'];item['regions']=[name]
                comparisons[identifier(name+'_'+key)]=item
        ready['scenarios']=expanded;ready['comparisons']=comparisons
    else:
        for comparison in ready.get('comparisons',{}).values():comparison['regions']=list(selected)
    # Preserve preparation provenance, but do not imply the output config is a portable source template.
    ready.pop('site_preparation',None)
    atomic_json(out/'study.json',ready)
    stat=land.stat()
    atomic_json(out/'selection_report.json',{'source_gridlist':str(grid),'source_landuse':str(land),'source_landuse_size':stat.st_size,'source_landuse_mtime_ns':stat.st_mtime_ns,
        'source_grid_sha256':hashlib.sha256(grid.read_bytes()).hexdigest(),'reference_year':reference,'minimum_forest_fraction':threshold,
        'climate_basis':'Broad geographic climate strata; not per-pixel Koppen classification. See site_preparation.zones.',
        'selection_mode':mode,'minimum_points_per_zone':minimum if mode=='rectangle_minimum_points' else None,
        'selection_method':'Smallest grid-cell footprint meeting minimum point count; prefer compact aspect ratio, then highest mean forest fraction; include every eligible point within the chosen rectangle' if mode=='rectangle_minimum_points' else 'Complete rectangular blocks ranked by mean forest fraction', 'rectangle_shape':shape,'rectangle_shapes':{name:[r['rows'],r['columns']] for name,r in rectangles.items()},'rectangles':rectangles,
        'source_years':[min(source_years),max(source_years)],'simulation_years':[first,last],'written_years':[start,last],
        'outside_source_years':policy,'boundary_held_records':len(filled),'zones':counts,'selected_points':len(used),
        'shortfalls':{},
        'landuse_files':{'controlled_regrowth':'landuse_forest1.txt','landuse_change':'landuse_dynamic.txt'}})
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study',required=True,type=Path);p.add_argument('--source-gridlist');p.add_argument('--source-landuse');p.add_argument('--output-dir')
    args=p.parse_args()
    try:
        out=prepare(args.study,args.source_gridlist,args.source_landuse,args.output_dir)
        print(f'Prepared inputs and study: {out / "study.json"}')
    except (ConfigError,KeyError,ValueError,OSError) as exc:
        p.exit(2,f'ERROR: {exc}\n')

if __name__=='__main__':main()
