"""Fixture-based tests: no scheduler, model execution, or real inputs required."""
import csv
import gzip
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from lpjregrowth.config import Study, infer_roots, atomic_json, read_grid, split_grid, write_text
from lpjregrowth.instructions import ConfigError, Instructions, uncomment
from lpjregrowth.workflow import Store, prepare, submit_execution, refresh, slurm_submit
from lpjregrowth.collect import collect, merge_table, validate_table, verify_archive
from lpjregrowth.analysis import analyze, biomass_value


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        write_text(self.root/'base.ins','''group "tree" (
 lifeform "tree"
 include 1
)
pft "BNE" (
 tree
 sla 9
)
st "Natural" (
 stinclude 1
 landcover "natural"
)
mt "Forest_management" (
 cutfirstyear 1
 firstmanageyear 1905
 harvest_system "clearcut"
 cutinterval 60
)
st "Forest" (
 stinclude 1
 landcover "forest"
 management1 "Forest_management"
 naturalveg "all"
)
firsthistyear 1904
lasthistyear 1907
''')
        write_text(self.root/'guess.ins','import "base.ins"\nparam "file_gridlist" (str "grid.txt")\n')
        write_text(self.root/'grid.txt','! comment\n10 50 site_a\n\n11 51 site_b\n')
        write_text(self.root/'guess','#!/bin/bash\nexit 0\n')
        write_text(self.root/'experiments.csv','id,densities,reestab,twig_removal\nbaseline,2000,NONE,0.4\nlow,1000,NONE,0.4\n')
        c=dict(executable=str(self.root/'guess'),python='/usr/bin/python3',partition='test',finish_partition='finish',nodes=1,processes_per_node=2,finish_tasks=1,max_active=1,walltime='1:00:00',finish_walltime='0:30:00',environment=[],work_root=str(self.root/'work'),submission_root=str(self.root/'submissions'),archive_root=str(self.root/'archives'))
        atomic_json(self.root/'cluster.json',c)
        outputs=[]
        for var,role in [('agb','biomass'),('clearcut','harvest_event'),('harvest','harvest_total')]:
            outputs.append(dict(variable=var,role=role,keyword='file_'+var,file=var+'.out',unit='kg C m-2',area_basis='gridcell',key=['Lon','Lat','Year'],year_column='Year',values=['BNE'],nonnegative=True))
        self.settings=dict(cluster='cluster.json',workspace='workspace',main_ins='guess.ins',gridlist='grid.txt',experiments='experiments.csv',selection=['BNE'],cut_year=1905,outputs=outputs,biomass=dict(kind='carbon',definition_reviewed=True,definition='synthetic fixture'),disturbance_audit_confirmed=True,landcover_audit_confirmed=True,executable_compatibility_confirmed=True)
        self.save_settings()

    def save_settings(self):
        atomic_json(self.root/'study.json',self.settings)
        self.study=Study(self.root/'study.json')

    def prepared(self, ids=None):
        return [Path(p) for p in prepare(self.study,ids)]

    def synthetic_outputs(self,path,later_cut=False):
        m=json.loads(path.read_text())
        for i,sites in enumerate(m['rank_sites'],1):
            run=Path(m['work_dir'])/f'run{i}'
            write_text(run/'model.exitcode','0\n')
            write_text(run/'copy.exitcode','0\n')
            write_text(run/'guess.log','Synthetic fixture only; no model simulation.\n')
            for spec in m['outputs']:
                lines=['Lon Lat Year BNE']
                for lon,lat in sites:
                    for year in range(1904,1908):
                        value=(0.1+max(0,year-1905)) if spec['role']=='biomass' else (4 if year==1905 or (later_cut and year==1907) else 0)
                        lines.append(f'{lon} {lat} {year} {value}')
                write_text(run/spec['file'],'\n'.join(lines)+'\n')
        return m


class ConfigurationTests(Fixture):
    def test_inferred_roots_and_overrides(self):
        data = self.root / 'data'
        work = data / 'work'
        directory = data / 'user' / 'simulations' / 'test_2'
        c = dict(data_prefix=str(data), work_prefix=str(work))
        result = infer_roots(c, directory)
        self.assertEqual(Path(result['work_root']), work / 'user' / 'simulations' / 'test_2')
        self.assertEqual(Path(result['archive_root']), directory / 'archives')
        self.assertEqual(Path(result['submission_root']), directory / 'submissions')
        explicit = dict(work_root='custom-work', submission_root='custom-submit', archive_root='custom-archive')
        self.assertEqual(infer_roots(explicit.copy(), directory), explicit)
        with self.assertRaises(ConfigError):
            infer_roots(dict(data_prefix=str(data), work_prefix=str(work)), self.root / 'elsewhere')
        with self.assertRaises(ConfigError):
            infer_roots(dict(data_prefix=str(data), work_prefix=str(work)), work / 'user')

    def test_instruction_directory_entry_and_workspace(self):
        self.settings['ins_directory'] = str(self.root)
        self.settings.pop('workspace')
        self.save_settings()
        self.assertEqual(self.study.base, self.root / 'guess.ins')
        self.assertEqual(self.study.root, self.root / 'regrowth-workspace')
        self.settings.pop('main_ins')
        with self.assertRaises(ConfigError):
            self.save_settings()
        (self.root / 'base.ins').rename(self.root / 'base.inc')
        write_text(self.root / 'guess.ins', 'import "base.inc"\n')
        self.save_settings()
        self.assertEqual(self.study.base, self.root / 'guess.ins')

    def test_imports_inheritance_and_generation(self):
        self.study.validate()
        generated=self.study.generate(['baseline'])[0]
        parsed=Instructions(Path(generated)/'guess.ins')
        self.assertEqual(parsed.resolve('pft','BNE')['sla'],['9'])
        mt=parsed.resolve('mt','Forest_management')
        self.assertEqual(mt['cutinterval'],['0'])
        self.assertEqual(mt['plantdensity'],['2000'])
        first=(Path(generated)/'guess.ins').read_bytes()
        self.study.generate(['baseline'])
        self.assertEqual(first,(Path(generated)/'guess.ins').read_bytes())

    def test_import_cycle_and_missing(self):
        write_text(self.root/'a.ins','import "b.ins"\n')
        with self.assertRaisesRegex(ConfigError,'Missing'):
            Instructions(self.root/'a.ins')
        write_text(self.root/'b.ins','import "a.ins"\n')
        with self.assertRaisesRegex(ConfigError,'cycle'):
            Instructions(self.root/'a.ins')

    def test_comments_and_bang_in_strings(self):
        self.assertEqual(uncomment('param "x" (str "a!b") ! comment'),'param "x" (str "a!b") ')

    def test_balanced_split_preserves_records(self):
        chunks=split_grid([str(i) for i in range(8)],3)
        self.assertEqual(list(map(len,chunks)),[3,3,2])
        self.assertEqual(sum(chunks,[]),[str(i) for i in range(8)])
        with self.assertRaises(ConfigError): split_grid(['one'],2)
        self.assertEqual(read_grid(self.root/'grid.txt'),['10 50 site_a','11 51 site_b'])

    def test_invalid_pft_and_density(self):
        self.settings['selection']=['Pic_abi'];self.save_settings()
        with self.assertRaisesRegex(ConfigError,'Undefined'):
            self.study.validate()
        self.settings['selection']=['BNE'];self.save_settings()
        write_text(self.root/'experiments.csv','id,densities,reestab,twig_removal\nbaseline,1000 2000,NONE,0.4\n')
        self.save_settings()
        with self.assertRaisesRegex(ConfigError,'density'):
            self.study.validate()

    def test_external_cutting_override_rejected(self):
        with (self.root/'guess.ins').open('a') as f:f.write('param "file_cutinterval_st" (str "/data/cuts.txt")\n')
        self.save_settings()
        with self.assertRaisesRegex(ConfigError,'conflicts'):
            self.study.validate()

    def test_duplicate_grid_rejected(self):
        write_text(self.root/'grid.txt','10 50\n10 50\n')
        with self.assertRaisesRegex(ConfigError,'Duplicate'):
            read_grid(self.root/'grid.txt')


class WorkflowTests(Fixture):
    def test_prepare_rank_directories_and_commands(self):
        path=self.prepared(['baseline'])[0]
        m=json.loads(path.read_text());work=Path(m['work_dir'])
        self.assertEqual((work/'run1/gridlist.txt').read_text(),'10 50 site_a\n')
        self.assertEqual((work/'run2/gridlist.txt').read_text(),'11 51 site_b\n')
        script=(work/'submit.sh').read_text()
        self.assertIn('#SBATCH --ntasks=2',script)
        self.assertIn('srun --label',script)
        self.assertIn('-parallel -input cfx guess.ins',script)
        with self.assertRaisesRegex(ConfigError,'already'):
            prepare(self.study,['baseline'])

    def test_two_jobs_dependency_and_limit(self):
        paths=self.prepared()
        runner=Mock(side_effect=[subprocess.CompletedProcess([],0,'111;cluster\n',''),subprocess.CompletedProcess([],0,'112\n','')])
        result=submit_execution(paths[0],runner)
        self.assertEqual(result['simulation_job'],'111')
        self.assertIn('--dependency=afterok:111',runner.call_args_list[1].args[0])
        self.assertEqual(submit_execution(paths[1],runner)['status'],'deferred')
        with self.assertRaisesRegex(ConfigError,'prepared'):
            submit_execution(paths[0],runner)

    def test_ambiguous_submission_not_retried(self):
        path=self.prepared(['baseline'])[0]
        runner=Mock(return_value=subprocess.CompletedProcess([],0,'unexpected response',''))
        with self.assertRaises(ConfigError):submit_execution(path,runner)
        self.assertEqual(Store(self.study.root).rows()[0]['status'],'submission_unknown')

    def test_failed_simulation_cancels_owned_dependency(self):
        path=self.prepared(['baseline'])[0]
        m=json.loads(path.read_text());store=Store(self.study.root)
        store.update(m['execution_id'],'submitted',sim_job='111',finish_job='112')
        runner=Mock(side_effect=[subprocess.CompletedProcess([],0,'111|FAILED|1:0\n112|PENDING|0:0\n',''),subprocess.CompletedProcess([],0,'','')])
        refresh(store,runner)
        self.assertEqual(store.rows()[0]['status'],'failed')
        self.assertEqual(runner.call_args_list[1].args[0],['scancel','112'])

    def test_checksum_tampering_blocks_submit(self):
        path=self.prepared(['baseline'])[0]
        write_text(path.parent/'guess.ins','tampered')
        with self.assertRaisesRegex(ConfigError,'changed'):
            submit_execution(path,Mock())


class CollectionTests(Fixture):
    def test_complete_collection_analysis(self):
        paths=self.prepared()
        for path in paths:
            self.synthetic_outputs(path)
            archive=Path(collect(path))
            verify_archive(archive)
            self.assertTrue((archive/'agb.out.gz').is_file())
            self.assertEqual(len(list(__import__('lpjregrowth.collect',fromlist=['read_table']).read_table(archive/'agb.out.gz'))),8)
        result=Path(analyze(self.study))
        records=list(csv.DictReader((result/'timeseries.csv').read_text().splitlines()))
        self.assertTrue(any(r['years_since_cut']=='0' for r in records))
        diffs=list(csv.DictReader((result/'differences.csv').read_text().splitlines()))
        self.assertTrue(all(float(r['difference'])==0 for r in diffs))

    def test_plot_validated_fixture(self):
        try:
            import matplotlib
        except ImportError:
            self.skipTest('Install plotting dependencies')
        from lpjregrowth.analysis import plot
        for path in self.prepared():
            self.synthetic_outputs(path)
            collect(path)
        analyze(self.study)
        files=plot(self.study)
        self.assertTrue(any(f.endswith('.pdf') for f in files))
        self.assertTrue(any('difference' in f for f in files))
        self.assertTrue(all(Path(f).stat().st_size>100 for f in files))

    def test_precut_difference_can_block_analysis(self):
        for path in self.prepared():
            m=self.synthetic_outputs(path)
            if m['experiment']['id']=='low':
                output=Path(m['work_dir'])/'run1/agb.out'
                text=output.read_text().replace('1904 0.1','1904 0.9')
                write_text(output,text)
            collect(path)
        self.study.config['analysis']={'require_equal_precut':True}
        with self.assertRaisesRegex(ConfigError,'Pre-cut states differ'):
            analyze(self.study)
        self.assertFalse((self.study.root/'results/analysis.json').exists())

    def test_second_cut_fails(self):
        path=self.prepared(['baseline'])[0]
        m=self.synthetic_outputs(path,later_cut=True)
        with self.assertRaisesRegex(ConfigError,'later harvest'): collect(path)
        self.assertFalse(Path(m['archive_dir']).exists())
        self.assertEqual(Store(self.study.root).rows()[0]['status'],'failed')

    def test_missing_rank_file_fails(self):
        path=self.prepared(['baseline'])[0];m=self.synthetic_outputs(path)
        (Path(m['work_dir'])/'run2/agb.out').unlink()
        with self.assertRaisesRegex(ConfigError,'inventories'): collect(path)

    def test_header_mismatch_fails(self):
        path=self.prepared(['baseline'])[0];m=self.synthetic_outputs(path)
        output=Path(m['work_dir'])/'run2/agb.out'
        write_text(output,output.read_text().replace('BNE','BINE'))
        with self.assertRaisesRegex(ConfigError,'header'):collect(path)

    def test_duplicate_and_missing_rows_fail(self):
        for duplicate in (True,False):
            with self.subTest(duplicate=duplicate):
                table=self.root/'table.out'
                lines=['Lon Lat Year BNE']+[f'{lon} {lat} {y} 1' for lon,lat in [(10,50),(11,51)] for y in range(1904,1908)]
                if duplicate:lines.append(lines[-1])
                else:lines.pop()
                write_text(table,'\n'.join(lines)+'\n')
                manifest=dict(sites=[[10,50],[11,51]],first_year=1904,last_year=1907,cut_year=1905,study={})
                with sqlite3.connect(':memory:') as db:
                    with self.assertRaises(ConfigError):validate_table(table,self.settings['outputs'][0],manifest,db)

    def test_archive_corruption_detected(self):
        path=self.prepared(['baseline'])[0];self.synthetic_outputs(path)
        archive=Path(collect(path));write_text(archive/'guess.ins','changed')
        with self.assertRaisesRegex(ConfigError,'corrupted'):verify_archive(archive)

    def test_model_failure_not_collected(self):
        path=self.prepared(['baseline'])[0];m=self.synthetic_outputs(path)
        write_text(Path(m['work_dir'])/'run1/model.exitcode','1')
        with self.assertRaisesRegex(ConfigError,'successful'):collect(path)

    def test_conversion_requires_fraction(self):
        spec=dict(role='biomass',unit='kg C m-2')
        self.assertEqual(biomass_value(1,spec,dict(kind='dry_mass',carbon_fraction=.5)),(20,'Mg dry matter ha-1'))
        with self.assertRaises(ConfigError):biomass_value(1,spec,dict(kind='dry_mass',carbon_fraction=0))


if __name__=='__main__':unittest.main()

class ForcingTests(Fixture):
    def enable(self):
        write_text(self.root/'co2.txt', '1901 296\n1902 297\n')
        with (self.root/'guess.ins').open('a') as f:
            f.write('param "file_co2" (str "co2.txt")\n')
        self.settings['forcing_experiment']={'reference_year':1901, 'start_year':1905}
        self.save_settings()

    def test_three_treatments_same_management_and_original_inputs(self):
        self.enable()
        self.assertEqual([e['id'] for e in self.study.experiments],['baseline','co2_constant','climate_constant'])
        management=[self.study.management_values(e) for e in self.study.experiments]
        self.assertTrue(all(m == management[0] for m in management))
        for folder in self.study.generate():
            parsed=Instructions(Path(folder)/'guess.ins')
            name=Path(folder).name
            self.assertEqual(json.loads((Path(folder)/'forcing-settings.json').read_text()),next(e for e in self.study.experiments if e['id']==name)['forcing']['settings'])
            self.assertEqual(parsed.scalar('fixed_co2'),str(int(name=='co2_constant')))
            self.assertEqual(parsed.scalar('extend_climate'),str(int(name=='climate_constant')))
            self.assertEqual(parsed.scalar('extend_climate_nyears'),'1')
            self.assertEqual(parsed.scalar('climate_recycle_from_year'),'1905')
            self.assertEqual(parsed.scalar('restart'),'0')
            self.assertEqual(parsed.scalar('save_state'),'0')
            self.assertEqual(Path(parsed.params['file_co2'][0]),self.root/'co2.txt')

    def test_forcing_defaults_and_invalid_options(self):
        self.enable()
        self.settings['forcing_experiment'].pop('start_year')
        self.save_settings()
        self.assertEqual(self.study.experiments[0]['forcing']['start_year'],1905)
        for invalid in ({'reference_year':1901,'start_year':1800}, {'reference_year':'1901'},
                        {'reference_year':1901,'management_experiment':'missing'}, {'reference_year':1901,'typo':1}):
            self.settings['forcing_experiment']=invalid
            with self.assertRaises(ConfigError): self.save_settings()

    def test_forcing_requires_cfx_and_co2(self):
        self.enable()
        self.settings['input_module']='cf'
        with self.assertRaises(ConfigError): self.save_settings()
        self.settings['input_module']='cfx'
        write_text(self.root/'guess.ins','import "base.ins"\n')
        self.save_settings()
        with self.assertRaisesRegex(ConfigError,'file_co2'): self.study.validate()

    def completed(self):
        self.enable()
        for path in self.prepared():
            m=self.synthetic_outputs(path)
            factor={'baseline':1,'co2_constant':.8,'climate_constant':.6}[m['experiment']['id']]
            for run in Path(m['work_dir']).glob('run*'):
                p=run/'agb.out'
                if not p.is_file(): continue
                lines=p.read_text().splitlines()
                for i in range(1,len(lines)):
                    parts=lines[i].split()
                    if int(parts[2])>=1905: parts[3]=str(float(parts[3])*factor)
                    lines[i]=' '.join(parts)
                write_text(p,'\n'.join(lines)+'\n')
            collect(path)

    def test_comparison_values_and_figures(self):
        self.completed()
        result=Path(analyze(self.study))
        rows=list(csv.DictReader((result/'differences.csv').read_text().splitlines()))
        row=next(r for r in rows if r['experiment_id']=='co2_constant' and r['variable']=='agb' and r['calendar_year']=='1907')
        self.assertAlmostEqual(float(row['difference']),-.42)
        self.assertAlmostEqual(float(row['percent_difference']),-20)
        metadata=json.loads((result/'analysis.json').read_text())
        self.assertEqual(metadata['precut_differences_above_tolerance'],0)
        self.assertTrue(all(e['forcing'] for e in metadata['executions']))
        try: import matplotlib
        except ImportError: self.skipTest('Install plotting dependencies')
        from lpjregrowth.analysis import plot
        files=plot(self.study)
        self.assertEqual(len([p for p in files if 'forcing_comparison_' in p]),4)
        self.assertTrue(all(Path(p).stat().st_size>100 for p in files))

    def test_stale_forcing_and_management_rejected(self):
        self.completed()
        self.settings['forcing_experiment']['reference_year']=1902
        self.save_settings()
        with self.assertRaisesRegex(ConfigError,'forcing differs'): analyze(self.study)
        self.settings['forcing_experiment']['reference_year']=1901
        self.settings['killgrass_at_cc']=1
        self.save_settings()
        with self.assertRaisesRegex(ConfigError,'management differs'): analyze(self.study)

    def test_analysis_requires_complete_forcing_comparison(self):
        self.enable()
        with self.assertRaisesRegex(ConfigError,'all configured treatments'):
            analyze(self.study,['baseline'])

class CleanupTests(Fixture):
    def test_preview_and_full_cleanup_preserve_unrelated(self):
        from lpjregrowth.cleanup import clean
        path=self.prepared(['baseline'])[0];m=json.loads(path.read_text())
        other=Path(m['work_dir']).parent/'unrelated';other.mkdir();write_text(other/'keep.txt','keep')
        archive=Path(m['archive_dir']);archive.mkdir(parents=True);write_text(archive/'execution.json',path.read_text())
        preview=clean(self.study,include_archives=True)
        self.assertEqual(preview['mode'],'preview');self.assertTrue(path.exists())
        clean(self.study,execute=True,include_archives=True)
        self.assertFalse(self.study.root.exists());self.assertFalse(Path(m['work_dir']).exists())
        self.assertFalse(archive.exists());self.assertTrue((other/'keep.txt').exists())
        self.assertTrue(self.study.base.exists())

    def test_default_preserves_archives(self):
        from lpjregrowth.cleanup import clean
        path=self.prepared(['baseline'])[0];m=json.loads(path.read_text())
        archive=Path(m['archive_dir']);archive.mkdir(parents=True)
        result=clean(self.study,execute=True)
        self.assertIn(str(archive),result['retain_archives']);self.assertTrue(archive.exists())

    def test_active_and_orphan_refused(self):
        from lpjregrowth.cleanup import clean
        path=self.prepared(['baseline'])[0];m=json.loads(path.read_text())
        Store(self.study.root).update(m['execution_id'],'submitted',sim_job='12')
        with self.assertRaisesRegex(ConfigError,'active/uncertain'):clean(self.study,execute=True)
        self.assertTrue(path.exists())
        (self.study.root/'status.sqlite').unlink()
        with self.assertRaisesRegex(ConfigError,'no tracking'):clean(self.study,execute=True)
        self.assertTrue(path.exists())

    def test_slurm_checks_before_deletion(self):
        from lpjregrowth.cleanup import clean
        path=self.prepared(['baseline'])[0];m=json.loads(path.read_text())
        Store(self.study.root).update(m['execution_id'],'complete',sim_job='12',finish_job='13')
        runner=Mock(return_value=subprocess.CompletedProcess([],0,'13\n',''))
        with self.assertRaisesRegex(ConfigError,'Slurm jobs'):clean(self.study,execute=True,runner=runner)
        self.assertTrue(path.exists())
        runner.return_value=subprocess.CompletedProcess([],0,'','')
        clean(self.study,execute=True,runner=runner)
        self.assertFalse(path.exists())

    def test_path_tampering_refused(self):
        from lpjregrowth.cleanup import clean
        path=self.prepared(['baseline'])[0];m=json.loads(path.read_text())
        m['work_dir']=str(self.root)
        for p in [path,Path(m['submission_dir'])/'execution.json']:atomic_json(p,m)
        with self.assertRaisesRegex(ConfigError,'outside'):clean(self.study,execute=True)
        self.assertTrue(self.study.base.exists())

    def test_generated_only_workspace(self):
        from lpjregrowth.cleanup import clean
        self.study.generate()
        clean(self.study,execute=True)
        self.assertFalse(self.study.root.exists());self.assertTrue(self.study.base.exists())

    def test_retained_archives_can_be_cleaned_later(self):
        from lpjregrowth.cleanup import clean
        path=self.prepared(['baseline'])[0];m=json.loads(path.read_text())
        archive=Path(m['archive_dir']);archive.mkdir(parents=True)
        write_text(archive/'execution.json',path.read_text())
        clean(self.study,execute=True)
        self.assertTrue(archive.exists())
        clean(self.study,execute=True,include_archives=True)
        self.assertFalse(archive.exists())


class ForcingSwitchTests(Fixture):
    enable = ForcingTests.enable
    def test_json_switches_control_instructions_and_labels(self):
        from lpjregrowth.forcing import labels
        self.enable()
        self.settings['forcing_experiment']['treatments']={
            'baseline':{'fix_climate':False,'fix_co2':False},
            'both_fixed':{'fix_climate':True,'fix_co2':True},
            'neither_fixed':{'fix_climate':False,'fix_co2':False}}
        self.save_settings()
        outputs=self.study.generate()
        both=Instructions(next(Path(p)/'guess.ins' for p in outputs if Path(p).name=='both_fixed'))
        self.assertEqual(both.scalar('extend_climate'),'1')
        self.assertEqual(both.scalar('fixed_co2'),'1')
        neither=Instructions(next(Path(p)/'guess.ins' for p in outputs if Path(p).name=='neither_fixed'))
        self.assertEqual(neither.scalar('extend_climate'),'0')
        self.assertEqual(neither.scalar('fixed_co2'),'0')
        self.assertEqual(labels(self.study.experiments)['both_fixed'],'Reference-year climate + fixed CO2')

    def test_invalid_switches_rejected(self):
        self.enable()
        for flags in ({'fix_climate':0,'fix_co2':False},{'fix_climate':False}, {'fix_climate':False,'fix_co2':'true'}):
            self.settings['forcing_experiment']['treatments']={'baseline':{'fix_climate':False,'fix_co2':False},'other':flags}
            with self.assertRaises(ConfigError): self.save_settings()
        self.settings['forcing_experiment']['treatments']={'baseline':{'fix_climate':True,'fix_co2':False},'other':{'fix_climate':False,'fix_co2':True}}
        with self.assertRaises(ConfigError): self.save_settings()

    def test_two_configured_treatments_plot(self):
        self.enable()
        self.settings['forcing_experiment']['treatments']={
            'baseline':{'fix_climate':False,'fix_co2':False},
            'both_fixed':{'fix_climate':True,'fix_co2':True}}
        self.settings['analysis']={'plot_max_sites':1}
        self.save_settings()
        for path in self.prepared():
            self.synthetic_outputs(path)
            collect(path)
        analyze(self.study)
        try: import matplotlib
        except ImportError: self.skipTest('Install plotting dependencies')
        from lpjregrowth.analysis import plot
        self.assertEqual(len([p for p in plot(self.study) if 'forcing_comparison_' in p]),2)
