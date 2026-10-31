"""Optional hull must change real wall/hit geometry and public prediction together."""
import unittest
from dataclasses import replace
from inspect import signature

from tank_game.controllers import keyboard_request
from tank_game.entities import BulletState
from tank_game.map import Spawn, WallEdge
from tank_game.world import World
from tests.test_driving import open_map
from tests.test_laika_dodge_repair import incoming


class OrientedHullTests(unittest.TestCase):
    def world(self,heading=0,extra=(),**kwargs):
        self.assertIn('collision_profile',signature(World).parameters,'oriented hull missing')
        maze=open_map(Spawn(112,112,heading));maze=replace(maze,edges=maze.edges+tuple(extra))
        return World(maze,duel=True,spawns=(maze.spawn,Spawn(272,272,180)),collision_profile='rectangle',**kwargs)

    def test_orientation_changes_authoritative_bullet_hit(self):
        outcomes=[]
        for heading in (0,90):
            w=self.world(heading)
            w._bullets=(BulletState('fixture',119,80,0,90),)
            for _ in range(35):w.step()
            outcomes.append(w.observe('tank-1')['self_status']['alive'])
        self.assertEqual(outcomes,[False,True])

    def test_fast_translation_cannot_tunnel_through_wall(self):
        from tank_game.config import GameConfig
        w=self.world(extra=(WallEdge('vertical',4,3),),config=GameConfig(forward_speed=2000))
        sc=w.observe('tank-1');w.submit_action('tank-1',dict(keyboard_request(sc,set()),throttle=1));w.step()
        t=w.observe('tank-1')['tanks'][0]
        self.assertLess(t['x'],121)
        self.assertGreater(t['x'],119.5) # rectangle, not the original radius8 wall boundary

    def test_turn_sweep_beside_wall_never_enters_it(self):
        from tank_game.hull import rectangle_clear
        from tank_game.navigation import walls_from_scene
        w=self.world(extra=(WallEdge('vertical',4,3),))
        w._tanks['tank-1']=replace(w._tanks['tank-1'],x=121.5,heading_deg=90)
        for _ in range(35):
            sc=w.observe('tank-1');w.submit_action('tank-1',dict(keyboard_request(sc,set()),turn=-1));w.step()
            t=w._tanks['tank-1']
            self.assertTrue(rectangle_clear(t.x,t.y,t.radius,t.heading_deg,walls_from_scene(sc['map'])))
        self.assertGreater(w._tanks['tank-1'].heading_deg,70)

    def test_public_geometry_restart_and_contract_are_explicit(self):
        from tank_game.contracts import make_run_contract
        from tank_game.episodes import EpisodeSpec, create_world
        w=self.world();sc=w.observe('tank-1')
        self.assertEqual(sc['schema_version'],8)
        self.assertEqual(sc['collision_profile']['id'],'rectangle-v1')
        self.assertIn('wall_contact',sc['self_status'])
        w.restart(allow_active=True)
        self.assertEqual(w.observe('tank-2')['collision_profile'],sc['collision_profile'])
        base=EpisodeSpec(duel=True);rect=replace(base,collision_profile='rectangle')
        self.assertNotEqual(make_run_contract(base).episode_digest,make_run_contract(rect).episode_digest)
        self.assertEqual(create_world(base).observe('tank-1')['schema_version'],6)
        self.assertNotIn('collision_profile',create_world(base).observe('tank-1'))

    def test_predictor_and_real_world_use_same_oriented_shape(self):
        from tank_game.laika_geometry import PublicMaze, check_shot
        outcomes=[]
        for heading in (0,90):
            w=self.world();w._tanks['tank-1']=replace(w._tanks['tank-1'],x=48,y=112)
            w._tanks['tank-2']=replace(w._tanks['tank-2'],x=176,y=119,heading_deg=heading)
            sc=w.observe('tank-1');predicted=check_shot(sc,PublicMaze(sc),sc['tanks'][0],0)
            w.submit_action('tank-1',dict(keyboard_request(sc,set()),fire=True))
            for _ in range(130):w.step()
            actual=not w.observe('tank-2')['self_status']['alive']
            self.assertEqual(predicted.outcome=='hit',actual)
            outcomes.append(actual)
        self.assertEqual(outcomes,[False,True])

    def test_six_negative_cases_survive_with_rectangles_too(self):
        self.world()
        for offset in (0,4,7.5,8,8.5,9):
            with self.subTest(offset=offset):
                w,_,_,_=incoming(offset,'rectangle')
                self.assertTrue(w.observe('tank-1')['self_status']['alive'])

    def test_rectangle_cli_is_explicit_and_other_clocks_stay_native(self):
        import json
        import subprocess
        import sys
        r=subprocess.run([sys.executable,'-m','tank_game','--duel','--strategy','laika',
                          '--collision-profile','rectangle','--inspect'],capture_output=True,text=True,check=False)
        self.assertEqual(r.returncode,0,r.stderr)
        scene=json.loads(r.stdout)
        self.assertEqual(scene['collision_profile']['id'],'rectangle-v1')
        self.assertEqual(scene['rules']['tick_rate'],60)
        self.assertEqual(scene['rules']['forward_speed'],45)
        self.assertEqual(scene['rules']['bullet_speed'],90)

    def test_real_turn_avoids_a_line_that_hits_the_starting_orientation(self):
        from tank_game.hull import first_body_hit
        from tank_game.paths import Segment
        self.world(45)
        # x-offset8.5 crosses the initial diagonal hull but clears its aligned hull.
        line=(Segment(0,1,120.5,80,120.5,150),)
        static=(Segment(0,1,112,112,112,112),)
        self.assertIsNotNone(first_body_hit(line,static,8,45,1.5))
        self.assertIsNone(first_body_hit(line,static,8,90,1.5))
        alive,_,points,requests=incoming(8.5,'rectangle',45)
        self.assertTrue(alive.observe('tank-1')['self_status']['alive'])
        self.assertGreater(sum(r['turn']!=0 for r in requests),0)
        self.assertTrue(all(r['throttle']==0 for r in requests[39:78]))
        self.assertTrue(all((x,y)==(112,112) for x,y,a in points[39:78]))

    def test_moving_and_turning_in_a_corner_remains_wall_clear(self):
        from tank_game.hull import rectangle_clear
        from tank_game.navigation import walls_from_scene
        w=self.world(45,extra=(WallEdge('vertical',4,3),WallEdge('horizontal',3,4)))
        for tick in range(90):
            scene=w.observe('tank-1')
            request=dict(keyboard_request(scene,set()),throttle=1,turn=1 if tick<45 else -1)
            w.submit_action('tank-1',request);w.step()
            t=w._tanks['tank-1']
            self.assertTrue(rectangle_clear(t.x,t.y,t.radius,t.heading_deg,walls_from_scene(scene['map'])))

    def test_public_contact_distinguishes_progressing_slide_from_blockage(self):
        w=self.world(45,extra=(WallEdge('vertical',4,3),))
        saw_slide=False
        for _ in range(35):
            sc=w.observe('tank-1');old=w._tanks['tank-1']
            w.submit_action('tank-1',dict(keyboard_request(sc,set()),throttle=1));w.step()
            status=w.observe('tank-1')['self_status'];new=w._tanks['tank-1']
            if status['wall_contact'] and new.y-old.y>.1:
                saw_slide=True
                self.assertIs(status.get('wall_blocked'),False)
        self.assertTrue(saw_slide)
