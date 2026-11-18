"""Command-line interface. No command submits implicitly."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from .config import Study
from .instructions import ConfigError
from .workflow import Store, prepare, refresh, submit_execution


def main(argv=None):
    parser=argparse.ArgumentParser(description='LPJ-GUESS regrowth and multi-site scenario experiments on Slurm')
    parser.add_argument('command',choices=['validate','generate','prepare','submit','status','collect','analyze','plot','adopt-jobs','clean'])
    parser.add_argument('--yes',action='store_true',help='For clean: execute the previewed deletion')
    parser.add_argument('--include-archives',action='store_true',help='For clean: also remove final and partial archives')
    parser.add_argument('--study',type=Path)
    parser.add_argument('--execution',type=Path)
    parser.add_argument('--experiments',nargs='+')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--remote-checks',action='store_true')
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--retry',action='store_true')
    parser.add_argument('--watch',action='store_true',help='For submit: refill available slots until selected executions finish')
    parser.add_argument('--poll-seconds',type=int,default=60)
    parser.add_argument('--simulation-job')
    parser.add_argument('--finish-job')
    args=parser.parse_args(argv)
    try:
        if args.execution:
            if args.command=='collect':
                from .collect import collect
                result={'would_collect':str(args.execution)} if args.dry_run else collect(args.execution)
            elif args.command=='submit':
                result={'would_submit':str(args.execution)} if args.dry_run else submit_execution(args.execution)
            elif args.command=='adopt-jobs':
                import re
                if not args.simulation_job or not args.finish_job or not all(re.fullmatch(r'[0-9]+',x) for x in (args.simulation_job,args.finish_job)):
                    raise ConfigError('Supply verified --simulation-job and --finish-job IDs')
                m=json.loads(args.execution.read_text())
                if args.dry_run:
                    result={'would_adopt':[args.simulation_job,args.finish_job]}
                else:
                    Store(m['state_root']).update(m['execution_id'],'submitted',sim_job=args.simulation_job,finish_job=args.finish_job,reason='Job IDs explicitly reconciled by user')
                    result={'adopted':m['execution_id']}
            else:
                raise ConfigError('--execution supports submit, collect, or adopt-jobs')
        else:
            if not args.study:
                raise ConfigError('--study is required')
            study=Study(args.study)
            if args.command=='clean':
                if args.experiments:
                    raise ConfigError('clean operates on the entire workspace, not an experiment subset')
                from .cleanup import clean
                result=clean(study, execute=args.yes and not args.dry_run, include_archives=args.include_archives)
            elif args.command=='validate':
                result={'warnings':study.validate(args.remote_checks),'experiments':study.selected(args.experiments),
                        'sites':len(study.records),'processes':study.processes,'period':[study.first_year,study.last_year],
                        'source_files':list(map(str,study.ins.files)),
                        'forcing':{'enabled':study.config.get('forcing_experiment') is not None or study.config.get('scenarios') is not None,
                                   'message':'Forcing settings are written to generated guess.ins, not the original imported climate ins.',
                                   'instruction_settings':{e['id']:e.get('forcing',{}).get('settings',{}) for e in study.selected(args.experiments)}},
                        'directories':dict(ins_directory=str(study.instruction_dir), workspace=str(study.root), **{k:str(study.cluster_path_value(k)) for k in ('submission_root','work_root','archive_root')}),
                        'baseline_management':study.ins.resolve('mt',study.management)}
            elif args.dry_run:
                result={'command':args.command,'warnings':study.validate(args.remote_checks),
                        'experiments':study.selected(args.experiments),'submission': 'No jobs submitted'}
            elif args.command=='generate':
                result=study.generate(args.experiments)
            elif args.command=='prepare':
                result=prepare(study,args.experiments,args.retry)
            elif args.command=='submit':
                study.validate(remote=True)
                store=Store(study.root)
                selected={e['id'] for e in study.selected(args.experiments)}
                if args.watch and args.poll_seconds < 10:
                    raise ConfigError('--poll-seconds must be at least 10')
                result=[]
                while True:
                    if args.watch:
                        refresh(store)
                    for row in store.rows():
                        if row['status']=='prepared' and row['experiment'] in selected:
                            result.append(submit_execution(row['manifest']))
                    if not args.watch:
                        break
                    pending=[r for r in store.rows() if r['experiment'] in selected and r['status'] not in ('complete','failed','cancelled')]
                    if not pending:
                        break
                    if any(r['status'] in ('submission_unknown','finish_submission_failed','submitting') for r in pending):
                        raise ConfigError('Submission needs reconciliation; use status and adopt-jobs before continuing')
                    import time
                    print(json.dumps({'pending':len(pending),'time':__import__('datetime').datetime.now().isoformat()}),flush=True)
                    time.sleep(args.poll_seconds)
                if args.watch:
                    result=store.rows()
            elif args.command=='status':
                store=Store(study.root)
                result=refresh(store) if args.refresh else store.rows()
            elif args.command=='collect':
                from .collect import collect
                selected={e['id'] for e in study.selected(args.experiments)}
                result=[collect(row['manifest']) for row in Store(study.root).rows()
                        if row['experiment'] in selected and row['status'] not in ('prepared','submitting','submission_unknown','cancelled')]
            elif args.command=='analyze':
                from .analysis import analyze
                result=analyze(study,args.experiments)
            elif args.command=='plot':
                from .analysis import plot
                result=plot(study)
            else:
                raise ConfigError('adopt-jobs requires --execution')
        print(json.dumps(result,indent=2,default=str))
        return 0
    except (ConfigError,KeyError,ValueError,OSError,subprocess.SubprocessError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 2
