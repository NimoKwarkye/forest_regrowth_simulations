import csv
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import Mock
from prepare_sites import prepare,select_rectangle,select_cluster
from test_tool import Fixture
from lpjregrowth.config import atomic_json,write_text,digest
from lpjregrowth.instructions import Instructions
from lpjregrowth.workflow import prepare as prepare_jobs, submit_execution

class PreparationTests(unittest.TestCase):
    def test_contiguous_rectangle_not_scattered_high_values(self):
        points={(x/2,y/2) for x in range(4) for y in range(4)}|{(20,20)}
        forest={p:.7 for p in points};forest[20,20]=1
        result,bounds=select_rectangle(points,forest,[3,3],[.5,.5])
        self.assertEqual(len(result),9);self.assertNotIn((20,20),result)
        self.assertEqual(len({x for x,y in result}),3)
        self.assertEqual(bounds['longitude'],[-.25,1.25])

    def test_minimum_cluster_allows_gaps(self):
        points={(x,y) for x in range(3) for y in range(3)}-{(1,1)}
        forest={p:.8 for p in points}
        chosen,bounds=select_cluster(points,forest,7,[1,1])
        self.assertEqual(set(chosen),points)
        self.assertEqual(bounds['selected_points'],8)
        self.assertEqual(bounds['unselected_slots'],1)
        self.assertEqual(bounds['rectangle_slots'],9)
        self.assertEqual(select_cluster(points,forest,9,[1,1]),([] ,{}))

    def test_generation_years_fractions_areas_and_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);points=[(x+.25,y+.25) for x in range(2) for y in range(2)]
            write_text(root/'grid.txt',''.join(f'{x} {y}\n' for x,y in points))
            write_text(root/'lu.txt','Lon Lat Year FOREST NATURAL\n'+''.join(f'{x} {y} {year}.0 {v} {1-v}\n' for x,y in points for year,v in [(2000,.8),(2001,.6)]))
            cfg={'cluster':'cluster.json','experiments':'experiments.csv','model_source':'/bg/home/model','first_year':2000,'last_year':2003,'scenarios':[{'id':'baseline'}],
                 'site_preparation':{'source_gridlist':'grid.txt','source_landuse':'lu.txt','reference_year':2000,'rectangle_shape':[2,2],'grid_resolution_degrees':[1,1],'outside_source_years':'hold_boundary','zones':{'zone':{'longitude':[-1,3],'latitude':[-1,3]}}}}
            atomic_json(root/'study.json',cfg);out=prepare(root/'study.json')
            with (out/'landuse_forest1.txt').open() as f:
                reader=csv.DictReader(f,delimiter=' ')
                self.assertEqual(reader.fieldnames,['Lon','Lat','Year','FOREST'])
                rows=list(reader)
            self.assertEqual(len(rows),16)
            self.assertTrue(all(float(r['FOREST'])==1 and set(r)=={'Lon','Lat','Year','FOREST'} for r in rows))
            with (out/'landuse_dynamic.txt').open() as f:rows=list(csv.DictReader(f,delimiter=' '))
            self.assertTrue(all(float(r['FOREST'])==.6 for r in rows if r['Year']=='2003'))
            ready=json.loads((out/'study.json').read_text());self.assertEqual(ready['cluster'],'../cluster.json');self.assertEqual(ready['model_source'],'/bg/home/model')
            self.assertEqual(len(ready['regions']['zone']['sites']),4)
            self.assertEqual(json.loads((out/'selection_report.json').read_text())['boundary_held_records'],8)

class PreparedInputTests(Fixture):
    def test_forest_and_dynamic_files_reach_generated_instructions(self):
        write_text(self.root/'forest.txt','Lon Lat Year FOREST\n10 50 1904 1\n')
        write_text(self.root/'dynamic.txt','Lon Lat Year FOREST NATURAL\n10 50 1904 .4 .6\n')
        self.settings['prepared_landuse']={'forest_only':'forest.txt','dynamic':'dynamic.txt'}
        self.settings['scenarios']=[{'id':'forest'},{'id':'changing','mode':'landuse_change'}]
        self.save_settings()
        paths=prepare_jobs(self.study)
        for path in paths:
            m=json.loads(Path(path).read_text());ins=Instructions(Path(m['work_dir'])/'guess.ins')
            source=Path(ins.params['file_lu'][0]);self.assertEqual(source.parent,Path(m['work_dir'])/'inputs')
            self.assertEqual(source.read_text(),(self.root/('forest.txt' if m['experiment']['id']=='forest' else 'dynamic.txt')).read_text())
            self.assertEqual(m['main_sha256'],digest(Path(m['work_dir'])/'guess.ins'))
        runner=Mock(side_effect=[subprocess.CompletedProcess([],0,'101\n',''),subprocess.CompletedProcess([],0,'102\n','')])
        self.assertEqual(submit_execution(paths[0],runner)['simulation_job'],'101')
        self.assertEqual(runner.call_count,2)

class NaturalRegenerationTests(Fixture):
    def test_natural_management_reaches_instructions(self):
        self.settings.update(regeneration='natural',selection=[])
        self.save_settings()
        paths=prepare_jobs(self.study,['baseline'])
        m=json.loads(Path(paths[0]).read_text())
        ins=Instructions(Path(m['work_dir'])/'guess.ins')
        mt=ins.resolve('mt','Forest_management')
        self.assertEqual(mt['planting_system'],[''])
        self.assertEqual(mt['selection'],[''])
        self.assertEqual(mt['set_planting_density'],['0'])
        self.assertEqual(mt['relaxed_establishment'],['0'])
        self.assertEqual(mt['reestab'],['ALL'])
        self.assertEqual(mt['harvest_system'],['clearcut'])
        self.assertEqual(ins.resolve('st','Forest')['naturalveg'],['all'])
