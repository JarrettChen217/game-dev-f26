"""Two bounded processes around retained Python PPO; no replacement optimizer.

Imports Torch only in an explicitly launched CUDA phase. Fresh60Hz engineering,
not ordinary resume of a25Hz checkpoint, strength evaluation or convergence.
"""
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    os.replace(temporary, path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def phase_arguments(context, output, phase):
    if phase not in (1, 2):
        raise ValueError('only the two frozen engineering phases exist')
    args = ['source60-ppo', '--steps', '4928', '--envs', '16', '--seed', '77',
            '--critic-warmup-updates', '1', '--mix', '1', '0', '0', '--threads', '1',
            '--device', 'cuda', '--timing-profile', '--schedule-steps', '480000000',
            '--save-every', '0', '--research-context', str(context),
            '--output', str(output/f'phase{phase}-run')]
    if phase == 2:
        args += ['--resume', str(output/'checkpoint/resume.pt')]
    return args


def ResearchHook(context_path):
    """Original serializer/checkpoint convention, with source60 contract checks."""
    import numpy as np
    import torch

    from tank_game.laika_60hz.training.contract import contract_digest, validate_resume_metadata

    class Hook:
        def __init__(self):
            self.context = json.loads(Path(context_path).read_text())
            self.output = Path(self.context['output'])
            self.output.mkdir(parents=True, exist_ok=True)
            self.phase = self.context['phase']
            self.optimizer_calls = 0
            self.restored = None
            self.initial = None
            if self.context['environment_contract_sha256'] != contract_digest():
                raise ValueError('native/source60 environment contract mismatch')

        def check_budget(self, reserve=0):
            if time.time() >= self.context['deadline_unix']:
                raise SystemExit(74)
            root = Path(self.context['storage_root'])
            used = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
            if used+reserve > 16*1024**2 or shutil.disk_usage(root).free < 10*1024**3:
                raise RuntimeError('source60 output/free-disk budget exceeded')

        def restore(self, payload):
            if payload is None:
                if self.phase != 1:
                    raise ValueError('phase2 requires a complete phase1 checkpoint')
                return 0, 0
            state = payload['research']
            validate_resume_metadata(state)
            if (self.phase != 2 or state['protocol_sha256'] != self.context['protocol_sha256']
                    or state['source_head'] != self.context['source_head']
                    or state['update'] != 1 or state['warmup_completed'] != 1
                    or payload['trained_steps'] != 4928 or payload['schedule_steps'] != 480000000):
                raise ValueError('foreign or incomplete engineering checkpoint')
            torch.set_rng_state(state['torch_rng'].cpu())
            np.random.set_state(state['numpy_rng'])
            torch.cuda.set_rng_state_all([v.cpu() for v in state['cuda_rng']])
            self.restored = payload
            return 1, 1

        def before_rollout(self, batch):
            if batch != 4928:
                raise ValueError('foreign rollout size')
            self.check_budget(3500000)

        def before_optimizer_step(self):
            self.check_budget()
            self.optimizer_calls += 1
            if self.optimizer_calls > 32:
                raise RuntimeError('more than one PPO update in this phase')

        def metric(self, record):
            return record

        def publish(self, model, optimiser, config, model_steps, update, warmup_completed,
                    save_live, save_resume, started, schedule_steps):
            self.check_budget(3500000)
            assert schedule_steps == 480000000
            assert sum(p.numel() for p in model.parameters()) == 261758
            state = model.state_dict()
            assert all(torch.isfinite(v).all() for v in state.values())
            assert all(not torch.is_tensor(v) or torch.isfinite(v).all()
                       for group in optimiser.state.values() for v in group.values())

            def fingerprint(prefix):
                h = hashlib.sha256()
                for key, value in state.items():
                    if key.startswith(prefix):
                        h.update(key.encode()); h.update(value.detach().cpu().numpy().tobytes())
                return h.hexdigest()

            current = {key: fingerprint(key) for key in ('actor.', 'critic.')}
            initial_publish = update == self.phase-1
            if initial_publish:
                self.initial = current
                if self.phase == 2:
                    def equal(a, b):
                        if torch.is_tensor(a):
                            return torch.equal(a.cpu(), b.cpu())
                        if isinstance(a, np.ndarray):
                            return np.array_equal(a, b)
                        if isinstance(a, dict):
                            return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
                        if isinstance(a, (list, tuple)):
                            return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b, strict=True))
                        return a == b
                    saved = self.restored
                    checks = {'model': equal(state, saved['model']),
                              'adam': equal(optimiser.state_dict(), saved['optimiser']),
                              'torch_rng': equal(torch.get_rng_state(), saved['research']['torch_rng']),
                              'numpy_rng': equal(np.random.get_state(), saved['research']['numpy_rng']),
                              'cuda_rng': equal(torch.cuda.get_rng_state_all(), saved['research']['cuda_rng']),
                              'trained_steps': model_steps == 4928, 'warmup': warmup_completed == 1,
                              'schedule': schedule_steps == 480000000,
                              'environment_contract': True, 'protocol_and_source': True}
                    if not all(checks.values()):
                        raise ValueError('new-process full-state restore mismatch: '+str(checks))
                    atomic_json(self.output.parent/'restore-proof.json',
                                {'checks': checks, 'pid': os.getpid(), 'before_next_rollout': True,
                                 'native_episodes': 'fresh; not tick-exact'})
            else:
                assert update == self.phase and model_steps == self.phase*4928
                assert warmup_completed == 1 and self.optimizer_calls == 32
                assert current['critic.'] != self.initial['critic.']
                assert (current['actor.'] != self.initial['actor.']) == (self.phase == 2)
                monitor = model.engineering_monitor
                assert monitor['forward_calls'] > 0 and monitor['device'] == 'cuda:0'
                assert monitor['critic_nonzero_gradients'] > 0
                assert (monitor['actor_nonzero_gradients'] > 0) == (self.phase == 2)

            metadata = {'protocol_sha256': self.context['protocol_sha256'],
                        'environment_contract_sha256': contract_digest(),
                        'source_head': self.context['source_head'], 'update': update,
                        'warmup_completed': warmup_completed, 'torch_rng': torch.get_rng_state(),
                        'numpy_rng': np.random.get_state(), 'cuda_rng': torch.cuda.get_rng_state_all()}
            save_live(self.output, model, config, model_steps, update, started, model_steps, schedule_steps)
            live = json.loads((self.output/'live.json').read_text())
            live.update(profile='source60-schema24-prep-v1', environment_contract_sha256=contract_digest())
            atomic_json(self.output/'live.json', live)
            save_resume(self.output, model, optimiser, model_steps, schedule_steps, research=metadata)
            marker = {'complete': True, 'schema': 24, 'arch': 'hybrid_schema24_reconstructed_v1',
                      'update': update, 'model_steps': model_steps, 'warmup_completed': warmup_completed,
                      'environment_contract_sha256': contract_digest(),
                      'files': {f: digest(self.output/f) for f in ('live.pt', 'live.json', 'resume.pt')}}
            atomic_json(self.output/'checkpoint.json', marker)
            if update == 0:
                initial = self.output/'initial'
                initial.mkdir(exist_ok=False)
                for name in ('live.pt', 'live.json', 'resume.pt', 'checkpoint.json'):
                    shutil.copy2(self.output/name, initial/name)
            if not initial_publish:
                atomic_json(self.output.parent/f'phase{self.phase}-proof.json',
                            {'phase': self.phase, 'pid': os.getpid(), 'update': update,
                             'model_steps': model_steps, 'warmup_completed': warmup_completed,
                             'critic_only': self.phase == 1, 'optimizer_steps': self.optimizer_calls,
                             'before': self.initial, 'after': current,
                             'monitor': model.engineering_monitor, 'checkpoint': marker})
                raise SystemExit(75)  # deliberate process boundary, no third update/final duplicate

    return Hook()


def phase_main(context_path, phase):
    import numpy as np
    import torch

    from tank_game.laika_60hz.training import ppo

    context = json.loads(Path(context_path).read_text())
    if context['phase'] != phase or not torch.cuda.is_available():
        raise RuntimeError('explicit CUDA phase/availability mismatch')
    torch.set_num_threads(1)
    # A real reference GAE regression, no environment steps or optimization.
    returns = ppo.compute_advantages(np.array([[1., 0.]], np.float32),
        np.array([[5., 2.]], np.float32), np.array([[True, False]]), np.array([999., 3.]), .9, .95)
    np.testing.assert_allclose(returns+np.array([[5., 2.]]), [[1., 2.7]], atol=1e-6)
    original = ppo.ActorCritic

    class AuditedActorCritic(original):
        def __init__(self):
            super().__init__()
            self.engineering_monitor = {'forward_calls': 0, 'finite_gradient_tensors': 0,
                                       'actor_nonzero_gradients': 0, 'critic_nonzero_gradients': 0}
            self.register_forward_hook(self.check_forward)
            for name, parameter in self.named_parameters():
                parameter.register_hook(lambda gradient, name=name: self.check_gradient(name, gradient))

        def check_forward(self, _module, _input, output):
            if not all(torch.isfinite(v).all() for v in output):
                raise FloatingPointError('nonfinite source60 forward')
            self.engineering_monitor['forward_calls'] += 1
            self.engineering_monitor['device'] = str(output[0].device)

        def check_gradient(self, name, gradient):
            if not torch.isfinite(gradient).all():
                raise FloatingPointError('nonfinite source60 gradient: '+name)
            self.engineering_monitor['finite_gradient_tensors'] += 1
            for prefix in ('actor', 'critic'):
                if name.startswith(prefix+'.') and bool(gradient.abs().sum() > 0):
                    self.engineering_monitor[prefix+'_nonzero_gradients'] += 1
            return gradient

    ppo.ActorCritic = AuditedActorCritic  # instrumentation only; retained model/loop/loss
    sys.argv = phase_arguments(Path(context_path), Path(context['storage_root']), phase)
    ppo.main()
