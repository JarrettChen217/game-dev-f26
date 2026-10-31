"""Startup config and real input adapter wiring without window/device access."""

import json
import tempfile
import unittest
from pathlib import Path

from tank_game.app import DrivingApp
from tank_game.keymap import DEFAULT_KEYMAP_PATH, KeymapError, load_keymap
from tank_game.world import World
from tests.test_driving import open_map
from tests.test_driving_app import WindowStub


def defaults():
    return json.loads(DEFAULT_KEYMAP_PATH.read_text())


def write_config(directory, config):
    path = Path(directory) / 'keymap.json'
    path.write_text(json.dumps(config))
    return path


class KeymapTests(unittest.TestCase):
    def test_repo_defaults_and_path_are_independent_of_cwd(self):
        keymap = load_keymap()
        self.assertTrue(DEFAULT_KEYMAP_PATH.is_absolute())
        self.assertEqual(keymap.names('forward'), ('W', 'UP'))
        self.assertEqual(keymap.names('fire'), ('F', 'SPACE'))
        self.assertEqual(keymap.names('quit'), ('ESCAPE',))

    def test_invalid_configs_fail_with_file_and_action_context(self):
        invalid = []
        for name, values in (('forward', []), ('fire', ['F','F']), ('quit', ['W']),
                             ('turn_left', 'A'), ('fire', [4]), ('fire', ['NO_SUCH_KEY'])):
            data = defaults()
            data['bindings'][name] = values
            invalid.append((data, name))
        missing = defaults()
        del missing['bindings']['fire']
        invalid.append((missing, 'fire'))
        unknown = defaults()
        unknown['bindings']['teleport'] = ['T']
        invalid.append((unknown, 'teleport'))
        bad_version = defaults()
        bad_version['version'] = True
        invalid.append((bad_version, 'version'))
        invalid.append(({'version':2, 'bindings':{}}, 'version'))
        with tempfile.TemporaryDirectory() as directory:
            for data, context in invalid:
                with self.subTest(data=data):
                    path = write_config(directory, data)
                    with self.assertRaises(KeymapError) as caught:
                        load_keymap(path)
                    self.assertIn(str(path.resolve()), str(caught.exception))
                    self.assertIn(context, str(caught.exception))

    def test_missing_malformed_and_duplicate_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'keymap.json'
            for raw in (None, '{', '{"version":1,"version":1,"bindings":{}}'):
                if raw is not None:
                    path.write_text(raw)
                with self.assertRaises(KeymapError):
                    load_keymap(path)

    def test_names_are_case_insensitive_and_duplicates_remain_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            config = defaults()
            config['bindings']['fire'] = ['space']
            loaded = load_keymap(write_config(directory, config))
            self.assertEqual(loaded.names('fire'), ('SPACE',))
            config['bindings']['fire'] = ['f', 'F']
            with self.assertRaises(KeymapError):
                load_keymap(write_config(directory, config))

    def test_aggregate_and_side_modifiers_cannot_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            for group, side in (('SHIFT', 'LSHIFT'), ('SHIFT', 'RSHIFT'),
                                ('CTRL', 'LCTRL'), ('CTRL', 'RCTRL'),
                                ('ALT', 'LALT'), ('ALT', 'RALT')):
                with self.subTest(group=group, side=side):
                    config = defaults()
                    config['bindings']['forward'] = [group]
                    config['bindings']['quit'] = [side]
                    with self.assertRaises(KeymapError):
                        load_keymap(write_config(directory, config))
            config = defaults()
            config['bindings']['fire'] = ['SHIFT', 'LSHIFT']
            with self.assertRaises(KeymapError):
                load_keymap(write_config(directory, config))
            config['bindings']['forward'] = ['LSHIFT']
            config['bindings']['fire'] = ['RSHIFT']
            load_keymap(write_config(directory, config))  # distinct physical keys allowed

    def test_restart_reads_modified_file_once_per_app(self):
        with tempfile.TemporaryDirectory() as directory:
            config = defaults()
            path = write_config(directory, config)
            window = WindowStub()
            window.KEY_SPACE = 'space'
            first = DrivingApp(window, World(open_map()), keymap_path=path, clock=window.clock)
            config['bindings']['fire'] = ['SPACE']
            write_config(directory, config)
            window.pressed = {'f'}
            first.update()
            self.assertEqual(len(first.world._bullets), 1)  # no hot reload
            window = WindowStub()
            window.KEY_SPACE = 'space'
            second = DrivingApp(window, World(open_map()), keymap_path=path, clock=window.clock)
            window.pressed = {'f'}
            second.update()
            self.assertEqual(len(second.world._bullets), 0)
            window.pressed = {'space'}
            second.update()
            self.assertEqual(len(second.world._bullets), 1)
            window.pressed.clear()
            window.held = {'space'}
            for _ in range(30):
                second.update()
            self.assertEqual(len(second.world._bullets), 1)

    def test_custom_drive_fire_quit_and_scroll_use_shared_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            config = defaults()
            config['bindings'].update(forward=['I'], backward=['K'],
                                      turn_left=['J'], turn_right=['L'], fire=['SPACE'],
                                      quit=['Q'], inspection_next=['N'], inspection_previous=['P'])
            path = write_config(directory, config)
            window = WindowStub()
            for name in ('I','K','J','L','SPACE','Q','N','P'):
                setattr(window, 'KEY_'+name, name.lower())
            app = DrivingApp(window, World(open_map()), keymap_path=path, clock=window.clock)
            self.assertEqual(window.init_options['quit_key'], window.KEY_NONE)
            app.ui.inspection_visible = True
            window.held = {'w','d'}
            app.update()
            self.assertEqual(app.world._tanks['tank-1'].x, 100)
            window.held = {'i','l'}
            window.pressed = {'space','n'}
            app.update()
            self.assertGreater(app.world._tanks['tank-1'].x, 100)
            self.assertEqual(app.scene['tanks'][0]['heading_deg'], 3)
            self.assertEqual(len(app.world._bullets), 1)
            self.assertGreater(app.scroll, 0)
            self.assertIn('I', app.controls_hint)
            self.assertIn('SPACE', app.controls_hint)
            window.held = {'i','k','j','l'}
            window.pressed = {'p'}
            before = app.world._tanks['tank-1']
            app.update()
            self.assertEqual((before.x,before.y,before.heading_deg),
                             (app.world._tanks['tank-1'].x,app.world._tanks['tank-1'].y,
                              app.world._tanks['tank-1'].heading_deg))
            self.assertEqual(app.scroll, 0)
            window.held.clear()
            window.pressed = {'esc'}
            app.update()
            self.assertFalse(window.exited)
            tick = app.scene['observation_tick']
            window.pressed = {'q'}
            app.update()
            self.assertFalse(window.exited)
            self.assertEqual(app.ui.screen, 'pause')
            window.pressed.clear()
            app.update()
            app.ui.focus = 'quit'
            window.pressed = {'enter'}
            app.update()
            self.assertFalse(window.exited)
            window.pressed.clear()
            app.update()
            self.assertTrue(window.exited)
            self.assertEqual(app.scene['observation_tick'], tick)


class StateBindingTests(unittest.TestCase):
    def test_restart_key_can_overlap_gameplay_but_not_global_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            config = defaults()
            config['bindings']['restart'] = ['SPACE']
            path = write_config(directory, config)
            try:
                loaded = load_keymap(path)
            except KeymapError as error:
                self.fail(f'State-specific Space reuse rejected: {error}')
            self.assertEqual(loaded.names('restart'), ('SPACE',))
            config['bindings']['restart'] = ['ESCAPE']
            with self.assertRaises(KeymapError):
                load_keymap(write_config(directory, config))

    def test_old_v1_config_keeps_working_with_default_postgame_space(self):
        with tempfile.TemporaryDirectory() as directory:
            config = defaults()
            config['bindings'].pop('restart', None)
            loaded = load_keymap(write_config(directory, config))
            self.assertIn('restart', loaded.bindings)
            self.assertEqual(loaded.names('restart'), ('SPACE',))
