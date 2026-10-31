"""GUI default changes do not alter headless or explicit launch semantics."""
import io
import unittest
from unittest.mock import patch

from tank_game.__main__ import main


class UICLITests(unittest.TestCase):
    def test_graphical_defaults_and_explicit_duel_are_distinct(self):
        for args, menu in (([], True), (['--duel'], False)):
            with (self.subTest(args=args), patch('sys.argv', ['tank_game']+args),
                  patch('tank_game.app.main') as launch):
                main()
                self.assertEqual(launch.call_args.kwargs['menu'], menu)
                self.assertEqual(launch.call_args.kwargs['strategy'], 'simple')

    def test_inspect_does_not_launch_menu(self):
        output = io.StringIO()
        with (patch('sys.argv', ['tank_game', '--inspect']), patch('sys.stdout', output),
              patch('tank_game.app.main') as launch):
            main()
            launch.assert_not_called()
        self.assertNotIn('tank-2', output.getvalue())
        self.assertIn('tank-1', output.getvalue())
