"""Bounded seed11 learning hooks around the retained Python PPO, not a new loop."""
import json
import math
import shutil
import sys
import time
from pathlib import Path

from tank_game.laika_60hz.training.engineering import atomic_json, digest

CAP = 16777216
FILES = ('live.pt', 'live.json', 'resume.pt')


def used_bytes(root):
    total = 0
    for path in Path(root).rglob('*'):
        try:
            if path.is_file():
                total += path.stat().st_size
        except FileNotFoundError:  # concurrent inactive-slot recycling; next sample sees replacement
            continue
    return total


class RollingGroups:
    """Two full groups; only recycle this pilot's inactive slot after validation.

    Individual serializers remain atomic-file writes, not an atomic directory.
    A complete SHA marker precedes pointer publication. Power loss can still lose
    the latest group; future deliberate recovery validates both retained groups.
    """
    def __init__(self, output, allocation, *, cap=CAP):
        if cap not in (CAP,18*1024**2):
            raise ValueError('only the original or specifically approved continuation cap is supported')
        self.cap = cap
        self.output, self.allocation = Path(output), Path(allocation)
        self.output.mkdir(parents=True, exist_ok=True)

    def valid(self, slot):
        try:
            group = self.output/slot
            marker = json.loads((group/'checkpoint.json').read_text())
            if marker['complete'] and all(digest(group/f) == h for f, h in marker['files'].items()):
                return dict(marker, slot=slot)
        except (OSError, ValueError, KeyError):
            pass
        return None

    def latest(self):
        try:
            pointer = json.loads((self.output/'latest.json').read_text())
            marker = self.valid(pointer['slot'])
            if marker and marker['update'] == pointer['update']:
                return marker
        except (OSError, ValueError, KeyError):
            pass
        candidates = [m for slot in ('slot0', 'slot1') if (m := self.valid(slot))]
        return max(candidates, key=lambda m: m['update']) if candidates else None

    def publish(self, update, steps, warmup, writer):
        previous = self.latest()
        slot = 'slot1' if previous and previous['slot'] == 'slot0' else 'slot0'
        target = self.output/slot
        target.mkdir(exist_ok=True)
        allowed = {*FILES, 'checkpoint.json', *(f+'.tmp' for f in FILES), 'checkpoint.json.tmp'}
        if any(not p.is_file() or p.name not in allowed for p in target.iterdir()):
            raise RuntimeError('foreign content in pilot inactive slot; preserve it')
        # Only this pilot's inactive slot is recyclable; current/engineering evidence stays.
        for p in target.iterdir():
            p.unlink()
        if used_bytes(self.allocation)+4400000 > self.cap:
            raise RuntimeError('shared allocation lacks full publication reserve')
        writer(target)
        if used_bytes(target) > 4400000:
            raise RuntimeError('full checkpoint exceeded predeclared group reserve')
        marker = {'complete': True, 'update': update, 'model_steps': steps,
                  'warmup_completed': warmup, 'files': {f: digest(target/f) for f in FILES}}
        atomic_json(target/'checkpoint.json', marker)
        atomic_json(self.output/'latest.json', {'slot': slot, 'update': update})
        return dict(marker, slot=slot)


def evaluate_panel(model, output, deadline, update, seeds=range(19000, 19020)):
    """Retained per-case/argmax loop; explicit frozen seeds and started-case meter."""
    import numpy as np
    import torch

    from tank_game.laika_60hz.training.vector import Source60HybridVec

    path = Path(output)
    if path.exists():
        raise RuntimeError('panel exists; preserve completed cases, do not rerun')
    rng = (torch.get_rng_state(), np.random.get_state(), torch.cuda.get_rng_state_all())
    device = next(model.parameters()).device
    rows, started = [], time.monotonic()
    model.eval()
    try:
        with path.open('x') as stream, torch.inference_mode():
            for index, seed in enumerate(seeds):
                if time.time() >= deadline:
                    break
                atomic_json(path.with_suffix('.progress.json'),
                            {'started_cases': index+1, 'completed_rows': len(rows), 'last_seed': seed})
                row = {'seed': seed, 'result': 'partial', 'frames': 0, 'update': update}
                env = Source60HybridVec(1, seed, (1., 0., 0.), 1)
                try:
                    for frame in range(2101):
                        if time.time() >= deadline:
                            break
                        logits, _ = model(torch.as_tensor(env.obs.copy(), device=device),
                                          torch.as_tensor(env.masks.astype(bool), device=device))
                        if not torch.isfinite(logits).all():
                            raise FloatingPointError('nonfinite evaluation logits')
                        env.step(logits.argmax(-1).cpu().numpy())
                        row['frames'] = frame+1
                        if env.dones[0]:
                            row.update(result={1: 'win', 2: 'loss', 3: 'double', 4: 'draw'}[int(env.outcomes[0])],
                                       reward=float(env.rewards[0]))
                            break
                finally:
                    env.close()
                rows.append(row); stream.write(json.dumps(row)+'\n'); stream.flush()
                if row['result'] == 'partial':
                    break
    finally:
        torch.set_rng_state(rng[0]); np.random.set_state(rng[1]); torch.cuda.set_rng_state_all(rng[2])
    counts = {key: sum(r['result'] == key for r in rows) for key in ('win', 'loss', 'double', 'draw', 'partial')}
    summary = {'update': update, 'started_cases': len(rows), 'counts': counts,
               'status': 'complete' if len(rows) == len(seeds) and not counts['partial'] else 'partial',
               'seconds': time.monotonic()-started, 'seeds': list(seeds),
               'opponent': 'Laika', 'policy': 'argmax', 'case_sha256': digest(path),
               'classification': 'paired fixed-seed development comparison, not convergence/generalization'}
    atomic_json(path.with_suffix('.summary.json'), summary)
    return summary


def ResearchHook(context_path):
    import numpy as np
    import torch

    from tank_game.laika_60hz.training.contract import contract_digest, validate_resume_metadata

    class Hook:
        def __init__(self):
            self.context = json.loads(Path(context_path).read_text())
            self.output = Path(self.context['output'])
            self.groups = RollingGroups(self.output/'checkpoints', self.context['allocation'])
            self.training_started = None
            self.deadline = self.context['batch_deadline_unix']-125
            if self.context['environment_contract_sha256'] != contract_digest():
                raise ValueError('environment contract mismatch')

        def restore(self, payload):
            if payload is None:
                return 0, 0
            state = payload['research']; validate_resume_metadata(state)
            if (state['protocol_sha256'] != self.context['protocol_sha256']
                    or state['source_head'] != self.context['source_head']):
                raise ValueError('foreign pilot checkpoint')
            torch.set_rng_state(state['torch_rng'].cpu()); np.random.set_state(state['numpy_rng'])
            torch.cuda.set_rng_state_all([v.cpu() for v in state['cuda_rng']])
            return state['update'], state['warmup_completed']

        def check(self):
            if used_bytes(self.context['allocation']) > CAP or shutil.disk_usage(self.output).free < 10*1024**3:
                raise RuntimeError('shared output/free-disk budget exceeded')

        def before_rollout(self, batch):
            self.check()
            if batch != 4928 or time.time() >= self.deadline:
                raise SystemExit(74)

        def before_optimizer_step(self):
            if time.time() >= self.deadline:
                raise SystemExit(74)

        def metric(self, record):
            for name in ('entropy', 'policy_loss', 'value_loss', 'approx_kl', 'clipfrac'):
                if not math.isfinite(record[name]):
                    raise FloatingPointError('nonfinite '+name)
            return record

        def publish(self, model, optimiser, config, model_steps, update, warmup_completed,
                    save_live, save_resume, started, schedule_steps):
            self.check()
            orderly_stop = self.training_started is not None and time.time() >= self.deadline-10
            if update % 8 and not orderly_stop:
                return
            assert schedule_steps == 480000000 and warmup_completed == min(20, update)
            assert all(torch.isfinite(v).all() for v in model.state_dict().values())
            assert all(not torch.is_tensor(v) or torch.isfinite(v).all()
                       for group in optimiser.state.values() for v in group.values())
            metadata = {'protocol_sha256': self.context['protocol_sha256'], 'source_head': self.context['source_head'],
                        'environment_contract_sha256': contract_digest(), 'update': update,
                        'warmup_completed': warmup_completed, 'torch_rng': torch.get_rng_state(),
                        'numpy_rng': np.random.get_state(), 'cuda_rng': torch.cuda.get_rng_state_all()}
            def write(path):
                save_live(path, model, config, model_steps, update, started, model_steps, schedule_steps)
                live = json.loads((path/'live.json').read_text())
                live.update(profile='source60-schema24-prep-v1', environment_contract_sha256=contract_digest())
                atomic_json(path/'live.json', live)
                save_resume(path, model, optimiser, model_steps, schedule_steps, research=metadata)
            marker = self.groups.publish(update, model_steps, warmup_completed, write)
            atomic_json(self.output/'progress.json', {**marker, 'device': str(next(model.parameters()).device),
                        'training_seconds': time.monotonic()-self.training_started if self.training_started else 0})
            print('PILOT_CHECKPOINT '+json.dumps(marker), flush=True)
            if update == 0:
                panel = evaluate_panel(model, self.output/'initial.jsonl', min(time.time()+120, self.context['batch_deadline_unix']-1), 0)
                if panel['status'] != 'complete':
                    raise SystemExit(74)
                self.training_started = time.monotonic()
                self.deadline = min(time.time()+900, self.context['batch_deadline_unix']-125)
            if update == 64 or orderly_stop:
                training_seconds = time.monotonic()-self.training_started
                atomic_json(self.output/'training-stop.json', {'update': update, 'steps': model_steps,
                            'training_seconds': training_seconds, 'reason': 'fixed64endpoint' if update == 64 else 'time cap'})
                if update == 64:
                    evaluate_panel(model, self.output/'final.jsonl', min(time.time()+120, self.context['batch_deadline_unix']-2), update)
                raise SystemExit(75)

    return Hook()


def train(context):
    import torch

    from tank_game.laika_60hz.training import ppo

    torch.set_num_threads(1)
    original = ppo.ActorCritic
    class Audited(original):
        def __init__(self):
            super().__init__()
            for name, parameter in self.named_parameters():
                parameter.register_hook(lambda gradient, name=name: self.finite_gradient(name, gradient))
        def finite_gradient(self, name, gradient):
            if not torch.isfinite(gradient).all():
                raise FloatingPointError('nonfinite gradient '+name)
            return gradient
    ppo.ActorCritic = Audited
    data = json.loads(Path(context).read_text())
    sys.argv = ['source60-pilot', '--steps', '315392', '--envs', '16', '--seed', '11',
                '--critic-warmup-updates', '20', '--mix', '1', '0', '0', '--threads', '1',
                '--device', 'cuda', '--timing-profile', '--schedule-steps', '480000000',
                '--save-every', '0', '--research-context', str(context), '--output', str(Path(data['output'])/'run')]
    ppo.main()
