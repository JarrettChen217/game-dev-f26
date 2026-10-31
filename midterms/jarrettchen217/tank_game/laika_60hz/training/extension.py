"""Full-stateu64 continuation; only Config/hook/instrumentation, retained PPO unchanged."""
import json
import math
import shutil
import sys
import time
from pathlib import Path

from tank_game.laika_60hz.training.engineering import atomic_json
from tank_game.laika_60hz.training.pilot import CAP, RollingGroups, evaluate_panel, used_bytes

BASE_SHA = '8ae23ef16d115fb53e71205db75bd0094aaa42ee7cb3fc3e26111434a98b9afa'
BASE_PROTOCOL = '7e30f34b9981f6cf134b9d15c4fe83d965f0c5e6b73ee7343504414abf929f2c'
BASE_SOURCE = '67724e811697f34295f48d4fe867dcdd6dd3de9f'
LOG_CAP = 786432


def storage_plan(allocation, groups, *, cap=CAP):
    protected = used_bytes(allocation)-used_bytes(groups)
    return {'protected_non_group_bytes': protected, 'two_group_reserves': 8800000,
            'extension_log_reserve': LOG_CAP, 'planned_peak': protected+8800000+LOG_CAP, 'cap': cap}


def arguments(context, output, resume):
    return ['source60-extension', '--steps', '5046272', '--envs', '16', '--seed', '11',
            '--critic-warmup-updates', '20', '--mix', '1', '0', '0', '--threads', '1',
            '--device', 'cuda', '--timing-profile', '--schedule-steps', '480000000',
            '--save-every', '0', '--resume', str(resume), '--research-context', str(context),
            '--output', str(output/'run')]


def compact_metric(record, *, base_update=64, base_steps=315392):
    if record['critic_only']:
        raise ValueError('restored20warmup must not repeat critic-only updates')
    row = {'update': record['update']+base_update+1, 'steps': record['steps']+base_steps,
           'new_steps': record['steps'], 'critic_only': False}
    for key in ('lr', 'entropy', 'policy_loss', 'value_loss', 'approx_kl', 'clipfrac', 'change_rate'):
        value = record[key]
        if value is not None and not math.isfinite(value):
            raise FloatingPointError('nonfinite metric '+key)
        row[key] = float(f'{value:.8g}') if value is not None else None  # log precision only
    if (row['update']-base_update) % 32 == 0:
        row['engineering_profile'] = record.get('engineering_profile', {})
    return row


def should_publish(update, base_update, end_update, orderly_stop):
    return (update-base_update) % 32 == 0 or update == end_update or orderly_stop


def ResearchHook(context_path):
    import numpy as np
    import torch

    from tank_game.laika_60hz.training.contract import contract_digest, validate_resume_metadata

    class Hook:
        def __init__(self):
            self.context = json.loads(Path(context_path).read_text())
            self.output = Path(self.context['output'])
            self.is_continue16 = self.context.get('variant') == 'u876-batch16'
            self.base_update, self.base_steps, self.end_update = 64, 315392, 1088
            self.base_sha, self.base_source, self.base_protocol = BASE_SHA, BASE_SOURCE, BASE_PROTOCOL
            self.cap, self.sampler_binding = CAP, None
            self.panel_cap, self.evaluation_cap = 180,900
            if self.is_continue16:
                from tank_game.laika_60hz.training import continuation16 as binding
                self.cap = binding.require_storage_approval(self.context['storage'])
                self.base_update, self.base_steps, self.end_update = binding.BASE_UPDATE, binding.BASE_STEPS, binding.END_UPDATE
                self.base_sha, self.base_source, self.base_protocol = binding.BASE_SHA, binding.BASE_SOURCE, binding.BASE_PROTOCOL
                self.sampler_binding = binding.validate_assets(self.context['old_assets'], self.context['batch_assets'],
                                                              self.context['source_root'])
                if self.sampler_binding != self.context['sampler_binding']:
                    raise ValueError('sampler execution binding mismatch')
                if contract_digest() != binding.PARENT_CONTRACT:
                    raise ValueError('parent environment contract mismatch')
                if self.context.get('skip_baseline'):
                    _,self.evaluation_cap,_ = binding.recovery_parameters(self.context['recovery'])
                    self.panel_cap = 300
            self.groups = RollingGroups(self.context['groups'], self.context['allocation'], cap=self.cap)
            self.training_started = None
            self.evaluation_seconds = 0.
            self.intermediate_evaluation_seconds = 0.
            self.evaluation_reserve = 315 if self.is_continue16 else 435
            self.deadline = self.context['batch_deadline_unix']-self.evaluation_reserve
            self.payload = None
            if self.context['environment_contract_sha256'] != contract_digest():
                raise ValueError('source60 environment mismatch')

        def check(self):
            launch_log = Path(self.context['launch_log'])
            logs = used_bytes(self.output)+(launch_log.stat().st_size if launch_log.exists() else 0)
            if (used_bytes(self.context['allocation']) > self.cap or logs > LOG_CAP-65536
                    or shutil.disk_usage(self.output).free < 10*1024**3):
                raise RuntimeError('approved cumulative/log/free-reserve cap')

        def restore(self, payload):
            if payload is None:
                raise ValueError('frozen full state required, no fresh initialization')
            state = payload['research']; validate_resume_metadata(state)
            if (state['protocol_sha256'] != self.base_protocol or state['source_head'] != self.base_source
                    or state['update'] != self.base_update or state['warmup_completed'] != 20
                    or payload['trained_steps'] != self.base_steps or payload['schedule_steps'] != 480000000):
                raise ValueError('wrong lineage/progress/schedule')
            torch.set_rng_state(state['torch_rng'].cpu()); np.random.set_state(state['numpy_rng'])
            torch.cuda.set_rng_state_all([v.cpu() for v in state['cuda_rng']])
            self.payload = payload
            return self.base_update, 20

        def before_rollout(self, batch):
            self.check()
            if batch != 4928 or time.time() >= self.deadline:
                raise SystemExit(74)

        def before_optimizer_step(self):
            if time.time() >= self.deadline:
                raise SystemExit(74)

        def metric(self, record):
            return compact_metric(record,base_update=self.base_update,base_steps=self.base_steps)

        def training_seconds(self):
            return time.monotonic()-self.training_started-self.intermediate_evaluation_seconds

        def phase(self, kind, deadline):
            if self.is_continue16:
                atomic_json(self.output/'phase.json',
                            {'phase':kind,'deadline_unix':deadline,'evaluation_seconds':self.evaluation_seconds,
                             'training_seconds':self.training_seconds() if self.training_started is not None else 0,
                             'observed_unix':time.time()})

        def panel(self, model, name, update):
            from tank_game.laika_60hz.training.continuation16 import panel_deadline
            was_training = model.training
            before = time.monotonic()
            deadline = panel_deadline(now=time.time(),used_seconds=self.evaluation_seconds,
                                      batch_deadline=self.context['batch_deadline_unix'],
                                      panel_cap=self.panel_cap,total_cap=self.evaluation_cap)
            self.phase('evaluation',deadline)
            try:
                result = evaluate_panel(model,self.output/(name+'.jsonl'),
                                        deadline,
                                        update,seeds=range(21000,21100))
            finally:
                elapsed = time.monotonic()-before
                self.evaluation_seconds += elapsed
                if self.training_started is not None:
                    self.intermediate_evaluation_seconds += elapsed
                model.train(was_training)
            atomic_json(self.output/'evaluation-status.json',
                        {'panel':name,'evaluation_seconds':self.evaluation_seconds,**result})
            print('EVALUATION '+json.dumps({'panel':name,**result}),flush=True)
            return result

        def publish(self, model, optimiser, config, model_steps, update, warmup_completed,
                    save_live, save_resume, started, schedule_steps):
            self.check()
            assert warmup_completed == 20 and schedule_steps == 480000000
            if update == self.base_update and self.training_started is None:
                def equal(a, b):
                    if torch.is_tensor(a):
                        return torch.equal(a.cpu(), b.cpu())
                    if isinstance(a, np.ndarray):
                        return np.array_equal(a, b)
                    if isinstance(a, dict):
                        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
                    if isinstance(a, (tuple, list)):
                        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b, strict=True))
                    return a == b
                saved = self.payload
                checks = {'model_and_critic': equal(model.state_dict(), saved['model']),
                          'Adam': equal(optimiser.state_dict(), saved['optimiser']),
                          'Torch_rng': equal(torch.get_rng_state(), saved['research']['torch_rng']),
                          'NumPy_rng': equal(np.random.get_state(), saved['research']['numpy_rng']),
                          'CUDA_rng': equal(torch.cuda.get_rng_state_all(), saved['research']['cuda_rng']),
                          'steps': model_steps == self.base_steps, 'warmup': warmup_completed == 20,
                          'schedule': schedule_steps == 480000000, 'environment_protocol_source': True}
                if not all(checks.values()):
                    raise ValueError('full restore mismatch '+str(checks))
                atomic_json(self.output/'restore-proof.json', {'checks': checks, 'base_resume_sha256': self.base_sha,
                            'sampler_binding':self.sampler_binding})
                seeds = range(21000,21100) if self.is_continue16 else range(20000,20100)
                if self.context.get('skip_baseline'):
                    panel = None  # retain the prior partial; do not synthesize a baseline result
                    atomic_json(self.output/'baseline-not-rerun.json',
                                {'status':'partial_from_prior_attempt','formal100_winrate':None,
                                 'prior_attempt':self.context['prior_attempt'],'new_started_cases':0})
                else:
                    panel = self.panel(model,'baseline-new100',self.base_update) if self.is_continue16 else evaluate_panel(model, self.output/'baseline-new100.jsonl',
                                       min(time.time()+300, self.context['batch_deadline_unix']-1), self.base_update,
                                       seeds=seeds)
                if panel is not None and panel['status'] != 'complete':
                    raise SystemExit(74)
                self.training_started = time.monotonic()
                self.deadline = min(time.time()+5400, self.context['batch_deadline_unix']-self.evaluation_reserve)
                atomic_json(self.output/'training-start.json', {'deadline_unix': self.deadline,
                            'base_update': self.base_update, 'base_steps': self.base_steps, 'warmup_completed': 20})
                self.phase('training',self.deadline)
                return
            orderly_stop = self.training_started is not None and time.time() >= self.deadline-10
            if not should_publish(update,self.base_update,self.end_update,orderly_stop):
                return
            assert all(torch.isfinite(v).all() for v in model.state_dict().values())
            assert all(not torch.is_tensor(v) or torch.isfinite(v).all()
                       for group in optimiser.state.values() for v in group.values())
            metadata = {'protocol_sha256': self.context['protocol_sha256'], 'source_head': self.context['source_head'],
                        'environment_contract_sha256': contract_digest(), 'update': update,
                        'warmup_completed': 20, 'base_resume_sha256': self.base_sha,
                        'base_protocol_sha256': self.base_protocol, 'torch_rng': torch.get_rng_state(),
                        'numpy_rng': np.random.get_state(), 'cuda_rng': torch.cuda.get_rng_state_all()}
            if self.sampler_binding:
                metadata['sampler_binding'] = self.sampler_binding
            def writer(path):
                save_live(path, model, config, model_steps, update, started, model_steps, schedule_steps)
                live = json.loads((path/'live.json').read_text())
                live.update(profile='source60-schema24-prep-v1', environment_contract_sha256=contract_digest())
                atomic_json(path/'live.json', live)
                save_resume(path, model, optimiser, model_steps, schedule_steps, research=metadata)
            marker = self.groups.publish(update, model_steps, 20, writer)
            atomic_json(self.output/'progress.json', {**marker, 'training_seconds': self.training_seconds(),
                        'new_steps': model_steps-self.base_steps, 'device': str(next(model.parameters()).device)})
            print('EXTENSION_CHECKPOINT '+json.dumps(marker), flush=True)
            if self.is_continue16 and not orderly_stop:
                from tank_game.laika_60hz.training.continuation16 import periodic_panel
                if periodic_panel(update):
                    panel = self.panel(model,'milestone-u'+str(update),update)
                    if panel['status'] != 'complete':
                        atomic_json(self.output/'training-stop.json', {'update':update,'steps':model_steps,
                                    'new_steps':model_steps-self.base_steps,'training_seconds':self.training_seconds(),
                                    'reason':'intermediate evaluation partial; no retry'})
                        raise SystemExit(74)
                    self.deadline = min(time.time()+max(0,5400-self.training_seconds()),
                                        self.context['batch_deadline_unix']-self.evaluation_reserve)
                    self.phase('training',self.deadline)
                    orderly_stop = time.time() >= self.deadline-10
            if update == self.end_update or orderly_stop:
                atomic_json(self.output/'training-stop.json', {'update': update, 'steps': model_steps,
                            'new_steps': model_steps-self.base_steps, 'training_seconds': self.training_seconds(),
                            'reason': 'fixed1024additional' if update == self.end_update else 'time cap'})
                if not self.is_continue16:
                    evaluate_panel(model, self.output/'endpoint-old20.jsonl',
                                   min(time.time()+120, self.context['batch_deadline_unix']-2), update)
                if self.is_continue16:
                    self.panel(model,'endpoint-new100',update)
                else:
                    evaluate_panel(model, self.output/'endpoint-new100.jsonl',
                               min(time.time()+300, self.context['batch_deadline_unix']-2), update,
                               seeds=range(20000,20100))
                raise SystemExit(75)

    return Hook()


def train(context_path):
    import torch

    from tank_game.laika_60hz.training import ppo

    torch.set_num_threads(1)
    original = ppo.ActorCritic
    class Audited(original):
        def __init__(self):
            super().__init__()
            for name, parameter in self.named_parameters():
                parameter.register_hook(lambda grad, name=name: self.check(name, grad))
        def check(self, name, grad):
            if not torch.isfinite(grad).all():
                raise FloatingPointError('nonfinite gradient '+name)
            return grad
    ppo.ActorCritic = Audited
    context = json.loads(Path(context_path).read_text())
    argument_builder = arguments
    if context.get('variant') == 'u876-batch16':
        from tank_game.laika_60hz.training.continuation16 import arguments as argument_builder
    sys.argv = argument_builder(Path(context_path), Path(context['output']), Path(context['resume']))
    if context.get('continuation') in ('b-u2924-150mb','u5996-overnight-20261029'):
        if context['continuation']=='u5996-overnight-20261029':
            from tank_game.laika_60hz.training import overnight as bound
        else:
            from tank_game.laika_60hz.training import b_extension as bound
        bound.profile(context)
        sys.argv[sys.argv.index('--steps')+1] = str(context['max_updates']*4928)
    ppo.main()
