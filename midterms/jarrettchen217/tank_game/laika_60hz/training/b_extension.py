"""Frozen u2924 B continuation limits and retained in-process evaluator."""
import json
import shutil
import time
from pathlib import Path

from tank_game.laika_60hz.training.engineering import atomic_json
from tank_game.laika_60hz.training.pilot import evaluate_panel, used_bytes

PROFILE='b-u2924-150mb'
SSH_CAP,MAC_CAP,GROUP=100000000,50000000,4400000
MILESTONES=(3948,4972,5996)
EXCLUDED=('checkpoints',*(f'milestone-u{u}' for u in MILESTONES))


def profile(context):
    if (context.get('continuation')!=PROFILE or context.get('max_updates')!=3072
            or context.get('arm')!='b'):
        raise ValueError('only the frozen B3072 continuation is accepted')
    return {'base_update':2924,'base_steps':14409472,
            'base_sha':'f7ecd27bf09151e351a74d5268c05a9d22aa6d0ea0a139b2b28fb47c608a59c6',
            'base_source':'1b455c485f0e8a4fcc06e8429b70c08d9e86ef3f',
            'base_protocol':'docs/evidence/source60-lr-comparison-v1.json',
            'lr_multiplier':.5,'ssh_cap':SSH_CAP,'log_cap':3000000}


def training_seconds(*,now,started,evaluation):
    return max(0,now-started-evaluation)


def next_deadline(*,now,used_training,batch_end,opt_stop):
    return min(now+max(0,5400-used_training),batch_end-10,opt_stop-10)


def metadata_bytes(output):
    output=Path(output)
    return used_bytes(output)-sum(used_bytes(output/n) for n in EXCLUDED)


def check_budget(allocation,output,*,now,deadline):
    if (now>=deadline or used_bytes(allocation)>SSH_CAP or metadata_bytes(output)>3000000
            or shutil.disk_usage(output).free<10*1024**3):
        raise RuntimeError('expanded cumulative/log/time/free-disk cap')


def storage_plan(ssh_bytes,mac_bytes):
    plan={'existing_ssh':ssh_bytes,'existing_mac':mac_bytes,'ssh_groups':5*GROUP,
          'mac_groups':5*GROUP,'ssh_peak':ssh_bytes+5*GROUP+3000000,
          'mac_peak':mac_bytes+5*GROUP+2000000}
    plan['combined_peak']=plan['ssh_peak']+plan['mac_peak']
    if plan['ssh_peak']>SSH_CAP or plan['mac_peak']>MAC_CAP or plan['combined_peak']>150000000:
        raise RuntimeError('expanded cumulative quota insufficient')
    return plan


class EvaluationControl:
    def __init__(self,hook):
        self.hook=hook
        self.seconds=0.
        self.panels={}
        self.started_cases=0

    def used_training(self):
        return training_seconds(now=time.monotonic(),started=self.hook.started,evaluation=self.seconds)

    def deadline(self):
        c=self.hook.c
        return next_deadline(now=time.time(),used_training=self.used_training(),
                             batch_end=c['batch_deadline_unix'],opt_stop=c['optimization_stop_unix'])

    def stop(self,update,steps,reason):
        atomic_json(self.hook.output/'training-stop.json',{'update':update,'steps':steps,
                    'training_seconds':self.used_training(),'evaluation_seconds':self.seconds,
                    'started_cases':self.started_cases,'panels':self.panels,'reason':reason})

    def after_checkpoint(self,model,marker,model_steps,orderly):
        hook=self.hook;update=marker['update']
        if update in MILESTONES:
            destination=hook.output/f'milestone-u{update}'
            if destination.exists() or used_bytes(hook.c['allocation'])+GROUP>SSH_CAP:
                raise RuntimeError('immutable milestone exists or lacks snapshot reserve')
            shutil.copytree(hook.groups.output/marker['slot'],destination)
            deadline=min(time.time()+max(0,1200-self.seconds),hook.c['batch_deadline_unix']-10)
            atomic_json(hook.output/'phase.json',{'phase':'evaluation','update':update,'deadline_unix':deadline})
            was_training=model.training;before=time.monotonic();result=None
            try:
                result=evaluate_panel(model,hook.output/f'milestone-u{update}.jsonl',deadline,update,seeds=range(21000,21100))
            finally:
                self.seconds+=time.monotonic()-before
                model.train(was_training)
                meters=[json.loads(p.read_text()) for p in hook.output.glob('milestone-u*.progress.json')]
                self.started_cases=sum(x['started_cases'] for x in meters)
                atomic_json(hook.output/'evaluation-budget.json',{'seconds':self.seconds,'started_cases':self.started_cases})
            self.panels[str(update)]=result
            if result['status']!='complete' or self.started_cases>300:
                self.stop(update,model_steps,'partial evaluation; no retry')
                raise SystemExit(74)
            hook.deadline=self.deadline()
            atomic_json(hook.output/'phase.json',{'phase':'training','deadline_unix':hook.deadline,
                        'training_seconds':self.used_training(),'evaluation_seconds':self.seconds})
            orderly=orderly or time.time()>=hook.deadline-10
        if update==5996 or orderly:
            self.stop(update,model_steps,'fixed3072 endpoint' if update==5996 else 'training/absolute time cap')
            raise SystemExit(75 if update==5996 else 76)
