"""Public-only stable tensors, strict profiles and decision-scoped history."""
import unittest
from copy import deepcopy
from dataclasses import replace

import numpy as np

from tank_game.actions import Action
from tank_game.entities import BulletState
from tank_game.world import World

try:
    from tank_game.learning.encoding import ObservationEncoder
except ImportError:
    ObservationEncoder=None


class LearningEncodingTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(ObservationEncoder,'shared encoder missing')

    def test_layout_masks_timers_and_detachment(self):
        w=World(duel=True)
        w._tanks['tank-1']=replace(w._tanks['tank-1'],cooldown_remaining=.125)
        w._bullets=(BulletState('bullet-2',64,96,0,90,age=5),
                    BulletState('bullet-1',32,48,90,0,age=2.5))
        e=ObservationEncoder();a=e.encode(w.observe('tank-1'))
        self.assertEqual(a.shape,(340,));self.assertEqual(a.dtype,np.float32)
        self.assertEqual(int(a[:110].sum()),45)
        self.assertEqual(a[110],16/256)
        self.assertEqual(a[110+14],32/256) # first bullet is numeric ID1
        self.assertEqual(a[110+14+7],.75)
        self.assertEqual(a[110+104+3],.5)
        self.assertTrue(np.all(a[223:336]==0));self.assertEqual(a[-1],0)
        a[0]=77
        self.assertNotEqual(e.encode(w.observe('tank-1'))[0],77)

    def test_history_duplicate_reset_and_public_only_inputs(self):
        w=World(duel=True);e=ObservationEncoder()
        initial=w.observe('tank-1');a=e.encode(initial)
        extra=deepcopy(initial);extra['host_seed']=999
        np.testing.assert_array_equal(e.encode(extra),a)
        w.step();scene=w.observe('tank-1')
        b=e.encode(scene,Action(1,0,True))
        np.testing.assert_array_equal(b[223:336],a[110:223])
        np.testing.assert_array_equal(b[336:339],[1,0,1]);self.assertEqual(b[-1],1)
        np.testing.assert_array_equal(e.encode(scene,Action(1,0,True)),b)
        with self.assertRaises(ValueError):e.encode(scene,Action())
        with self.assertRaises(ValueError):e.encode(initial)
        w.restart(allow_active=True)
        c=e.encode(w.observe('tank-1'))
        self.assertEqual(c[-1],0);self.assertTrue(np.all(c[223:339]==0))

    def test_invalid_profiles_and_nonfinite_values_rejected(self):
        base=World(duel=True).observe('tank-1')
        cases=[]
        for path,value in [(('schema_version',),4),(('rules','tick_rate'),30),
                           (('duel','limit'),30),(('tanks',0,'x'),float('nan'))]:
            scene=deepcopy(base);target=scene
            for key in path[:-1]:target=target[key]
            target[path[-1]]=value;cases.append(scene)
        bad=deepcopy(base);bad['map']['walls'].append(deepcopy(bad['map']['walls'][0]));cases.append(bad)
        for scene in cases:
            with self.subTest(scene=scene),self.assertRaises(ValueError):ObservationEncoder().encode(scene)

    def test_full_capacity_and_absent_terminal_self(self):
        w=World(duel=True)
        w._bullets=tuple(BulletState(f'bullet-{i}',100,120,90,0) for i in range(1,11))
        x=ObservationEncoder().encode(w.observe('tank-1'))
        self.assertEqual(sum(x[110+14+8:110+104:9]),10)
        w._bullets+= (BulletState('bullet-11',100,120,90,0),)
        with self.assertRaises(ValueError):ObservationEncoder().encode(w.observe('tank-1'))
        w._bullets=();w._tanks['tank-1']=replace(w._tanks['tank-1'],alive=False)
        w._round_status='DYING';w._result='tank-2'
        x=ObservationEncoder().encode(w.observe('tank-1'))
        self.assertTrue(np.all(x[110:116]==0));self.assertTrue(np.all(np.isfinite(x)))
