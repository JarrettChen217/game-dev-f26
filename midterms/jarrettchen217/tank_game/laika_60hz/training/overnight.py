"""One date-bound overnight continuation, using retained PPO/evaluation/save hooks."""
import json
import re
import shutil
import time
from pathlib import Path

from tank_game.laika_60hz.training.b_extension import EvaluationControl as PreviousControl
from tank_game.laika_60hz.training.engineering import atomic_json
from tank_game.laika_60hz.training.pilot import evaluate_panel, used_bytes

PROFILE='u5996-overnight-20261029'
SSH_CAP,MAC_CAP,GROUP=90000000,60000000,4400000
TRAIN_SECONDS,EVAL_SECONDS,CASE_CAP=24000,1800,400
BASE_UPDATE,END_UPDATE=5996,22380
MILESTONES=(10092,14188,18284,22380)


def profile(context):
    if context.get('continuation')!=PROFILE or context.get('arm')!='b' or context.get('max_updates')!=16384:
        raise ValueError('only the frozen single-night16384 upper bound is accepted')
    return {'base_update':5996,'base_steps':29548288,
            'base_sha':'9094f52b0f28a21810c98e335ed91476fbe7b2253406f28740a7dfdff6ed021b',
            'base_source':'62bb6cc53d30058ae5f37b0ed911aef8dec9151c',
            'base_protocol':'docs/evidence/source60-b-extension-v1.json',
            'lr_multiplier':.5,'ssh_cap':SSH_CAP,'log_cap':8000000}


def next_deadline(*,now,used_training,batch_end,opt_stop):
    return min(now+max(0,TRAIN_SECONDS-used_training),batch_end-30,opt_stop-10)


def needs_panel(update,final,panel_count):
    needed=update in MILESTONES or final
    if needed and panel_count>=4:
        raise RuntimeError('four-panel cap; never restart or replace a panel')
    return needed


def group_directories(output):
    root=Path(output)
    return [p for p in root.iterdir() if p.is_dir() and (p.name=='checkpoints'
            or re.fullmatch(r'(milestone|endpoint)-u[0-9]+',p.name))]


def metadata_bytes(output):
    return used_bytes(output)-sum(used_bytes(p) for p in group_directories(output))


def check_budget(allocation,output,*,now,deadline):
    if now>=deadline or used_bytes(allocation)>SSH_CAP or metadata_bytes(output)>8000000 or shutil.disk_usage(output).free<10*1024**3:
        raise RuntimeError('overnight time/cumulative/log/free-disk cap')


def storage_plan(ssh_bytes,mac_bytes):
    plan={'existing_ssh':ssh_bytes,'existing_mac':mac_bytes,'ssh_groups':6*GROUP,'mac_groups':4*GROUP,
          'ssh_peak':ssh_bytes+6*GROUP+8000000,'mac_peak':mac_bytes+4*GROUP+2000000}
    plan['combined_peak']=plan['ssh_peak']+plan['mac_peak']
    if plan['ssh_peak']>SSH_CAP or plan['mac_peak']>MAC_CAP or plan['combined_peak']>150000000:
        raise RuntimeError('inherited150MB cannot preserve old evidence and overnight endpoints')
    return plan


class EvaluationControl(PreviousControl):
    def __init__(self,hook):
        super().__init__(hook)
        self.panel_names={}

    def deadline(self):
        c=self.hook.c
        return next_deadline(now=time.time(),used_training=self.used_training(),
                             batch_end=c['batch_deadline_unix'],opt_stop=c['optimization_stop_unix'])

    def stop(self,update,steps,reason):
        atomic_json(self.hook.output/'training-stop.json',{'update':update,'steps':steps,
                    'training_seconds':self.used_training(),'evaluation_seconds':self.seconds,
                    'started_cases':self.started_cases,'panels':self.panels,'panel_names':self.panel_names,
                    'reason':reason,'endpoint_rule':'earliest frozen step/training-time/absolute-time cap; never score selected'})

    def after_checkpoint(self,model,marker,model_steps,orderly):
        hook=self.hook;update=marker['update'];final=update==END_UPDATE or orderly
        if needs_panel(update,final,len(self.panels)):
            label=('milestone-u' if update in MILESTONES else 'endpoint-u')+str(update)
            destination=hook.output/label
            if destination.exists() or used_bytes(hook.c['allocation'])+GROUP>SSH_CAP:
                raise RuntimeError('immutable point exists or lacks complete snapshot reserve')
            shutil.copytree(hook.groups.output/marker['slot'],destination)
            self.panel_names[str(update)]=label
            deadline=min(time.time()+min(900,max(0,EVAL_SECONDS-self.seconds)),hook.c['batch_deadline_unix']-30)
            atomic_json(hook.output/'phase.json',{'phase':'evaluation','update':update,'deadline_unix':deadline})
            was_training=model.training;before=time.monotonic();result=None
            try:
                result=evaluate_panel(model,hook.output/(label+'.jsonl'),deadline,update,seeds=range(21000,21100))
            finally:
                self.seconds+=time.monotonic()-before;model.train(was_training)
                meters=[json.loads(p.read_text()) for pattern in ('milestone-u*.progress.json','endpoint-u*.progress.json') for p in hook.output.glob(pattern)]
                self.started_cases=sum(x['started_cases'] for x in meters)
                atomic_json(hook.output/'evaluation-budget.json',{'seconds':self.seconds,'started_cases':self.started_cases})
            self.panels[str(update)]=result
            if result['status']!='complete' or self.started_cases>CASE_CAP:
                self.stop(update,model_steps,'partial evaluation; no retry')
                raise SystemExit(74)
            hook.deadline=self.deadline()
            atomic_json(hook.output/'phase.json',{'phase':'training','deadline_unix':hook.deadline,
                        'training_seconds':self.used_training(),'evaluation_seconds':self.seconds})
            final=final or time.time()>=hook.deadline-10
        if final:
            self.stop(update,model_steps,'fixed16384 upper bound' if update==END_UPDATE else 'frozen training/absolute time endpoint')
            raise SystemExit(75)
