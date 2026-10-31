"""Pure runtime imports work when desktop dependencies are unavailable."""
import subprocess
import sys
import unittest


class PlatformBoundaryTests(unittest.TestCase):
    def test_pure_imports_reject_native_dependencies(self):
        code = '''
import importlib.abc, sys
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('pyxel','multiprocessing','numpy','gymnasium','torch','stable_baselines3') or fullname == 'tank_game.window_state':
            raise ImportError('desktop dependency forbidden: '+fullname)
sys.meta_path.insert(0,Reject())
from tank_game import world, agents, strategies, control_math, window_contract, runtime_factories, episodes, contracts, runner
from tank_game.learning import contracts as learning_contracts, actions as learning_actions
assert 'multiprocessing' not in sys.modules
assert 'tank_game.process_worker' not in sys.modules
'''
        proc = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
