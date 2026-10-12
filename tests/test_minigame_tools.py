"""Contract tests for classroom submission tooling (no external services)."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('minigames', REPO / 'scripts/minigames.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MinigameToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        shutil.copytree(REPO / 'minigames/get-out', self.root / 'minigames/get-out')
        shutil.copytree(REPO / 'minigames/templates', self.root / 'minigames/templates')

    def new(self, owner='alice'):
        return m.scaffold(self.root, owner, 'hints')

    def test_two_students_and_overwrite_refusal(self):
        a, b = self.new(), self.new('bob')
        self.assertNotEqual(a, b)
        self.assertEqual(m.validate(self.root)[0]['author'], 'alice')
        with self.assertRaises(ValueError):
            self.new()
        self.assertTrue((a / 'index.html').is_file())

    def test_invalid_usernames(self):
        for owner in ('../alice', '-alice', 'alice-', 'a/b', 'a--b', 'ALICE', ''):
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                self.new(owner)

    def test_manifest_mismatches(self):
        folder = self.new()
        path = folder / 'submission.json'
        original = json.loads(path.read_text())
        for key, value in [('author', 'bob'), ('entry', '../index.html'),
                           ('principle', 'unknown'), ('title', ''), ('schema', True)]:
            data = dict(original, **{key: value})
            path.write_text(json.dumps(data))
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.validate(self.root)
        path.write_text(json.dumps(original))
        (folder / 'experiment.md').unlink()
        with self.assertRaises(ValueError):
            m.validate(self.root)

    def test_symlinks_rejected(self):
        folder = self.new()
        (folder / 'shortcut').symlink_to(self.root / 'minigames/get-out')
        with self.assertRaises(ValueError):
            m.validate(self.root)

    def test_symlinked_submission_parent_rejected_before_writing(self):
        target = self.root / 'elsewhere'
        target.mkdir()
        (self.root / 'minigames/submissions').symlink_to(target)
        with self.assertRaises(ValueError):
            self.new()
        self.assertEqual(list(target.iterdir()), [])

    def test_draft_and_ready(self):
        folder = self.new()
        m.validate(self.root)
        with self.assertRaises(ValueError):
            m.validate(self.root, ready=True)
        (folder / 'experiment.md').write_text('Observed one player. Exploratory evidence only.\n')
        m.validate(self.root, ready=True)

    def test_gallery_escape_links_and_no_overwrite_outside_build(self):
        folder = self.new()
        path = folder / 'submission.json'
        data = json.loads(path.read_text())
        data['title'] = '<script>alert(1)</script>'
        path.write_text(json.dumps(data))
        out = m.gallery(self.root)
        text = out.read_text()
        self.assertIn('&lt;script&gt;', text)
        self.assertNotIn('<script>alert(1)</script>', text)
        self.assertTrue((out.parent / 'submissions/alice/get-out/index.html').is_file())
        self.assertTrue((out.parent / 'get-out/index.html').is_file())
        self.assertEqual(out, m.gallery(self.root))

    def test_gallery_handles_combined_games_larger_than_single_game_limit(self):
        for owner in ('alice', 'bob'):
            folder = self.new(owner)
            for number in range(2):
                (folder / f'asset{number}.txt').write_bytes(b'x' * (1500 * 1024))
        m.gallery(self.root)
        m.gallery(self.root)

    def test_gallery_preserves_unrelated_build_directory(self):
        folder = self.root / 'build/minigames'
        folder.mkdir(parents=True)
        (folder / 'precious.txt').write_text('preserve')
        with self.assertRaises(ValueError):
            m.gallery(self.root)
        self.assertEqual((folder / 'precious.txt').read_text(), 'preserve')

    def test_boundary_ownership_and_mixed_changes(self):
        self.assertTrue(m.check_paths(['minigames/submissions/alice/get-out/app.js'], 'alice'))
        self.assertFalse(m.check_paths(['course_game/game.py'], 'alice'))
        for paths in ([ 'minigames/submissions/bob/get-out/app.js'],
                      ['minigames/submissions/alice/get-out/app.js', 'minigames/get-out/app.js'],
                      ['minigames/submissions/alice/get-out/app.js', '.github/workflows/a.yml']):
            with self.assertRaises(ValueError):
                m.check_paths(paths, 'alice')

    def test_git_rename_and_delete_keep_both_paths(self):
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=self.root, text=True).strip()
        git('init', '-q')
        git('config', 'user.email', 'test@example.invalid')
        git('config', 'user.name', 'Test')
        self.new()
        git('add', '.')
        git('commit', '-qm', 'base')
        base = git('rev-parse', 'HEAD')
        source = self.root / 'minigames/get-out/README.md'
        source.rename(self.root / 'minigames/submissions/alice/get-out/stolen.md')
        git('add', '-A')
        git('commit', '-qm', 'rename')
        paths = m.changed_paths(self.root, base, 'HEAD')
        self.assertIn('minigames/get-out/README.md', paths)
        with self.assertRaises(ValueError):
            m.check_paths(paths, 'alice')


if __name__ == '__main__':
    unittest.main()
