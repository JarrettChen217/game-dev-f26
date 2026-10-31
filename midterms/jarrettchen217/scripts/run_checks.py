"""Run the deterministic midterm checks; exit nonzero on any failure.

  uv run --frozen python scripts/run_checks.py            (from midterms/jarrettchen217)

1 rules            Rust: 60Hz movement/ballistics/time conservation; Python: shooting, ricochets, collisions
2 legal actions    the 18-action set, illegal-action rejection, controller contract
3 termination      win/loss/draw outcomes, terminal rounds stay terminal
4 regression       pinned opening digest, determinism, model ABI/fallback, known bug regressions
5 episode limits   1800 task frames + 300 grace frames, passive rounds end as time draws
+ information boundary (hidden state never reaches the observation) and a full u19588 round.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUST_TESTS = ['laika_60hz_core', 'source60_play', 'source60_training_core', 'episode_contract',
              'information_boundary']


def run(label, command):
    print(f'\n== {label}: {" ".join(map(str, command))}', flush=True)
    return subprocess.run(command, cwd=ROOT, check=False).returncode == 0


def main():
    rustc = shutil.which('rustc')
    if not rustc:
        sys.exit('rustc not found; install Rust (for example `brew install rust`)')
    results = {}
    with tempfile.TemporaryDirectory() as build:
        for name in RUST_TESTS:
            binary = Path(build)/name
            results[f'rust {name}'] = (run(f'compile {name}', [rustc, '--edition=2021', '--test', '-O',
                                                                f'tests/{name}.rs', '-o', binary])
                                       and run(f'run {name}', [binary]))
    results['python unittest'] = run('python tests', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'])
    results['full u19588 round'] = run('u19588 vs Laika smoke', [sys.executable, 'scripts/evaluate.py', '--seeds', '1000'])
    print('\n'+'\n'.join(f'{"PASS" if ok else "FAIL"}  {name}' for name, ok in results.items()))
    sys.exit(0 if all(results.values()) else 1)


if __name__ == '__main__':
    main()
