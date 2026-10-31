"""Rebuild the two native60Hz play libraries from the Rust sources in this folder.

Needs only `rustc` (no Cargo, no downloads). Paths are remapped so the binaries
carry no machine-specific directories. The training library is not shipped:
tank_game/laika_60hz/training/manifest.json is kept only as the record of the
environment u19588 was trained on (its digest is pinned in tank_game/models). Targets macOS arm64, the platform the
committed libraries are built for.
"""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT/'tank_game/laika_60hz'
LAIKA = ROOT/'tank_game/original_laika/source'
SHARED = [LAIKA/n for n in ('maze.rs', 'rng.rs', 'ballistics.rs')]
LIBRARIES = {
    # name: (crate root, output folder, manifest profile, extra source globs)
    'engine': (GAME/'source/lib.rs', GAME, 'laika-source-60hz-v1', [GAME/'source']),
    'play': (GAME/'training/source/play_lib.rs', GAME/'play', 'source60-hybrid-play-v1',
             [GAME/'training/source', GAME/'source']),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(rustc, name):
    crate, folder, profile, globs = LIBRARIES[name]
    folder.mkdir(parents=True, exist_ok=True)
    library = f'{name}.dylib'
    home = Path.home()
    with TemporaryDirectory() as temporary:
        artifact = Path(temporary)/library
        subprocess.run([rustc, '--edition=2021', '--crate-type=cdylib', '-C', 'opt-level=3',
                        '-C', 'panic=abort', '-C', 'codegen-units=1', '-C', 'strip=symbols',
                        # rustc applies the last matching prefix, so the most specific goes last.
                        f'--remap-path-prefix={home}=~', f'--remap-path-prefix={Path(temporary)}=build',
                        f'--remap-path-prefix={ROOT}=.',
                        '-C', f'link-arg=-Wl,-install_name,@rpath/{library}',
                        str(crate), '-o', str(artifact)], check=True)
        shutil.copyfile(artifact, folder/library)
    sources = sorted({p for g in globs for p in g.glob('*.rs')} | set(SHARED))
    manifest = {'profile': profile, 'target': 'aarch64-apple-darwin',
                'compiler': subprocess.check_output([rustc, '--version'], text=True).strip(),
                'library': library, 'library_sha256': digest(folder/library),
                'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in sources}}
    (folder/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return {'library': str((folder/library).relative_to(ROOT)), 'sha256': manifest['library_sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rustc', default=shutil.which('rustc'))
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ('Darwin', 'arm64'):
        parser.error('the native60Hz libraries target macOS arm64')
    if not args.rustc:
        parser.error('rustc not found; install Rust (for example `brew install rust`)')
    print(json.dumps([build(args.rustc, name) for name in LIBRARIES], indent=2))


if __name__ == '__main__':
    main()
