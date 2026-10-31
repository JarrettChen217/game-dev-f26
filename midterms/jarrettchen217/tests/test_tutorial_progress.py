"""Completion is user-local, versioned and best-effort, never a play gate."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from tank_game import tutorial_progress as progress
except ImportError:
    progress = None


class TutorialProgressTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(progress, 'local tutorial completion storage is missing')
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'app' / 'tutorial-progress.json'

    def test_missing_corrupt_and_future_records_are_unrecognized_and_preserved(self):
        self.assertFalse(progress.load_completed(self.path))
        self.path.parent.mkdir()
        for raw in ('bad json', '[]', '{"tutorial_version": 4, "completed": true}',
                    '{"tutorial_version": true, "completed": true}',
                    '{"tutorial_version": 1, "completed": "yes"}'):
            self.path.write_text(raw)
            self.assertFalse(progress.load_completed(self.path))
            self.assertEqual(self.path.read_text(), raw)
        with patch.object(Path, 'read_text', side_effect=PermissionError('denied')):
            self.assertFalse(progress.load_completed(self.path))

    def test_actual_completion_saves_atomically_with_only_version_and_flag(self):
        self.assertTrue(progress.save_completed(self.path))
        self.assertTrue(progress.load_completed(self.path))
        self.assertEqual(json.loads(self.path.read_text()),
                         {'tutorial_version': 3, 'completed': True})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_unwritable_storage_is_nonblocking_and_preserves_existing_record(self):
        self.path.parent.mkdir()
        self.path.write_text('{"tutorial_version": 4, "completed": true}')
        before = self.path.read_bytes()
        with patch('tank_game.tutorial_progress.os.replace', side_effect=PermissionError('denied')):
            self.assertFalse(progress.save_completed(self.path))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        blocker = Path(self.directory.name) / 'file'
        blocker.write_text('not a directory')
        self.assertFalse(progress.save_completed(blocker / 'state.json'))

    def test_default_path_uses_platform_application_data_not_cwd(self):
        home = Path(self.directory.name).resolve()/'home'
        local = Path(self.directory.name).resolve()/'local'
        xdg = Path(self.directory.name).resolve()/'xdg'
        with patch('tank_game.tutorial_progress.sys.platform', 'darwin'), \
             patch.object(Path, 'home', return_value=home):
            self.assertEqual(progress.default_progress_path(), home/
                'Library/Application Support/TankTroubleReconstruction/tutorial-progress.json')
        with patch('tank_game.tutorial_progress.sys.platform', 'win32'), \
             patch.dict('os.environ', {'LOCALAPPDATA': str(local)}):
            self.assertEqual(progress.default_progress_path(), local/
                'TankTroubleReconstruction/tutorial-progress.json')
        with patch('tank_game.tutorial_progress.sys.platform', 'linux'), \
             patch.dict('os.environ', {'XDG_DATA_HOME': str(xdg)}):
            self.assertEqual(progress.default_progress_path(), xdg/
                'tank-trouble-reconstruction/tutorial-progress.json')


    def test_legacy_four_lesson_completion_is_preserved_but_not_current(self):
        self.path.parent.mkdir()
        legacy = '{"tutorial_version": 1, "completed": true}'
        self.path.write_text(legacy)
        self.assertFalse(progress.load_completed(self.path))
        self.assertEqual(self.path.read_text(), legacy)
        self.assertTrue(progress.save_completed(self.path))
        self.assertEqual(json.loads(self.path.read_text()),
                         {'tutorial_version': 3, 'completed': True})
