"""Scenario integration tests using synthetic model output, without Slurm."""
import csv
import json
import math
from pathlib import Path
from test_tool import Fixture
from lpjregrowth.config import Study, write_text, atomic_json
from lpjregrowth.instructions import ConfigError, Instructions
from lpjregrowth.scenarios import climate_settings, region_sites, freeze_table
from lpjregrowth.analysis import analyze, plot, biomass_value
from lpjregrowth.collect import collect
from lpjregrowth.workflow import prepare

class ScenarioTests(Fixture):
    def setup_scenarios(self):
        self.settings['scenarios']=[{'id':'historical'},{'id':'recycled','climate':{'mode':'recycle','window_start':1901,'window_end':1904,'apply_from':1906}}]
        self.settings['regions']={'north':{'longitude':[9,12],'latitude':[49,52],'weighting':'cell_area'}}
        self.settings['analysis']={'grid_resolution_degrees':[1,1]}
        self.settings['comparisons']={'climate':{'experiments':['historical','recycled'],'baseline':'historical','regions':['north'],'vary':['climate']}}
        self.save_settings()

    def test_climate_window_mapping(self):
        result=climate_settings({'mode':'recycle','window_start':1980,'window_end':2000,'apply_from':2001},{'mode':'fixed_year','reference_year':1850,'apply_from':2005},1901,2100)
        self.assertEqual(result['extend_climate_nyears'],21)
        self.assertEqual(result['extend_climate_startyear'],2000)
        self.assertEqual(result['climate_recycle_from_year'],2001)
        self.assertEqual(result['fixed_co2_year'],1850)
        with self.assertRaises(ConfigError):climate_settings({'mode':'recycle','window_start':1800,'window_end':2000,'apply_from':2001},{},1901,2100)

    def test_regions_wrap_and_empty(self):
        self.assertEqual(len(region_sites(['179 0','-179 0','0 0'],{'longitude':[170,-170]})),2)
        self.assertEqual(region_sites(self.study.records,{'latitude':[-10,0]}),[])

    def test_generation_and_rank_subset(self):
        self.setup_scenarios()
        self.settings['regions']['one']={'sites':[[10,50]]}
        self.settings['scenarios'][1]['sites']='one'
        self.save_settings()
        paths=prepare(self.study)
        manifests=[json.loads(Path(p).read_text()) for p in paths]
        self.assertEqual(manifests[0]['processes'],2)
        self.assertEqual(manifests[1]['processes'],1)
        self.assertEqual(manifests[1]['rank_sites'],[[[10,50]]])
        ins=Instructions(Path(manifests[1]['work_dir'])/'guess.ins')
        self.assertEqual(ins.scalar('extend_climate_nyears'),'4')
        self.assertEqual(ins.scalar('climate_recycle_from_year'),'1906')

    def test_sla_preserves_calculated_baselines(self):
        with (self.root/'base.ins').open('a') as f:f.write('\nifcalcsla 1\npft "BNE" (\n leaflong 2\n leafphysiognomy "needleleaf"\n)\n')
        self.settings['scenarios']=[{'id':'sla','sweep':{'parameter':'sla','pfts':['BNE'],'multipliers':[.75,1,1.25]}}]
        self.save_settings()
        generated=self.study.generate()
        expected=.2*10**(2.29-.4*math.log10(24))
        for factor,path in zip([.75,1,1.25],generated):
            ins=Instructions(Path(path)/'guess.ins')
            self.assertEqual(ins.scalar('ifcalcsla'),'0')
            self.assertAlmostEqual(float(ins.resolve('pft','BNE')['sla'][0]),expected*factor)

    def test_fixed_ppm_staged_and_archived(self):
        write_text(self.root/'co2.txt','1904 300\n1905 301\n1906 302\n1907 303\n')
        with (self.root/'guess.ins').open('a') as f:f.write('param "file_co2" (str "co2.txt")\n')
        self.settings['scenarios']=[{'id':'fixed','co2':{'mode':'fixed_ppm','ppm':400,'apply_from':1906}}]
        self.save_settings()
        path=Path(prepare(self.study)[0]);m=json.loads(path.read_text())
        ins=Instructions(Path(m['work_dir'])/'guess.ins');co2=Path(ins.params['file_co2'][0])
        self.assertEqual(co2.parent,Path(m['work_dir'])/'inputs')
        self.assertIn('1905 301',co2.read_text());self.assertIn('1906 400',co2.read_text())
        self.synthetic_outputs(path);collect(path)
        self.assertTrue((Path(m['archive_dir'])/'inputs'/'co2.txt').exists())

    def test_regional_pipeline(self):
        self.setup_scenarios()
        for path in self.prepared():self.synthetic_outputs(path);collect(path)
        analyze(self.study)
        with (self.study.root/'results'/'regional_summary.csv').open() as f:rows=list(csv.DictReader(f))
        self.assertTrue(rows);self.assertTrue(all(int(r['sites'])==2 for r in rows))
        expected=6371008.8**2*math.radians(1)*sum(math.sin(math.radians(y+.5))-math.sin(math.radians(y-.5)) for y in (50,51))
        self.assertAlmostEqual(float(rows[0]['weight_sum']),expected,places=3)
        paths=plot(self.study)
        self.assertTrue(any('cross_site' in p for p in paths))
        self.assertTrue(any('Regional' in p for p in paths))

    def test_landuse_mode_allows_zero_biomass_and_later_harvest(self):
        self.settings['scenarios']=[{'id':'land','mode':'landuse_change'}]
        self.save_settings()
        path=Path(prepare(self.study)[0]);m=self.synthetic_outputs(path,later_cut=True)
        for run in Path(m['work_dir']).glob('run*'):
            agb=run/'agb.out'
            if agb.exists():
                lines=agb.read_text().splitlines();write_text(agb,lines[0]+'\n'+'\n'.join(' '.join(line.split()[:3]+['0']) for line in lines[1:])+'\n')
        collect(path)
        analyze(self.study)

    def test_landuse_freezing(self):
        source=self.root/'lu.txt';target=self.root/'fixed.txt'
        write_text(source,'Lon Lat Year FOREST NATURAL\n10 50 1904 .2 .8\n10 50 1905 .3 .7\n10 50 1906 .4 .6\n10 50 1907 .5 .5\n11 51 1904 .1 .9\n11 51 1905 .2 .8\n11 51 1906 .3 .7\n11 51 1907 .4 .6\n')
        freeze_table(source,target,self.study,1905,1906,False)
        self.assertIn('10.0 50.0 1907 0.3 0.7',target.read_text())
        self.assertIn('10.0 50.0 1904 0.2 0.8',target.read_text())

    def test_kg_dry_conversion(self):
        value,unit=biomass_value(10,{'role':'biomass','unit':'kg C m-2'},{'kind':'dry_mass','carbon_fraction':.5,'output_unit':'kg dry matter m-2'})
        self.assertEqual(value,20);self.assertEqual(unit,'kg dry matter m-2')

    def test_mismatched_sites_rejected(self):
        self.setup_scenarios();self.settings['regions']['one']={'sites':[[10,50]]};self.settings['scenarios'][1]['sites']='one';self.save_settings()
        for path in self.prepared():self.synthetic_outputs(path);collect(path)
        with self.assertRaisesRegex(ConfigError,'identical nonempty'):analyze(self.study)

    def test_undeclared_management_difference_rejected(self):
        self.setup_scenarios()
        self.settings['scenarios'][1]['base']='low'
        self.save_settings()
        for path in self.prepared():self.synthetic_outputs(path);collect(path)
        with self.assertRaisesRegex(ConfigError,'management'):analyze(self.study)

    def test_weighted_mean_uses_values_and_area(self):
        self.setup_scenarios()
        for path in self.prepared():
            m=self.synthetic_outputs(path)
            for run in Path(m['work_dir']).glob('run*'):
                file=run/'agb.out'
                if not file.exists():continue
                lines=file.read_text().splitlines();modified=[lines[0]]
                for line in lines[1:]:
                    cells=line.split()
                    if float(cells[0])==11:cells[-1]=str(float(cells[-1])*3)
                    modified.append(' '.join(cells))
                write_text(file,'\n'.join(modified)+'\n')
            collect(path)
        analyze(self.study)
        with (self.study.root/'results'/'regional_summary.csv').open() as f:row=next(r for r in csv.DictReader(f) if r['variable']=='agb' and r['time']=='1906')
        a=math.cos(math.radians(50));b=math.cos(math.radians(51))
        self.assertAlmostEqual(float(row['mean']),(1.1*a+3.3*b)/(a+b),places=10)

    def test_stale_scenario_rejected(self):
        self.setup_scenarios()
        for path in self.prepared():self.synthetic_outputs(path);collect(path)
        self.settings['scenarios'][1]['climate']['window_start']=1902;self.save_settings()
        with self.assertRaisesRegex(ConfigError,'changed since execution'):analyze(self.study)

    def test_forest_area_weights(self):
        self.setup_scenarios()
        for output in self.settings['outputs']:output['area_fraction_variable']='fraction'
        self.settings['outputs'].append(dict(variable='fraction',keyword='file_fraction',file='fraction.out',unit='1',area_basis='gridcell',key=['Lon','Lat','Year'],year_column='Year',values=['BNE'],area_fraction_variable='fraction'))
        self.settings['regions']['north']['weighting']='forest_area'
        self.save_settings()
        for path in self.prepared():
            # Fixture helper expects roles on every output; give fraction its own role.
            m=json.loads(path.read_text())
            for output in m['outputs']:output.setdefault('role','fraction')
            atomic_json(path,m)
            m=self.synthetic_outputs(path)
            for run in Path(m['work_dir']).glob('run*'):
                file=run/'fraction.out'
                if file.exists():
                    lines=file.read_text().splitlines();write_text(file,lines[0]+'\n'+'\n'.join(' '.join(line.split()[:3]+['0.25' if float(line.split()[0])==10 else '0.75']) for line in lines[1:])+'\n')
            collect(path)
        # Match the added role in manifests.
        self.settings['outputs'][-1]['role']='fraction';self.save_settings()
        analyze(self.study)
        with (self.study.root/'results'/'regional_summary.csv').open() as f:row=next(r for r in csv.DictReader(f) if r['variable']=='agb')
        r=6371008.8**2*math.radians(1)
        expected=r*(.25*(math.sin(math.radians(50.5))-math.sin(math.radians(49.5)))+.75*(math.sin(math.radians(51.5))-math.sin(math.radians(50.5))))
        self.assertAlmostEqual(float(row['weight_sum']),expected,places=3)

    def test_freezing_requires_explicit_transition_policy(self):
        write_text(self.root/'lu.txt','Lon Lat Year FOREST\n10 50 1904 1\n11 51 1904 1\n')
        with (self.root/'guess.ins').open('a') as f:f.write('param "file_lu" (str "lu.txt")\nparam "file_grossLUC" (str "lu.txt")\n')
        self.settings['scenarios']=[{'id':'land','mode':'landuse_change','landuse':{'mode':'fixed_year','reference_year':1904,'apply_from':1904,'freeze_inputs':['file_lu'],'audit_confirmed':True}}]
        self.save_settings()
        with self.assertRaisesRegex(ConfigError,'file_grossLUC'):self.study.generate()


    def test_empty_ranges_zero_outputs_without_changing_simulation_grid(self):
        self.setup_scenarios()
        self.settings['regions']['empty']={'longitude':[-70,-60],'latitude':[-10,0],'weighting':'forest_area'}
        # Omitting comparison regions groups by all user-specified ranges.
        self.settings['comparisons']['climate'].pop('regions')
        self.save_settings()
        for path in self.prepared():
            m=self.synthetic_outputs(path)
            self.assertEqual(m['sites'],[[10,50],[11,51]])
            collect(path)
        analyze(self.study)
        with (self.study.root/'results'/'regional_summary.csv').open() as f:rows=list(csv.DictReader(f))
        empty=[r for r in rows if r['region']=='empty']
        self.assertEqual(len(empty),2*4*3)
        for r in empty:
            self.assertEqual(r['status'],'empty_region')
            for key in ('sites','weight_sum','mean','minimum','maximum'):self.assertEqual(float(r[key]),0)
        self.assertTrue(any(r['region']=='north' and r['status']=='ok' and float(r['mean'])>0 for r in rows))
        with (self.study.root/'results'/'comparison_differences.csv').open() as f:
            for r in csv.DictReader(f):
                if r['region']=='empty':
                    self.assertEqual(float(r['difference']),0)
                    self.assertEqual(r['percent_difference'],'')
        figures=plot(self.study)
        self.assertTrue(any('Regional_climate_empty_agb' in p for p in figures))

    def test_empty_simulation_subset_is_not_submitted(self):
        self.setup_scenarios()
        self.settings['regions']['empty']={'latitude':[-10,0]}
        self.settings['scenarios'][1]['sites']='empty'
        self.save_settings()
        with self.assertRaisesRegex(ConfigError,'simulation subset is empty'):prepare(self.study)
