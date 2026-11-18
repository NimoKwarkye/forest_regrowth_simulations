from pathlib import Path
import json, csv, hashlib
import numpy as np
import os, pyproj
os.environ['PROJ_DATA']=pyproj.datadir.get_data_dir()
os.environ['PROJ_LIB']=pyproj.datadir.get_data_dir()
import rasterio
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
import cartopy
import cartopy.crs as ccrs
from cartopy.io import shapereader
from cartopy.mpl.path import shapely_to_path
from shapely.ops import unary_union

out=Path(__file__).resolve().parent
cartopy.config['data_dir']=str(out/'map_data')
source=Path(r'F:\post_doc\forest_regrowth\growthcurve_regrowth.tif')
lon,lat=-64.75,-0.75
with rasterio.open(source) as src:
    assert pyproj.CRS(src.crs).equals(pyproj.CRS.from_epsg(4326),ignore_axis_order=True), 'Expected geographic WGS84 raster'
    assert src.count==4
    row,col=src.index(lon,lat)
    values=src.read(window=rasterio.windows.Window(col,row,1,1),masked=True)[:,0,0]
    assert not np.any(np.ma.getmaskarray(values)) and np.isfinite(values).all(), 'Point has no valid parameters'
    raw=[float(v) for v in values]
    cube=np.ma.masked_invalid(src.read(masked=True))
    extent=(src.bounds.left,src.bounds.right,src.bounds.bottom,src.bounds.top)
    center=src.xy(row,col)
    pixel_bounds=rasterio.windows.bounds(rasterio.windows.Window(col,row,1,1),src.transform)
    profile={'crs':str(src.crs),'width':src.width,'height':src.height,'resolution':src.res,'nodata':src.nodata,'band_descriptions':src.descriptions}
A,b,c,d=raw
assert A>0 and b>0 and c>0
ages=np.arange(0,121,dtype=float)
agb=(A*(-np.expm1(-b*ages))**c+d)*.1
asymptote=(A+d)*.1
assert np.isfinite(agb).all() and np.all(np.diff(agb)>=-1e-9)
assert np.isclose(agb[0],d*.1)
report=dict(source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),metadata=profile,
    requested_point={'longitude':lon,'latitude':lat},extraction='Containing raster cell; no interpolation',
    row_zero_based=row,column_zero_based=col,pixel_center=center,pixel_bounds_wsen=pixel_bounds,
    parameters_original=dict(A_Mg_ha=A,b_per_year=b,c=c,d_Mg_ha=d),
    parameters_converted=dict(A_kg_m2=A*.1,b_per_year=b,c=c,d_kg_m2=d*.1),
    asymptote_kg_m2=asymptote,equation='AGB(t) = A * (1 - exp(-b*t))**c + d',
    conversion='1 Mg/ha = 0.1 kg/m2; biomass mass, not carbon mass',
    displayed_age_range_years=[0,120],fit_age_support='Not stated in accompanying README; long-age extrapolation is illustrative',
    provenance_note='README: TMF-domain fits; some pixels spatially interpolated. This pixel has no interpolation flag.',
    boundary_source='Natural Earth 1:110m land polygons; public domain')
(out/'parameters.json').write_text(json.dumps(report,indent=2)+'\n')
with (out/'regrowth_curve.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['age_years','AGB_kg_m2']);w.writerows(zip(ages,agb))
plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
def save(fig,name):
    for ext in ('png','pdf'):fig.savefig(out/f'{name}.{ext}',dpi=220,bbox_inches='tight')
    plt.close(fig)
fig,ax=plt.subplots(figsize=(9,5.6))
ax.plot(ages,agb,color=plt.get_cmap('jet')(.15),lw=2.5,label='Chapman–Richards regrowth')
ax.axhline(asymptote,color='.4',ls='--',lw=1,label=f'Asymptote: {asymptote:.2f} kg/m²')
ax.set(xlabel='Forest age (years)',ylabel='Aboveground biomass (kg/m²)',xlim=(0,120),ylim=(0,max(asymptote,agb.max())*1.15),title='Forest regrowth at 64.75°W, 0.75°S')
ax.text(.97,.32,f'A = {A*.1:.5g} kg/m²\nb = {b:.5g} yr⁻¹\nc = {c:.5g}\nd = {d*.1:.5g} kg/m²',ha='right',va='top',transform=ax.transAxes,bbox=dict(facecolor='white',edgecolor='.85',alpha=.95))
ax.grid(alpha=.18);ax.legend(loc='upper left',frameon=False)
fig.text(.12,.015,'1° raster cell; Mg/ha × 0.1 → kg/m². Age range shown is illustrative.',fontsize=9,color='.35')
fig.tight_layout(rect=(0,.04,1,1));save(fig,'regrowth_curve')
land_path=shapereader.natural_earth(resolution='110m',category='physical',name='land')
land=unary_union(list(shapereader.Reader(land_path).geometries()))
def base_map(ax):
    ax.set_global();ax.set_facecolor('white')
    ax.add_geometries([land],ccrs.PlateCarree(),facecolor='#efefeb',edgecolor='#444444',linewidth=.45,zorder=1)
    ax.spines['geo'].set_visible(False)
    ax.plot(lon,lat,marker='*',color='#d7191c',markeredgecolor='white',markeredgewidth=.6,markersize=12,transform=ccrs.PlateCarree(),zorder=5)
fig=plt.figure(figsize=(12,6.2));ax=fig.add_subplot(111,projection=ccrs.PlateCarree());base_map(ax)
ax.annotate('Reference point\n64.75°W, 0.75°S',xy=(lon,lat),xytext=(-145,-40),arrowprops=dict(arrowstyle='-',color='.25'),fontsize=11,bbox=dict(facecolor='white',edgecolor='none'),zorder=6)
ax.set_title('Global land and the reference location',pad=15)
fig.text(.12,.045,'Continental outlines: Natural Earth. Ocean areas are blank.',fontsize=9,color='.4')
save(fig,'reference_location')
fig,axes=plt.subplots(2,2,figsize=(14,8),subplot_kw={'projection':ccrs.PlateCarree()},layout='constrained')
names=['A: biomass amplitude (kg/m²)','b: growth-rate parameter (yr⁻¹)','c: shape parameter (dimensionless)','d: initial biomass (kg/m²)']
scales=[]
for i,ax in enumerate(axes.flat):
    base_map(ax)
    layer=cube[i]*(.1 if i in (0,3) else 1)
    valid=layer.compressed();lo,hi=np.percentile(valid,[2,98])
    if lo==hi:lo,hi=float(valid.min()),float(valid.max())
    if lo==hi:lo,hi=lo-.5,hi+.5
    im=ax.imshow(layer,extent=extent,origin='upper',transform=ccrs.PlateCarree(),cmap='jet',vmin=lo,vmax=hi,interpolation='nearest',zorder=2)
    im.set_clip_path(PathPatch(shapely_to_path(land),transform=ax.transData))
    ax.add_geometries([land],ccrs.PlateCarree(),facecolor='none',edgecolor='#444444',linewidth=.4,zorder=3)
    ax.set_title(names[i],fontsize=12)
    fig.colorbar(im,ax=ax,orientation='horizontal',shrink=.82,pad=.04,extend='both')
    scales.append({'band':i+1,'color_min':lo,'color_max':hi})
fig.suptitle('Chapman–Richards regrowth parameters • reference point marked by a star\nBlank oceans; grey land = no parameter data; colors use 2nd–98th percentile limits',fontsize=12)
save(fig,'global_parameters')
report['map_color_limits']=scales;(out/'parameters.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
