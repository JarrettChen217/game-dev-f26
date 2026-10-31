"""New UI keys reject ambiguous states without rewriting legacy files."""
import json
import tempfile
import unittest
from pathlib import Path

from tank_game.keymap import DEFAULT_KEYMAP_PATH, KeymapError, load_keymap


class UIKeymapTests(unittest.TestCase):
    def keys(self, changes=None):
        data = json.loads(DEFAULT_KEYMAP_PATH.read_text())
        data['bindings'].pop('inspection_toggle', None)
        data['bindings'].update(changes or {})
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)/'keymap.json'
        path.write_text(json.dumps(data))
        return path

    def test_legacy_defaults_are_in_memory_and_escape_routes(self):
        path = self.keys()
        before = path.read_bytes()
        self.assertEqual(load_keymap(path, enable_ui=True).names('inspection_toggle'), ('TAB',))
        self.assertEqual(path.read_bytes(), before)

    def test_custom_tab_and_enter_conflicts_are_explicit(self):
        for change in ({'fire': ['TAB']}, {'restart': ['RETURN']}, {'quit': ['UP']}):
            with self.subTest(change=change), self.assertRaises(KeymapError):
                load_keymap(self.keys(change), enable_ui=True)

    def test_random_start_rejects_physical_modifier_alias_overlap(self):
        for modifier in ('SHIFT', 'CTRL', 'ALT'):
            for side in ('L', 'R'):
                for changes in ({'next_map': [side+modifier], 'restart': [modifier]},
                                {'next_map': [modifier], 'quit': [side+modifier]},
                                {'next_map': [side+modifier], 'inspection_toggle': [modifier]}):
                    with self.subTest(changes=changes):
                        keymap = load_keymap(self.keys(changes), enable_ui=True)
                        keymap.validate_mode(random_map=False)
                        with self.assertRaises(KeymapError):
                            keymap.validate_mode(random_map=True)
