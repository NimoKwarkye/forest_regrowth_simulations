"""Write the portable example configurations (also used to refresh examples)."""
import json
from pathlib import Path

base=Path(__file__).resolve().parent.parent/'examples'
cluster={
 'executable':'/absolute/path/to/guess', 'python':'/absolute/path/to/venv/bin/python',
 'partition':'CHANGE_ME', 'finish_partition':'CHANGE_ME', 'nodes':1,'processes_per_node':1,
 'finish_tasks':1,'max_active':5,'walltime':'3-00:00:00','finish_walltime':'1-00:00:00',
 'account':None,'qos':None,'memory':None,'environment':[],
 'data_prefix':'/bg/data/lpj', 'work_prefix':'/bg/data/lpj/work',
 'reference_helpers':{'setup':'/bg/data/lpj/scripts/setup_run_owl_with_scratch_lpj_work.sh',
 'scratch':'mpi_run_guess_on_tmp.sh','finish':'finishup_lpj_work_owl.sh','append':'append_files.sh'}
}
trees=['BNE','BINE','BNS','TeNE','TeBS','IBS','TeBE','TrBE','TrIBE','TrBR','TrIBR']
outputs=[]
def output(var,keyword,file,unit,values,role=None,basis='per unit forest stand-type area',nonnegative=True):
 d=dict(variable=var,keyword=keyword,file=file,unit=unit,area_basis=basis,key=['Lon','Lat','Year'],year_column='Year',values=values,records_per_site_year=1,nonnegative=nonnegative)
 if role: d['role']=role
 outputs.append(d)
output('aboveground_carbon','file_agb_gridcell','agb_gridcell.out','kg C m-2','TREE_PFTS','biomass','per unit grid-cell area; sum of model woody PFT columns')
output('clearcut_wood_carbon','file_cmass_wood_clearcut_sts','cmass_wood_clearcut_sts.out','kg C m-2 yr-1',['Forest'],'harvest_event')
output('harvest_wood_carbon','file_cmass_wood_harv_sts','cmass_wood_harv_sts.out','kg C m-2 yr-1',['Forest'],'harvest_total')
output('tree_carbon','file_cmass_tree_sts','cmass_tree_sts.out','kg C m-2',['Forest'])
output('wood_carbon','file_cmass_wood_sts','cmass_wood_sts.out','kg C m-2',['Forest'])
output('mortality_carbon','file_cmass_tree_mort_sts','cmass_tree_mort_sts.out','kg C m-2 yr-1',['Forest'])
output('npp','file_anpp_sts','anpp_sts.out','kg C m-2 yr-1',['Forest'],nonnegative=False)
output('gpp','file_agpp_gridcell','agpp_gridcell.out','kg C m-2 yr-1','TREE_PFTS',basis='per unit grid-cell area; sum of model woody PFT columns')
output('density','file_dens_sts','dens_sts.out','individuals m-2',['Forest'])
output('litter_carbon','file_clitter_sts','clitter_sts.out','kg C m-2',['Forest'])
output('soil_carbon','file_csoil_sts','csoil_sts.out','kg C m-2',['Forest'])
# Height and diameter are not additive: one output variable per selected PFT.
output('height_BNE','file_speciesheights','height.out','m',['BNE'],basis='mean for BNE; confirm weighting in executable')
output('diameter_BNE','file_speciesdiam','diam.out','cm',['BNE'],basis='mean for BNE; confirm weighting in executable')
study={
 'cluster':'cluster.json','ins_directory':'/bg/data/lpj/kwarkye-n/simulations/eu_to_global/forest_regrowth/test_2','main_ins':'guess.ins',
 'gridlist':'/absolute/path/to/test_2/gridlist.txt','model_source':'/absolute/path/to/european_applications',
 'forcing_experiment':None,
 'experiments':'experiments.csv','input_module':'cfx','stand':'Forest','management':'Forest_management',
 'selection':['BNE'],'selection_note':'DEVELOPMENT EXAMPLE ONLY: BNE is a global PFT, not a species; choose deliberately.',
 'baseline':'baseline','cut_year':1905,'first_year':1901,'last_year':2020,'killgrass_at_cc':0,
 'disturbance_audit_confirmed':False,'landcover_audit_confirmed':False,'executable_compatibility_confirmed':False,
 'biomass':{'kind':'carbon','definition_reviewed':False,'definition':'REVIEW REQUIRED: verify file_agb_gridcell formula and carbon units against the deployed executable. Selected woody PFT columns exclude grasses.','carbon_fraction':None},
 'validation':{'harvest_tolerance':1e-8,'fatal_log_patterns':['\\bFATAL\\b','mass balance error']},
 'analysis':{'percentage_floor':1e-8}, 'outputs':outputs}
base.mkdir(exist_ok=True)
for name,data in [('cluster.json',cluster),('study.json',study)]:
 (base/name).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
(base/'experiments.csv').write_text('id,densities,reestab,twig_removal\nbaseline,2000,NONE,0.4\ndensity_low,1000,NONE,0.4\ndensity_high,3000,NONE,0.4\nrecruitment_all,2000,ALL,0.4\ntwig_retained,2000,NONE,0.0\n',encoding='utf-8')

# A separate workspace prevents mixing old regeneration executions with forcing runs.
forcing_study={**study, 'workspace':'../forcing-study-workspace',
               'forcing_experiment':{'reference_year':1901,'start_year':1905,'management_experiment':'baseline',
                   'treatments':{'baseline':{'fix_climate':False,'fix_co2':False},
                                 'co2_constant':{'fix_climate':False,'fix_co2':True},
                                 'climate_constant':{'fix_climate':True,'fix_co2':False}}}}
forcing_study={'forcing_experiment':forcing_study.pop('forcing_experiment'), **forcing_study}
(base/'study-forcing.json').write_text(json.dumps(forcing_study,indent=2)+'\n',encoding='utf-8')
