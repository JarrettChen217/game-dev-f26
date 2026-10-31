"""CPU PPO adapters and bounded execution. No Torch import until explicitly used."""
import copy
import math
import shutil
import time
from pathlib import Path

import gymnasium as gym
import numpy as np

from tank_game.learning.environment import TankDuelEnv
from tank_game.learning.evaluation import episode_from_condition
from tank_game.learning.ppo_protocol import ROOT


class RunInterrupted(RuntimeError):
    """An incomplete run; never a fabricated game outcome."""


class ScopeComplete(Exception):
    """Stop only after an entire rollout has actually been updated."""


def read_resources():
    memory = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                  if line.startswith('MemAvailable:'))
    return {'memory': memory, 'disk': shutil.disk_usage(ROOT).free}


class Budget:
    def __init__(self, transition_limit, deadline, *, clock=time.monotonic, resources=read_resources):
        self.transition_limit = transition_limit
        self.deadline = deadline
        self.clock = clock
        self.resources = resources

    def check(self, sampled):
        if type(sampled) is not int or sampled > self.transition_limit:
            raise RunInterrupted('step-budget')
        if self.clock() >= self.deadline:
            raise RunInterrupted('wall-budget')
        resource = self.resources()
        if resource['memory'] < 8 * 1024**3 or resource['disk'] < 10 * 1024**3:
            raise RunInterrupted('resource-budget')


class ScheduledDuelEnv(gym.Wrapper):
    """Private train-only reset schedule; the factory seed is authoritative.

    SB3's reset seed is deliberately not used to replace the SeedSequence worker
    schedule. The underlying original environment still receives its worker seed.
    """
    def __init__(self, manifest, seed, rank, *, external_tick_limit=None,safety_arm=None):
        episodes = tuple(episode_from_condition(manifest, c) for c in manifest['splits']['train'])
        super().__init__(TankDuelEnv(episodes, opponent='simple', external_tick_limit=external_tick_limit,safety_arm=safety_arm))
        self.worker_seed = int(np.random.SeedSequence([seed, rank]).generate_state(1)[0])
        self.schedule_rng = np.random.default_rng(self.worker_seed)
        self.parity = int(self.schedule_rng.integers(2))
        self.episode_count = 0
        self.first_reset = True
        self.episode_return = 0.0
        self.episode_steps = 0

    def get_schedule_state(self):
        return {'worker_seed': self.worker_seed, 'rng': copy.deepcopy(self.schedule_rng.bit_generator.state),
                'parity': self.parity, 'episode_count': self.episode_count}

    def restore_schedule_state(self, state):
        if (state['worker_seed'] != self.worker_seed or type(state['episode_count']) is not int
                or state['episode_count'] < 0 or state['parity'] not in (0, 1)):
            raise ValueError('incompatible reset schedule')
        self.schedule_rng.bit_generator.state = copy.deepcopy(state['rng'])
        self.parity = state['parity']
        self.episode_count = state['episode_count']
        self.first_reset = True

    def _check(self,observation, reward, info):
        if observation.shape != self.observation_space.shape or observation.dtype != np.float32 or not np.isfinite(observation).all():
            raise RunInterrupted('nonfinite-or-incompatible-observation')
        if not math.isfinite(reward):
            raise RunInterrupted('nonfinite-reward')
        if any(info.get(k, 0) for k in ('invalid_actions', 'failed_decisions', 'rejected_decisions', 'disabled_worker')):
            raise RunInterrupted('opponent-or-action-fault')

    def reset(self, *, seed=None, options=None):
        if options:
            raise ValueError('training reset options are owned by the schedule')
        index = int(self.schedule_rng.integers(len(self.env.episodes)))
        learner = ('tank-1', 'tank-2')[(self.parity + self.episode_count) % 2]
        observation, info = self.env.reset(seed=self.worker_seed if self.first_reset else None,
                                           options={'episode_index': index, 'learner_id': learner})
        self.first_reset = False
        self.episode_count += 1
        self.episode_return = 0.0
        self.episode_steps = 0
        self._check(observation, 0.0, info)
        return observation, info

    def step(self, action):
        if isinstance(action, np.integer):
            action = int(action)
        if type(action) is not int or not 0 <= action < 18:
            raise ValueError('strict discrete action required')
        obs, reward, terminated, truncated, info = self.env.step(action)
        self._check(obs, reward, info)
        self.episode_return += reward
        self.episode_steps += 1
        if terminated or truncated:
            info['episode'] = {'r': self.episode_return, 'l': self.episode_steps}
        return obs, reward, terminated, truncated, info


def make_training_env(manifest, protocol, seed, *, external_tick_limit=None):
    from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv
    factories = [lambda rank=rank: ScheduledDuelEnv(manifest, seed, rank,
                external_tick_limit=external_tick_limit,
                safety_arm=protocol['contracts'].get('safety_profile',{}).get('arm'))
                for rank in range(protocol['n_envs'])]
    if protocol['backend'] == 'sequential':
        return DummyVecEnv(factories)
    return SubprocVecEnv(factories, start_method='spawn')


def count_submitted_steps(env, counter):
    from stable_baselines3.common.vec_env import VecEnvWrapper
    class CountedEnv(VecEnvWrapper):
        def reset(self):
            return self.venv.reset()

        def step_async(self, actions):
            try:
                counter.submit()
            except ValueError as error:
                raise RunInterrupted('step-budget;no-extra-vector-batch') from error
            self.venv.step_async(actions)

        def step_wait(self):
            result=self.venv.step_wait()
            counter.receive()
            return result
    return CountedEnv(env)


_MODEL_CLASS = None


def model_class():
    global _MODEL_CLASS
    if _MODEL_CLASS is not None:
        return _MODEL_CLASS
    import torch
    from stable_baselines3 import PPO

    class AuditedPPO(PPO):
        def train(self):
            if not self.rollout_buffer.full:
                raise RunInterrupted('partial-rollout')
            budget = getattr(self, '_budget', None)
            if budget:
                budget.check(int(self.num_timesteps))
            super().train()  # Stock PPO losses/updates; hooks only check and account.
            for parameter in self.policy.parameters():
                if not torch.isfinite(parameter).all() or (parameter.grad is not None
                        and not torch.isfinite(parameter.grad).all()):
                    raise RunInterrupted('nonfinite-parameter-or-gradient')
            names = ('train/loss', 'train/entropy_loss', 'train/policy_gradient_loss',
                     'train/value_loss', 'train/approx_kl')
            self.last_losses = {k: float(self.logger.name_to_value[k]) for k in names
                                if k in self.logger.name_to_value}
            if not self.last_losses or not all(math.isfinite(x) for x in self.last_losses.values()):
                raise RunInterrupted('nonfinite-loss')
            self.completed_updates = getattr(self, 'completed_updates', 0) + 1
            hook = getattr(self, '_on_update', None)
            if hook:
                hook(self)
            limit = getattr(self, '_scope_limit', None)
            if limit is not None and self.num_timesteps >= limit:
                raise ScopeComplete

        def _excluded_save_params(self):
            return super()._excluded_save_params() + ['_on_update', '_budget', '_scope_limit']

    _MODEL_CLASS = AuditedPPO
    return _MODEL_CLASS


def configure_cpu():
    import torch
    torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)


def build_model(env, protocol, seed, *, stop_after_updates=None):
    import torch
    configure_cpu()
    p = protocol['ppo']
    model = model_class()('MlpPolicy', env, seed=seed, device='cpu',
        learning_rate=lambda progress: p['learning_rate']['initial'] * progress,
        n_steps=p['n_steps_per_environment'], batch_size=p['batch_size'], n_epochs=p['n_epochs'],
        gamma=p['gamma'], gae_lambda=p['gae_lambda'], clip_range=p['clip_range'],
        clip_range_vf=p['clip_range_vf'], normalize_advantage=p['normalize_advantage'],
        ent_coef=p['ent_coef'], vf_coef=p['vf_coef'], max_grad_norm=p['max_grad_norm'],
        target_kl=p['target_kl'], use_sde=p['use_sde'],
        policy_kwargs={'net_arch': {'pi': protocol['network']['actor_hidden_sizes'],
                                   'vf': protocol['network']['critic_hidden_sizes']},
                       'activation_fn': torch.nn.Tanh, 'ortho_init': True,
                       'optimizer_class': torch.optim.Adam,
                       'optimizer_kwargs': {'eps': p['optimizer']['eps'],
                                            'betas': tuple(p['optimizer']['betas']),
                                            'weight_decay': p['optimizer']['weight_decay']}})
    if 'safety_profile' in protocol['contracts']:
        from tank_game.learning.safety_initialization import zero_safety_columns
        zero_safety_columns(model.policy)
    model.completed_updates = 0
    model.last_losses = {}
    model._scope_limit = None if stop_after_updates is None else stop_after_updates * 4096
    return model


def guard_callback(budget):
    from stable_baselines3.common.callbacks import BaseCallback

    class Guard(BaseCallback):
        def _on_step(self):
            budget.check(int(self.model.num_timesteps))
            if (int(self.model.num_timesteps) == budget.transition_limit
                    and self.model.rollout_buffer.pos+1 < self.model.n_steps):
                raise RunInterrupted('step-budget;discard-partial-rollout')
            if (not np.isfinite(self.locals['new_obs']).all()
                    or not np.isfinite(self.locals['rewards']).all()):
                raise RunInterrupted('nonfinite-rollout')
            for info in self.locals['infos']:
                if any(info.get(k, 0) for k in ('invalid_actions', 'failed_decisions',
                                               'rejected_decisions', 'disabled_worker')):
                    raise RunInterrupted('opponent-or-action-fault')
            return True
    return Guard()


def _atomic_json(path, value):
    import json
    import os
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    os.replace(temporary, path)


def _git(*args):
    import subprocess
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def _snapshot(expected=None):
    actual = _git('rev-parse', 'HEAD')
    if (expected is not None and actual != expected) or _git('status', '--porcelain'):
        raise ValueError('source snapshot dirty or changed; preserve and inspect')
    return actual


def _members(group):
    import os
    members = []
    for path in Path('/proc').glob('[0-9]*'):
        try:
            stat = (path/'stat').read_text().rsplit(') ', 1)[1].split()
            if path.stat().st_uid == os.getuid() and int(stat[2]) == group and stat[0] != 'Z':
                members.append(int(path.name))
        except (OSError, ValueError, IndexError):
            pass
    return members


def _stop_group(process):
    import os
    import signal
    # Give the learner time to record interruption/close VecEnv before signalling
    # every environment. All escalation stays within this Popen-owned session.
    for whole_group, sig, grace in ((False,signal.SIGTERM,10),
                                   (True,signal.SIGTERM,2),(True,signal.SIGKILL,2)):
        if not _members(process.pid):
            break
        try:
            if whole_group:
                os.killpg(process.pid, sig)
            else:
                os.kill(process.pid,sig)
        except ProcessLookupError:
            continue
        until = time.monotonic() + grace
        while _members(process.pid) and time.monotonic() < until:
            time.sleep(0.05)
    process.wait(timeout=5)


def run_owned(command, output_dir, *, deadline, resource_reader=read_resources,
              env=None, training_active_seconds=None):
    """External watchdog covers blocked Torch/VecEnv calls and only its new session."""
    import signal
    import subprocess
    import sys

    from tank_game.learning.ppo_protocol import read_json
    if not sys.platform.startswith('linux'):
        raise RuntimeError('owned-process supervision requires Linux /proc')
    output_dir = Path(output_dir)
    start = time.monotonic()
    reason = None
    samples = []
    last_sample = -math.inf
    def interrupt(signum, frame):
        raise KeyboardInterrupt(f'explicit signal {signum}')
    previous={sig:signal.signal(sig,interrupt) for sig in (signal.SIGTERM,signal.SIGHUP)}
    with (output_dir/'worker.log').open('x') as log:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, start_new_session=True)
        try:
            while child.poll() is None:
                now = time.monotonic()
                resource = resource_reader()
                if now-last_sample >= 1:
                    samples.append({'elapsed_seconds': now-start, **resource,
                                    **_telemetry(child.pid)})
                    last_sample = now
                if resource['memory'] < 8*1024**3 or resource['disk'] < 10*1024**3:
                    reason = 'resource-budget'
                if now >= deadline:
                    reason = 'wall-budget'
                progress_path = output_dir/'progress.json'
                progress = read_json(progress_path) if progress_path.exists() else {}
                done = min(max(float(progress.get('evaluation_seconds', 0)), 0), now-start)
                current = 0.0
                if progress.get('phase') == 'evaluation':
                    current = min(max(now-float(progress['evaluation_started_monotonic']), 0), now-start)
                    if float(progress['evaluation_spent_before']) + current >= float(progress['evaluation_active_limit']):
                        reason = 'evaluation-wall-budget'
                if training_active_seconds is not None and now-start-done-current >= training_active_seconds:
                    reason = 'wall-budget'
                if reason:
                    break
                time.sleep(0.1)
        except KeyboardInterrupt:
            reason = 'manual-interruption'
        finally:
            if child.poll() is None or _members(child.pid):
                _stop_group(child)
            else:
                child.wait(timeout=5)
            for sig, handler in previous.items():
                signal.signal(sig,handler)
    result = {'status': 'complete' if reason is None and child.returncode == 0 else 'incomplete',
              'stop_reason': reason or (f'worker-exit-{child.returncode}' if child.returncode else None),
              'returncode': child.returncode, 'owned_group': child.pid,
              'remaining_owned_pids': _members(child.pid), 'supervisor_seconds': time.monotonic()-start}
    result['resource_samples'] = samples
    if result['remaining_owned_pids']:
        result['status'] = 'incomplete'
        result['stop_reason'] = 'cleanup-failed'
    return result


def _telemetry(group):
    """Observation only: group RSS sums shared pages; thermal data never stops a run."""
    rss = 0
    cpu_ticks = 0
    for pid in _members(group):
        try:
            stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            cpu_ticks += int(stat[11])+int(stat[12])
            rss += next(int(x.split()[1])*1024 for x in Path(f'/proc/{pid}/status').read_text().splitlines()
                        if x.startswith('VmRSS:'))
        except (OSError, ValueError, StopIteration):
            continue
    thermal = {}
    for path in Path('/sys/class/thermal').glob('thermal_zone*/temp'):
        try:
            thermal[path.parent.name] = int(path.read_text())/1000
        except (OSError, ValueError):
            continue
    return {'owned_rss_bytes_sum': rss, 'owned_cpu_ticks': cpu_ticks,
            'load_average': Path('/proc/loadavg').read_text().split()[:3], 'thermal_celsius': thermal}


class EvaluationLedger:
    """One explicit shared ledger for all seeds/checkpoints; a stale lock is not repaired."""
    def __init__(self, path, protocol):
        self.path = Path(path)
        self.protocol = protocol
        self.lock = self.path.with_suffix(self.path.suffix+'.lock')

    def __enter__(self):
        import os

        from tank_game.learning.ppo_protocol import read_json
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            self.value = read_json(self.path) if self.path.exists() else {
                'protocol_sha256': self.protocol['_runtime']['sha256'], 'spent_seconds': 0.0,
                'events': [], 'reserved_slots': [], 'reserved_trace_games': 0}
            spent = self.value['spent_seconds']
            if (self.value['protocol_sha256'] != self.protocol['_runtime']['sha256']
                    or type(spent) not in (int, float) or not math.isfinite(spent) or spent < 0):
                raise ValueError('incompatible evaluation ledger')
            if spent >= self.protocol['budgets']['evaluation_active_cutoff_seconds_all_seeds']:
                raise RunInterrupted('evaluation-wall-budget')
            self.start = time.monotonic()
            return self
        except BaseException:
            os.close(self.fd)
            self.lock.unlink()
            raise

    def reserve(self, seed, steps, split, trace, *, resume=False, output=None, model_sha256=None):
        key = f'{seed}:{steps}:{split}'
        self.slot=key
        slots=self.value.setdefault('slots',{})
        identity={'output':str(Path(output).resolve()) if output is not None else None,
                  'model_sha256':model_sha256,'trace':trace}
        if key in self.value['reserved_slots']:
            if (not resume or key not in slots or any(slots[key].get(k)!=v for k,v in identity.items())
                    or output is None or model_sha256 is None):
                raise ValueError('invalid or already attempted evaluation slot')
            return
        if (type(seed) is not int or seed not in self.protocol['seeds']
                or type(steps) is not int or steps < 0 or steps % 4096
                or split not in ('sanity', 'validation') or key in self.value['reserved_slots']):
            raise ValueError('invalid or already attempted evaluation slot')
        if trace and (split != 'validation' or steps != self.protocol['budgets']['per_seed_transitions']
                or self.value['reserved_trace_games']+4 > 12):
            raise ValueError('trace reservation exceeds frozen final-game scope')
        self.value['reserved_slots'].append(key)
        slots[key]=identity|{'complete':False}
        self.value['reserved_trace_games'] += 4 if trace else 0
        # Persist before playing: interruption cannot make mandatory games retryable.
        _atomic_json(self.path, self.value)

    def complete(self, report_path):
        from tank_game.learning.ppo_protocol import file_digest
        self.value['slots'][self.slot].update(complete=True,report_sha256=file_digest(report_path))
        _atomic_json(self.path,self.value)

    @property
    def deadline(self):
        return self.start + self.protocol['budgets']['evaluation_active_cutoff_seconds_all_seeds'] - self.value['spent_seconds']

    def __exit__(self, kind, value, traceback):
        import os
        try:
            elapsed = time.monotonic()-self.start
            self.value['spent_seconds'] += elapsed
            self.value['events'].append({'seconds': elapsed, 'complete': kind is None})
            _atomic_json(self.path, self.value)
        finally:
            os.close(self.fd)
            self.lock.unlink()


def _evaluate_inline(checkpoint, manifest, output_dir, protocol, *, split, trace,
                     budget_path, progress=None, resume=False):
    from tank_game.learning.evaluation import run_readiness_manifest
    from tank_game.learning.ppo_checkpoint import (
        _restore_rng,
        _rng_state,
        _validate,
        checkpoint_expectations,
        load_predictor,
    )
    from tank_game.learning.ppo_protocol import file_digest, read_json
    metadata=_validate(checkpoint,checkpoint_expectations(protocol))
    if resume and Path(budget_path).exists():
        ledger_value=read_json(budget_path)
        if ledger_value['protocol_sha256']!=protocol['_runtime']['sha256']:
            raise ValueError('incompatible evaluation ledger')
        key=f"{metadata['seed']}:{metadata['sampled_steps']}:{split}"
        slot=ledger_value.get('slots',{}).get(key,{})
        if slot.get('complete'):
            path=Path(slot['output'])/'report.json'
            if slot['model_sha256']!=metadata['model_sha256'] or file_digest(path)!=slot['report_sha256']:
                raise ValueError('completed evaluation identity mismatch')
            return read_json(path)
    saved_rng = _rng_state()
    try:
        with EvaluationLedger(budget_path, protocol) as ledger:
            if progress is not None:
                progress.update(phase='evaluation', evaluation_started_monotonic=ledger.start,
                                evaluation_spent_before=ledger.value['spent_seconds'],
                                evaluation_active_limit=protocol['budgets']['evaluation_active_cutoff_seconds_all_seeds'])
                _atomic_json(progress['path'], progress)
            predictor = load_predictor(checkpoint, checkpoint_expectations(protocol))
            ledger.reserve(predictor.metadata['seed'], predictor.metadata['sampled_steps'], split, trace,
                           resume=resume,output=output_dir,model_sha256=predictor.metadata['model_sha256'])
            def factory():
                def predict(observation):
                    Budget(0, ledger.deadline).check(0)
                    return predictor(observation)
                return predict
            report = run_readiness_manifest(manifest, output_dir, predictor_factory=factory,
                split=split, opponents=('simple',), trace=trace,
                trace_conditions=tuple(protocol['evaluation']['diagnostic_traces']['condition_ids']) if trace else None,
                predictor_version=protocol['evaluation']['predictor_identity'],
                predictor_metadata={'kind': 'learned-ppo', 'model_sha256': predictor.metadata['model_sha256'],
                                    'protocol_sha256': protocol['_runtime']['sha256']},
                resume=resume and Path(output_dir).exists())
            expected = 32 if split == 'validation' else 2*len(manifest['sanity'])
            report['complete'] = (len(report['games']) == expected
                and all(g.get('terminated') and not g.get('truncated') and not g.get('fault')
                        for g in report['games']) and report['aggregate']['faults'] == 0)
            _atomic_json(Path(output_dir)/'report.json', report)
            if not report['complete']:
                raise RunInterrupted('incomplete-mandatory-evaluation')
            ledger.complete(Path(output_dir)/'report.json')
            return report
    finally:
        if progress is not None and progress.get('phase') == 'evaluation':
            progress['evaluation_seconds'] += time.monotonic()-progress['evaluation_started_monotonic']
            progress['phase'] = 'training'
            _atomic_json(progress['path'], progress)
        _restore_rng(saved_rng)


def _scoped_environment(seed):
    import os
    runtime = ROOT.parent/'.tank-runtime'
    env = os.environ.copy()
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED=str(seed),
        OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', UV_PYTHON_DOWNLOADS='never',
        UV_PYTHON_INSTALL_BIN='false', UV_PYTHON_INSTALL_DIR=str(runtime/'python'),
        UV_CACHE_DIR=str(runtime/'cache/uv'), XDG_CACHE_HOME=str(runtime/'cache'),
        XDG_CONFIG_HOME=str(runtime/'config'), XDG_DATA_HOME=str(runtime/'data'), TMPDIR=str(runtime/'tmp'))
    return env


def _launch(request, output, *, wall_seconds, training_active=None):
    import sys

    from tank_game.learning.ppo_protocol import read_json
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output/'protocol.snapshot.json'
    shutil.copyfile(request['protocol_path'], snapshot)
    request['protocol_path'] = str(snapshot.resolve())
    request['output'] = str(output.resolve())
    request['started_monotonic'] = time.monotonic()
    _atomic_json(output/'request.json', request)
    result = run_owned([sys.executable, '-B', '-m', 'tank_game.learning.ppo_training',
                       '--worker', str((output/'request.json').resolve())], output,
                       deadline=request['started_monotonic']+wall_seconds-60,
                       training_active_seconds=training_active, env=_scoped_environment(request['seed']))
    result['supervisor_stop_reason']=result.get('stop_reason')
    if (output/'worker-result.json').exists():
        worker = read_json(output/'worker-result.json')
        result['worker'] = worker
        if worker['status'] != 'complete':
            result['status'] = 'incomplete'
            result['stop_reason'] = worker.get('stop_reason') or result['stop_reason']
    elif result['status'] == 'complete':
        result.update(status='incomplete', stop_reason='missing-worker-report')
    result.update(branch=request['branch'], revision=request['expected_revision'],
                  lock_sha256=request['lock_sha256'], protocol_sha256=request['protocol_sha256'])
    evaluation = result.get('worker', {}).get('evaluation_seconds', 0.0)
    result['accounted_evaluation_seconds'] = evaluation if request['kind']=='train' else result['supervisor_seconds']
    result['accounted_training_seconds'] = max(0, result['supervisor_seconds']-evaluation) if request['kind']=='train' else 0.0
    _snapshot(request['expected_revision'])
    _atomic_json(output/'result.json', result)
    return result


def train_run(protocol_path, manifest_path, output_dir, *, seed, mode, resume=None,
              expected_revision=None, evaluation_budget=None, experiment=None):
    from tank_game.learning.ppo_protocol import (
        file_digest,
        load_protocol,
        read_json,
        require_pilot_ready,
    )
    manifest = read_json(manifest_path)
    if mode=='hybrid-pilot':
        from tank_game.learning.hybrid_protocol import load_hybrid_protocol
        p=load_hybrid_protocol(protocol_path,manifest)
    elif mode=='safety-smoke':
        from tank_game.learning.safety_protocol import load_safety_protocol
        p=load_safety_protocol(protocol_path,manifest)
    else:
        p = load_protocol(protocol_path, manifest)
    if mode not in ('smoke', 'pilot', 'resume-check', 'recovery-check','safety-smoke','hybrid-pilot') or type(seed) is not int or seed not in p['seeds']:
        raise ValueError('unknown mode/seed')
    if mode == 'pilot':
        require_pilot_ready(p)
    if mode in ('pilot','recovery-check','safety-smoke','hybrid-pilot') and (experiment is None or 'recovery' not in p):
        raise ValueError('explicit experiment and recovery protocol required')
    if mode not in ('pilot','recovery-check','safety-smoke','hybrid-pilot') and (mode == 'resume-check') != (resume is not None):
        raise ValueError('resume-check alone requires a checkpoint')
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(output)
    head = _snapshot(expected_revision)
    request = {'kind': 'train', 'mode': mode, 'seed': seed, 'protocol_path': str(Path(protocol_path).resolve()),
        'manifest_path': str(Path(manifest_path).resolve()), 'expected_revision': head,
        'branch': _git('branch', '--show-current'), 'lock_sha256': file_digest(ROOT/'uv.lock'),
        'protocol_sha256': p['_runtime']['sha256'], 'resume': str(Path(resume).resolve()) if resume else None,
        'evaluation_budget': str(Path(evaluation_budget).resolve()) if evaluation_budget else None}
    if mode in ('pilot','recovery-check','safety-smoke','hybrid-pilot'):
        from tank_game.learning.ppo_recovery import Experiment
        with Experiment(experiment,p,mode=mode,lock_sha256=request['lock_sha256']) as journal:
            if evaluation_budget is not None and Path(evaluation_budget).resolve()!=journal.budget_path:
                raise ValueError('cannot replace the experiment shared evaluation budget')
            continuation=journal.begin(seed,output,resume)
            request.update(recovery=continuation,evaluation_budget=str(journal.budget_path))
            remaining=continuation['remaining_training_seconds']
            evaluation_remaining=0
            if mode=='pilot':
                spent=read_json(journal.budget_path)['spent_seconds'] if journal.budget_path.exists() else 0
                evaluation_remaining=max(0,p['budgets']['evaluation_wall_seconds_all_seeds']-spent)
            started=time.monotonic()
            try:
                result=_launch(request,output,wall_seconds=remaining+evaluation_remaining,
                               training_active=remaining-60)
            except BaseException:
                journal.finish(seed,continuation,{'status':'incomplete','stop_reason':'supervisor-accounting-unconfirmed',
                    'accounted_training_seconds':time.monotonic()-started},journal.latest_checkpoint(seed))
                raise
            journal.finish(seed,continuation,result,journal.latest_checkpoint(seed))
            result['experiment_state']=copy.deepcopy(journal.value['seeds'][str(seed)])
            result['experiment_id']=journal.value['experiment_id']
            _atomic_json(output/'result.json',result)
            return result
    wall = 900 if mode != 'pilot' else p['budgets']['training_wall_seconds_per_seed']
    return _launch(request, output, wall_seconds=wall + (p['budgets']['evaluation_wall_seconds_all_seeds']
        if mode == 'pilot' else 0), training_active=wall-60)


def evaluate_checkpoint(checkpoint, manifest, output_dir, *, split='validation', trace=False,
                        protocol_path=None, budget_path=None, expected_revision=None):
    from tank_game.learning.ppo_protocol import file_digest, load_protocol, require_pilot_ready
    if split not in ('sanity', 'validation'):
        raise ValueError('holdout evaluation is forbidden')
    if protocol_path is None or budget_path is None:
        raise ValueError('explicit protocol and shared evaluation ledger required')
    p = load_protocol(protocol_path, manifest)
    if p['freeze_stage'] == 'pilot-frozen':
        require_pilot_ready(p)
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(output)
    head = _snapshot(expected_revision)
    # The manifest is always the exact frozen file already checked by load_protocol.
    request = {'kind': 'evaluate', 'mode': 'evaluation', 'seed': 11, 'split': split, 'trace': trace,
        'checkpoint': str(Path(checkpoint).resolve()), 'protocol_path': str(Path(protocol_path).resolve()),
        'manifest_path': str((ROOT/p['manifest_path']).resolve()), 'expected_revision': head,
        'branch': _git('branch', '--show-current'), 'lock_sha256': file_digest(ROOT/'uv.lock'),
        'protocol_sha256': p['_runtime']['sha256'], 'evaluation_budget': str(Path(budget_path).resolve())}
    return _launch(request, output, wall_seconds=p['budgets']['evaluation_wall_seconds_all_seeds'])



def _model_state_summary(model):
    import hashlib
    h=hashlib.sha256()
    for key,value in sorted(model.policy.state_dict().items()):
        h.update(key.encode());h.update(value.detach().cpu().numpy().tobytes())
    steps=[float(state['step']) for state in model.policy.optimizer.state.values() if 'step' in state]
    return {'policy_weights_sha256':h.hexdigest(),'model_steps':int(model.num_timesteps),
            'completed_updates':int(model.completed_updates),'optimizer_step_min':min(steps,default=0.),
            'optimizer_step_max':max(steps,default=0.),'n_updates':int(model._n_updates),
            'schedule_progress':float(model._current_progress_remaining),
            'learning_rate':float(model.policy.optimizer.param_groups[0]['lr'])}


def _step0_roundtrip(checkpoint,expected,probe):
    from tank_game.learning.ppo_checkpoint import _restore_rng, _rng_state, load_predictor
    state=_rng_state()
    try:
        return load_predictor(checkpoint,expected)(probe)
    finally:
        _restore_rng(state)


def _worker(request_path):
    import json
    import signal
    import traceback
    def interrupt(signum, frame):
        raise KeyboardInterrupt(f'explicit signal {signum}')
    for sig in (signal.SIGTERM,signal.SIGHUP):
        signal.signal(sig,interrupt)

    from tank_game.episodes import create_world
    from tank_game.learning.ppo_checkpoint import (
        checkpoint_expectations,
        load_for_resume,
        load_predictor,
        save_checkpoint,
    )
    from tank_game.learning.ppo_protocol import (
        file_digest,
        load_protocol,
        read_json,
        require_pilot_ready,
    )
    from tank_game.learning.safety_protocol import make_observation_encoder
    request = read_json(request_path)
    output = Path(request['output'])
    env = None
    model = None
    sampling_counter = None
    progress = {'path': str(output/'progress.json'), 'phase': 'training', 'evaluation_seconds': 0.0}
    report = {'status': 'incomplete', 'stop_reason': None, 'checkpoints': [],
              'sampled_steps': request.get('recovery',{}).get('initial_steps',0)}
    def persist():
        report['evaluation_seconds'] = progress['evaluation_seconds']
        report['training_seconds'] = time.monotonic()-request['started_monotonic']-progress['evaluation_seconds']
        if request['kind']=='qualify-hybrid' and (output/'qualification.json').exists():
            report['qualification_sha256']=file_digest(output/'qualification.json')
        _atomic_json(output/'worker-result.json', report)
    try:
        _snapshot(request['expected_revision'])
        manifest = read_json(request['manifest_path'])
        hybrid=request['mode']=='hybrid-pilot' or request['kind'] in ('evaluate-hybrid','qualify-hybrid')
        safety=hybrid or request['mode']=='safety-smoke' or request['kind']=='evaluate-safety'
        if hybrid:
            from tank_game.learning.hybrid_protocol import load_hybrid_protocol
            p=load_hybrid_protocol(request['protocol_path'],manifest)
        elif safety:
            from tank_game.learning.safety_protocol import load_safety_protocol
            p=load_safety_protocol(request['protocol_path'],manifest)
        else:
            p = load_protocol(request['protocol_path'], manifest)
        configure_cpu()
        if request['kind']=='qualify-hybrid':
            from tank_game.learning.hybrid_evaluation import run_hybrid_qualification
            run_hybrid_qualification(request,manifest,p)
            report['status']='complete'
            return
        if request['kind']=='evaluate-hybrid':
            from tank_game.learning.hybrid_evaluation import run_hybrid_games
            run_hybrid_games(request,manifest,p,progress=progress)
            report['status']='complete'
            return
        if request['kind']=='evaluate-safety':
            from tank_game.learning.safety_evaluation import run_controller_games
            run_controller_games(request['checkpoint'],manifest,output/'games',p,
                                 budget_path=request['evaluation_budget'],progress=progress)
            report['status']='complete'
            return
        if request['kind'] == 'evaluate':
            _evaluate_inline(request['checkpoint'], manifest, output/'games', p,
                split=request['split'], trace=request['trace'], budget_path=request['evaluation_budget'], progress=progress)
            report['status'] = 'complete'
            return
        if request['mode'] == 'pilot':
            require_pilot_ready(p)
        continuation=request.get('recovery')
        wall = (continuation['remaining_training_seconds'] if continuation else
                900 if request['mode'] != 'pilot' else p['budgets']['training_wall_seconds_per_seed'])
        step_limit=continuation['model_step_limit'] if continuation else p['budgets']['per_seed_transitions']
        budget = Budget(step_limit, request['started_monotonic']+wall-60)
        env = make_training_env(manifest, p, request['seed'])
        expected = checkpoint_expectations(p)
        if request['resume']:
            model, previous = load_for_resume(request['resume'], expected, cls=model_class())
            if previous['seed'] != request['seed']:
                raise ValueError('resume seed mismatch')
            states = previous.get('environment_schedule_states', [])
            for rank, state in enumerate(states):
                env.env_method('restore_schedule_state', state, indices=rank)
            model._scope_limit = (8192 if request['mode']=='recovery-check' else
                                  None if request['mode']=='pilot' else int(model.num_timesteps)+4096)
            report['checkpoints']=[request['resume']]
            report['last_complete_steps']=int(model.num_timesteps)
        else:
            model = build_model(env, p, request['seed'], stop_after_updates=(4 if request['mode']=='smoke' else
                                2 if request['mode']=='recovery-check' else None))
        initial_steps = int(model.num_timesteps)
        if safety:
            from tank_game.learning.safety_protocol import safety_training_target
            if hybrid:
                from tank_game.learning.hybrid_protocol import hybrid_training_target
                target=hybrid_training_target(p,initial_steps)
            else:
                target=safety_training_target(p,initial_steps)
            if step_limit<target:raise RunInterrupted('insufficient-cumulative-sampling-budget')
            model._scope_limit=target
        report['initial_steps'] = initial_steps
        from tank_game.learning.ppo_recovery import SamplingCounter
        sampling_counter=SamplingCounter(initial_steps,step_limit,p['n_envs'])
        env=count_submitted_steps(env,sampling_counter)
        model.set_env(env,force_reset=True)
        initial_weights = {k: v.detach().clone() for k, v in model.policy.state_dict().items()}
        if safety:
            report['starting_state']=_model_state_summary(model)
        model._budget = budget
        def save(updated, reason):
            _snapshot(request['expected_revision'])
            path = output/f'checkpoint-{updated.num_timesteps:09d}'
            probe_world = create_world(episode_from_condition(manifest, manifest['splits']['train'][0]))
            probe = make_observation_encoder(p).encode(probe_world.observe('tank-1'))
            metadata = expected | {'seed': request['seed'], 'save_reason': reason,
                'run_mode': request['mode'], 'implementation_revision': request['expected_revision'],
                'lock_sha256': request['lock_sha256'], 'prediction_observations': probe,
                'environment_schedule_states': env.env_method('get_schedule_state')}
            if continuation:
                metadata.update(experiment_id=continuation['experiment_id'],
                                experiment_path=continuation['experiment'],attempt_index=continuation['attempt_index'])
            if safety:metadata['model_state_summary']=_model_state_summary(updated)
            save_checkpoint(updated, path, metadata)
            report['checkpoints'].append(str(path))
            report['last_complete_steps'] = int(updated.num_timesteps)
            if hybrid:
                report.setdefault('checkpoint_metadata_sha256',{})[str(path)]=file_digest(path/'metadata.json')
            return path
        def evaluate(path, final):
            before = time.monotonic()
            try:
                evaluation_output=(Path(continuation['experiment'])/'evaluations'/
                    f"seed-{request['seed']}-step-{model.num_timesteps:09d}" if continuation else
                    output/f'evaluation-{model.num_timesteps:09d}')
                _evaluate_inline(path, manifest, evaluation_output, p,
                    split='validation', trace=final, budget_path=request['evaluation_budget'], progress=progress,
                    resume=bool(request['resume']))
            finally:
                budget.deadline += time.monotonic()-before
        if not request['resume']:
            zero = save(model, request['mode']+'-step0')
            if safety:
                probe_world=create_world(episode_from_condition(manifest,manifest['splits']['train'][0]))
                probe=make_observation_encoder(p).encode(probe_world.observe('tank-1'))
                _step0_roundtrip(zero,expected,probe)
                report['step0_prediction_roundtrip']=True
            if request['mode'] == 'pilot':
                evaluate(zero, False)
        elif request['mode']=='pilot' and initial_steps in p['evaluation']['checkpoint_aggregate_transitions']:
            evaluate(Path(request['resume']), initial_steps==p['budgets']['per_seed_transitions'])
        def on_update(updated):
            budget.check(int(updated.num_timesteps))
            checkpoint = save(updated, request['mode']+'-complete-update')
            if request['mode']=='pilot' and updated.num_timesteps in p['evaluation']['checkpoint_aggregate_transitions']:
                evaluate(checkpoint, updated.num_timesteps==p['budgets']['per_seed_transitions'])
        model._on_update = on_update
        target = (target if safety else 8192 if request['mode']=='recovery-check' else initial_steps+4096 if request['mode']=='resume-check' else
                  16384 if request['mode']=='smoke' else p['budgets']['per_seed_transitions'])
        try:
            if initial_steps<target:
                model.learn(total_timesteps=p['ppo']['learning_rate'].get('horizon_transitions',p['budgets']['per_seed_transitions'])-initial_steps,
                        reset_num_timesteps=not bool(request['resume']), callback=guard_callback(budget))
        except ScopeComplete:
            pass
        if model.num_timesteps != target or report.get('last_complete_steps') != target:
            raise RunInterrupted('missing-planned-endpoint')
        budget.check(int(model.num_timesteps))
        predictor = load_predictor(report['checkpoints'][-1], expected)
        probe_world = create_world(episode_from_condition(manifest, manifest['splits']['train'][0]))
        probe = make_observation_encoder(p).encode(probe_world.observe('tank-1'))
        predictor(probe)
        import torch
        changed = any(not torch.equal(initial_weights[k], v) for k, v in model.policy.state_dict().items())
        if not changed and int(model.num_timesteps)>initial_steps:
            raise RunInterrupted('weights-did-not-change')
        report.update(status='complete', sampled_steps=int(model.num_timesteps),
            updated_steps=int(model.num_timesteps)-initial_steps,
            complete_rollout_updates=(int(model.num_timesteps)-initial_steps)//4096,
            weights_changed=changed, losses=model.last_losses, prediction_roundtrip=True)
        if safety:
            report['ending_state']=_model_state_summary(model)
            if not hybrid and target==4096:
                report.update(status='incomplete',stop_reason='planned-checkpoint-boundary-pause')
    except BaseException as error:  # noqa: BLE001 -- preserve incomplete worker result; supervisor owns cleanup
        report.update(status='incomplete', stop_reason=f'{type(error).__name__}: {error}',
                      traceback=traceback.format_exc())
        if model is not None:
            report['sampled_steps'] = int(model.num_timesteps)
    finally:
        # IPC close can block after an interrupted step_wait consumed some replies.
        # Save confirmed accounting first; the supervisor charges/reaps cleanup.
        report['cleanup_pending']=env is not None
        if sampling_counter is not None:
            report.update(sampled_steps=sampling_counter.charged_steps,
                submitted_decisions=sampling_counter.submitted,returned_decisions=sampling_counter.returned,
                pending_batch_steps=sampling_counter.submitted-sampling_counter.returned,
                model_steps=int(model.num_timesteps),
                sampling_accounting='submitted-batches;pending-batch-conservatively-charged')
        persist()
        if env is not None:
            try:
                env.close()
                report['vector_closed'] = True
            except BaseException as error:  # noqa: BLE001 -- preserve cleanup signals; supervisor reaps group
                report.update(status='incomplete', cleanup_error=f'{type(error).__name__}: {error}')
        report['cleanup_pending']=env is not None and not report.get('vector_closed',False)
        persist()
        print(json.dumps({'status': report['status'], 'stop_reason': report['stop_reason']}), flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    _worker(parser.parse_args().worker)
