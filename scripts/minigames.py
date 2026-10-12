#!/usr/bin/env python3
"""Local, dependency-free tooling for the Get Out variation lab."""
import argparse
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

PRINCIPLES = {
    'entry': 'Clear goal and easy entry',
    'progress': 'Visible progress',
    'solvability': 'Confidence in solvability',
    'sequence': 'Gradual difficulty',
    'hints': 'Progressive hints',
    'perception': 'A change in perspective',
    'parallelism': 'Parallel puzzles',
    'pyramid': 'Combining learned ideas',
    'solution': 'Learning from a solution',
}
# The boundary workflow reads this from the trusted base commit, never PR code.
MAINTAINERS = {'bgarakani'}
PROTECTED = ('minigames/', 'scripts/minigames.py', 'tests/test_minigame_tools.py',
             '.github/', '.agents/', 'AGENTS.md', '.gitignore')
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 5 * 1024 * 1024


def username(value):
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){0,38}', value):
        raise ValueError('Use your lowercase GitHub login (letters, numbers, single internal hyphens).')
    return value


def safe_tree(path, size_limits=True):
    """Reject symlinks/special files, oversized files, and filesystem escapes."""
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError(f'Symlinks are not supported: {ancestor}')
    if not path.is_dir():
        raise ValueError(f'Missing directory: {path}')
    total = 0
    for current, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            item = Path(current) / name
            if item.is_symlink() or not (item.is_dir() or item.is_file()):
                raise ValueError(f'Only regular files and directories are supported: {item}')
            if item.is_file():
                size = item.stat().st_size
                if size_limits and size > MAX_FILE:
                    raise ValueError(f'File exceeds 2 MiB: {item}')
                total += size
    if size_limits and total > MAX_TOTAL:
        raise ValueError(f'Game exceeds 5 MiB: {path}')


def scaffold(root, owner, principle):
    username(owner)
    if principle not in PRINCIPLES:
        raise ValueError('Choose a principle from the exercise guide.')
    source = root / 'minigames/get-out'
    destination = root / 'minigames/submissions' / owner / 'get-out'
    safe_tree(source)
    for parent in (destination, *destination.parents):
        if parent.is_symlink():
            raise ValueError(f'Symlinks are not supported: {parent}')
    if destination.exists():
        raise ValueError(f'Already exists; resume your work here: {destination}')
    template = root / 'minigames/templates/experiment.md'
    text = template.read_text(encoding='utf-8')
    shutil.copytree(source, destination)
    data = {'schema': 1, 'author': owner, 'title': f'{owner}: {PRINCIPLES[principle]}',
            'principle': principle, 'entry': 'index.html'}
    (destination / 'submission.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    (destination / 'experiment.md').write_text(text.replace('{{OWNER}}', owner).replace('{{PRINCIPLE}}', principle), encoding='utf-8')
    return destination


def validate(root, owner=None, ready=False):
    if owner is not None:
        username(owner)
    parent = root / 'minigames/submissions'
    if parent.is_symlink():
        raise ValueError('Submissions directory must not be a symlink.')
    if not parent.exists():
        if owner:
            raise ValueError(f'No submission for {owner}. Run new first.')
        return []
    if not parent.is_dir():
        raise ValueError('Submissions must be a directory.')
    results = []
    owners = [parent / owner] if owner else sorted(parent.iterdir())
    for user_dir in owners:
        username(user_dir.name)
        safe_tree(user_dir)
        if {p.name for p in user_dir.iterdir()} != {'get-out'}:
            raise ValueError(f'Expected exactly one get-out directory in {user_dir}')
        folder = user_dir / 'get-out'
        safe_tree(folder)
        data = json.loads((folder / 'submission.json').read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) != {'schema', 'author', 'title', 'principle', 'entry'}:
            raise ValueError(f'Unexpected manifest fields: {folder}')
        if type(data['schema']) is not int or data['schema'] != 1:
            raise ValueError('Manifest schema must be 1.')
        if data['author'] != user_dir.name or data['entry'] != 'index.html':
            raise ValueError('Author must match the folder and entry must be index.html.')
        if not isinstance(data['principle'], str) or data['principle'] not in PRINCIPLES:
            raise ValueError('Unknown puzzle principle.')
        if not isinstance(data['title'], str) or not 1 <= len(data['title'].strip()) <= 100:
            raise ValueError('Title must contain 1 to 100 characters.')
        for required in ('index.html', 'experiment.md', 'tests/engine.test.cjs'):
            file = folder / required
            if not file.is_file() or not file.read_bytes().strip():
                raise ValueError(f'Missing or empty required file: {file}')
        report = (folder / 'experiment.md').read_text(encoding='utf-8')
        if ready and re.search(r'\bTODO\b|\{\{', report, re.I):
            raise ValueError(f'Complete the experiment report before ready-for-review: {folder}')
        results.append(data)
    return results


def gallery(root):
    entries = validate(root)
    safe_tree(root / 'minigames/get-out')
    build = root / 'build'
    target = build / 'minigames'
    # Only this generated directory may be replaced. A marker prevents deleting
    # an unrelated existing folder; never follow a symlink at either level.
    if build.is_symlink() or target.is_symlink():
        raise ValueError('Build directories must not be symlinks.')
    if target.exists():
        safe_tree(target, size_limits=False)
        if not (target / '.generated-gallery').is_file():
            raise ValueError('Refusing to replace an unmarked build/minigames directory.')
        shutil.rmtree(target)
    target.mkdir(parents=True)
    (target / '.generated-gallery').write_text('Generated by scripts/minigames.py gallery\n')
    shutil.copytree(root / 'minigames/get-out', target / 'get-out')
    cards = ['<article><h2>Instructor reference</h2><p>Play the original before a variation.</p><a href="get-out/index.html">Play reference</a></article>']
    for entry in entries:
        owner = entry['author']
        relative = f'submissions/{owner}/get-out'
        shutil.copytree(root / 'minigames' / relative, target / relative)
        esc = html.escape
        cards.append(f'<article><h2>{esc(entry["title"])}</h2><p>{esc(owner)} · {esc(PRINCIPLES[entry["principle"]])}</p><a href="{relative}/index.html">Play variation</a> · <a href="{relative}/experiment.md">Read experiment</a></article>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Get Out · Variation gallery</title><style>body{margin:0 auto;padding:40px 22px;max-width:1000px;background:#f6f1e7;color:#172b3a;font:18px/1.5 system-ui}h1{font-size:clamp(2.3rem,6vw,4rem);line-height:1.05}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:20px}article{background:#fffdf7;border:2px solid #172b3a;border-radius:12px;padding:24px}h2{margin-top:0}a{color:#87371f;text-underline-offset:4px}header{max-width:700px;margin-bottom:32px}</style><header><p>AI IN PRACTICE · GAME DESIGN AND DEVELOPMENT</p><h1>One puzzle.<br>Many design questions.</h1><p>Play the reference, try a variation, and compare what happened with its designer’s prediction. These are experiments, not ranked submissions.</p></header><main>'''
    (target / 'index.html').write_text(page + '\n'.join(cards) + '</main></html>\n', encoding='utf-8')
    return target / 'index.html'


def changed_paths(root, base, head):
    # Object IDs or refs are separate arguments, never interpolated into a shell.
    for ref in (base, head):
        if not re.fullmatch(r'[a-zA-Z0-9_./-]+', ref) or ref.startswith('-'):
            raise ValueError('Invalid git revision.')
    raw = subprocess.check_output(['git', 'diff', '--no-renames', '--name-only', '-z', f'{base}...{head}', '--'], cwd=root)
    return [p.decode('utf-8') for p in raw.split(b'\0') if p]


def check_paths(paths, author):
    author = username(author.lower())
    touched = any(p.startswith('minigames/submissions/') for p in paths)
    if author in MAINTAINERS:
        return touched
    prefix = f'minigames/submissions/{author}/get-out/'
    if touched:
        invalid = [p for p in paths if not p.startswith(prefix)]
    else:
        invalid = [p for p in paths if any(p == protected or p.startswith(protected) for protected in PROTECTED)]
    if invalid:
        raise ValueError('A student variation PR may change only its author’s game folder. Instructor-owned files need an instructor PR. Outside scope: ' + ', '.join(invalid))
    return touched


def run_tests(root, owner=None):
    entries = validate(root, owner)
    folders = [root / 'minigames/get-out'] if owner is None else []
    folders += [root / 'minigames/submissions' / data['author'] / 'get-out' for data in entries]
    for folder in folders:
        tests = sorted((folder / 'tests').glob('*.test.cjs'))
        subprocess.run(['node', '--test', *map(str, tests)], check=True, cwd=root, timeout=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest='command', required=True)
    new = sub.add_parser('new')
    new.add_argument('owner')
    new.add_argument('--principle', choices=PRINCIPLES, required=True)
    for name in ('check', 'test'):
        command = sub.add_parser(name)
        command.add_argument('--owner')
        if name == 'check':
            command.add_argument('--ready', action='store_true')
    sub.add_parser('gallery')
    boundary = sub.add_parser('boundary')
    boundary.add_argument('--base', required=True)
    boundary.add_argument('--head', required=True)
    boundary.add_argument('--author', required=True)
    args = parser.parse_args()
    # Resolve root once (macOS /tmp itself is an OS-managed symlink).
    root = args.root.resolve()
    try:
        if args.command == 'new':
            print(scaffold(root, args.owner, args.principle))
        elif args.command == 'check':
            print(f'Valid submissions: {len(validate(root, args.owner, args.ready))}')
        elif args.command == 'gallery':
            print(gallery(root))
        elif args.command == 'test':
            run_tests(root, args.owner)
        else:
            paths = changed_paths(root, args.base, args.head)
            check_paths(paths, args.author)
            # Static validation only. Never execute files from the submitted head.
            validate(root)
            print('Submission boundaries and metadata passed.')
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
