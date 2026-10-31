"""Native lesson navigation uses real actions; helpers never teleport engine state."""
import unittest
from dataclasses import replace
from math import atan2, degrees, hypot

from tank_game import tutorial
from tank_game.controllers import keyboard_request
from tank_game.map import Rect


def drive(session, held=(), count=1, *, fire=False):
    for _ in range(count):
        scene=session.scenario.world.observe('tank-1')
        session.tick(keyboard_request(scene,set(held),fire_pressed=fire))


def goal_around_current(session, inset=1):
    scene=session.scenario.world.observe('tank-1');tank=scene['tanks'][0];r=tank['radius']
    # Change only the host acceptance marker for UI/dwell unit checks, not native state.
    session.scenario=replace(session.scenario,goal=Rect(tank['x']-r-inset,tank['y']-r-5,2*r+10,2*r+10))


def navigate(session, points):
    for x,y in points:
        for _ in range(400):
            scene=session.scenario.world.observe('tank-1');tank=scene['tanks'][0]
            if session.phase!='active' or hypot(x-tank['x'],y-tank['y'])<.08*scene['map']['tile_size']:break
            error=(degrees(atan2(y-tank['y'],x-tank['x']))-tank['heading_deg']+180)%360-180
            drive(session,{'turn_right' if error>0 else 'turn_left'} if abs(error)>2.1 else {'forward'})


class TutorialScenarioTests(unittest.TestCase):
    def session(self,step=1):
        s=tutorial.TutorialSession();self.addCleanup(s.close)
        if step!=1:
            s.scenario.world.close();s.scenario=tutorial.make_tutorial_scenario(step);s._reset()
        return s

    def test_open_room_goal_reachable(self):
        s=self.session();z=s.scenario.world.observe('tank-1')['map']['tile_size']
        navigate(s,[(5*z,1.5*z),(5*z,.9*z)]);drive(s,count=15)
        self.assertEqual(s.phase,'success')

    def test_compact_first_room_requires_turning_and_allows_safe_reversing(self):
        s=self.session();drive(s,{'forward'},300)
        self.assertEqual(s.phase,'active');before=s.scenario.world.observe('tank-1')['tanks'][0]
        drive(s,{'backward'},60);after=s.scenario.world.observe('tank-1')['tanks'][0]
        self.assertTrue(after['alive']);self.assertLess(after['x'],before['x'])

    def test_l_corridor_goal_reachable_without_wall_shortcut(self):
        s=self.session(2);z=s.scenario.world.observe('tank-1')['map']['tile_size']
        drive(s,{'turn_left'},11);drive(s,{'forward'},150)
        self.assertGreater(s.scenario.world.observe('tank-1')['tanks'][0]['y'],4*z)
        self.assertTrue(s.retry());navigate(s,[(7*z,5*z),(7*z,z)]);drive(s,count=15)
        self.assertEqual(s.phase,'success')

    def test_invalid_step_and_physics_override_are_rejected(self):
        from tank_game.config import GameConfig
        for step in (0,6,True,'1'):
            with self.assertRaises(ValueError):tutorial.make_tutorial_scenario(step)
        with self.assertRaisesRegex(ValueError,'fixed native rules'):
            tutorial.make_tutorial_scenario(1,GameConfig(max_bullets=3))
