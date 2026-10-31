"""Small explicit experiment journal. No model runtime or automatic repair/restart."""
import math
import os
import uuid
from pathlib import Path

from tank_game.learning.ppo_protocol import read_json


def _write(path, value):
    import json
    temporary=path.with_suffix(path.suffix+'.partial')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    os.replace(temporary,path)


class SamplingCounter:
    """Charge submitted batches, including a possibly incomplete final vector wait."""
    def __init__(self, initial_steps, limit, batch):
        self.initial_steps=initial_steps
        self.limit=limit
        self.batch=batch
        self.submitted=0
        self.returned=0

    @property
    def charged_steps(self):
        return self.initial_steps+self.submitted

    def submit(self):
        if self.charged_steps+self.batch>self.limit:
            raise ValueError('cumulative sampling budget exhausted')
        self.submitted+=self.batch

    def receive(self):
        self.returned+=self.batch


class Experiment:
    def __init__(self, root, protocol, *, mode, lock_sha256):
        self.root=Path(root).resolve()
        self.protocol=protocol
        self.mode=mode
        self.lock_sha256=lock_sha256
        self.path=self.root/'experiment.json'
        self.budget_path=self.root/'evaluation-budget.json'

    def __enter__(self):
        import fcntl
        self.root.mkdir(parents=True,exist_ok=True)
        self.lock=(self.root/'experiment.lock').open('a')
        try:
            fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            identity={'schema_version':1,'protocol_sha256':self.protocol['_runtime']['sha256'],
                      'lock_sha256':self.lock_sha256,'mode':self.mode,
                      'evaluation_budget':str(self.budget_path)}
            self.value=read_json(self.path) if self.path.exists() else identity|{
                'experiment_id':str(uuid.uuid4()),'seeds':{}}
            if any(self.value.get(k)!=v for k,v in identity.items()):
                raise ValueError('incompatible experiment identity')
            self.save()
            return self
        except BaseException:
            self.lock.close()
            raise

    def __exit__(self, *error):
        self.lock.close()  # Kernel releases flock, no stale-lock repair/deletion.

    def save(self):
        _write(self.path,self.value)

    def latest_checkpoint(self, seed):
        candidates=[]
        for attempt in self.value['seeds'].get(str(seed),{}).get('attempts',[]):
            for path in Path(attempt['output']).glob('checkpoint-*'):
                if not path.is_dir():
                    continue
                m=read_json(path/'metadata.json')
                if (m.get('experiment_id')!=self.value['experiment_id'] or m.get('seed')!=seed
                        or m.get('run_mode')!=self.mode or m.get('protocol_sha256')!=self.value['protocol_sha256']
                        or type(m.get('sampled_steps')) is not int or m['sampled_steps']%4096
                        or m.get('completed_updates')!=m['sampled_steps']//4096):
                    raise ValueError('checkpoint is not from this experiment/seed/mode')
                candidates.append((m['sampled_steps'],path.resolve()))
        return max(candidates,key=lambda x:x[0])[1] if candidates else None

    def begin(self, seed, output, resume):
        output=Path(output).resolve()
        output.relative_to(self.root)
        if output.exists():
            raise FileExistsError(output)
        if type(seed) is not int or seed not in self.protocol['seeds']:
            raise ValueError('unknown experiment seed')
        state=self.value['seeds'].get(str(seed),{'training_seconds':0.0,'sampled_total':0,'attempts':[]})
        if state.get('status')=='complete':
            raise ValueError('completed seed cannot be repeated')
        if state.get('status') in ('running','unconfirmed'):
            raise ValueError('previous attempt accounting unconfirmed; preserve and inspect')
        latest=self.latest_checkpoint(seed)
        if state['attempts']:
            if latest is None or resume is None or Path(resume).resolve()!=latest:
                raise ValueError('explicit latest checkpoint from the same experiment required')
        elif resume is not None:
            raise ValueError('cannot warm-start a new experiment')
        initial=read_json(latest/'metadata.json')['sampled_steps'] if latest else 0
        cap=900 if self.mode=='recovery-check' else self.protocol['budgets']['training_wall_seconds_per_seed']
        steps=16384 if self.mode=='recovery-check' else self.protocol['budgets']['per_seed_transitions']
        remaining=cap-state['training_seconds']
        endpoint=8192 if self.mode=='recovery-check' else steps
        if (remaining<=60 or state['sampled_total']>steps
                or (state['sampled_total']==steps and initial<endpoint)):
            raise ValueError('cumulative experiment budget exhausted')
        request={'experiment_id':self.value['experiment_id'],'experiment':str(self.root),
                 'attempt_index':len(state['attempts']),'output':str(output),
                 'initial_steps':initial,'sampled_before':state['sampled_total'],
                 'training_seconds_before':state['training_seconds'],'remaining_training_seconds':remaining,
                 'model_step_limit':steps-(state['sampled_total']-initial)}
        state['attempts'].append({'output': str(output),'resume': str(latest) if latest else None,
                                      'initial_steps': initial,'status': 'running'})
        state['status']='running'
        self.value['seeds'][str(seed)]=state
        self.save()
        return request

    def finish(self, seed, request, result, checkpoint):
        state=self.value['seeds'][str(seed)]
        seconds=result['accounted_training_seconds']
        if type(seconds) not in (float,int) or not math.isfinite(seconds) or seconds<0:
            raise ValueError('invalid training accounting')
        sampled=result.get('worker',{}).get('sampled_steps')
        confirmed=type(sampled) is int and sampled>=request['initial_steps']
        attempt=state['attempts'][request['attempt_index']]
        attempt.update(status=result['status'] if confirmed else 'unconfirmed',
            training_seconds=seconds,sampled_steps=sampled,
            stop_reason=result.get('stop_reason'),checkpoint=str(checkpoint) if checkpoint else None)
        state['status']=attempt['status']
        state['training_seconds']+=seconds
        if confirmed:
            state['sampled_total']+=sampled-request['initial_steps']
        state['last_checkpoint']=attempt['checkpoint']
        state['was_interrupted']=len(state['attempts'])>1 or state['status']!='complete'
        self.save()
