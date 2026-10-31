"""The six observed failures must survive, not merely select a dodge goal."""
import unittest

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.entities import BulletState
from tank_game.laika import LaikaPolicy
from tank_game.map import Spawn
from tests.test_duel import duel


def incoming(offset, profile='circle', heading=90):
    w=duel(a=Spawn(112,112,heading),b=Spawn(272,272,180),
           **({} if profile=='circle' else {'collision_profile':profile}))
    p=LaikaPolicy();s=AgentScheduler(InlineWorker(p),decision_hz=20)
    positions=[];requests=[]
    for tick in range(140):
        if tick==36:w._bullets=(BulletState('bullet-1',112+offset,40,0,90,radius=1.5,owner_id='tank-2'),)
        scene=w.observe('tank-1');scene['self_status']['can_fire']=False
        requests.append(s.request(scene))
        w.submit_action('tank-1',requests[-1]);w.step()
        own=next((t for t in w.observe('tank-1')['tanks'] if t['id']=='tank-1'),None)
        if own:positions.append((own['x'],own['y'],own['heading_deg']))
        if w.observe('tank-1')['round_status']!='PLAYING':break
    s.close()
    return w,p,positions,requests


class DodgeRepairTests(unittest.TestCase):
    def test_six_native_circle_negative_fixtures_survive(self):
        for offset in (0,4,7.5,8,8.5,9):
            with self.subTest(offset=offset):
                w,_,_,_=incoming(offset)
                self.assertTrue(w.observe('tank-1')['self_status']['alive'])
                self.assertEqual(w.rejected_actions,0)

    def test_equal_distance_matches_reference_second_point(self):
        w=duel(a=Spawn(112,112,0),b=Spawn(272,272,180))
        sc=w.observe('tank-1');sc['bullets']=[{'id':'bullet-1','x':112,'y':40,'vx':0,'vy':90,'radius':1.5,'remaining_lifetime':8}]
        p=LaikaPolicy();p.decide(sc);tank=sc['tanks'][0]
        p.goal=p._dodge(sc,tank);p._build_actions(sc,tank)
        self.assertEqual(p.actions[-1].data[:2],(128,112))

    def test_dodge_position_does_not_stop_inside_native_hit_radius(self):
        w,_,points,_=incoming(0)
        self.assertTrue(w.observe('tank-1')['self_status']['alive'])
        self.assertGreater(max(abs(x-112) for x,y,a in points),9.5)

    def test_escape_stops_when_clear_instead_of_chasing_a_subpixel_point(self):
        w=duel(a=Spawn(112,112,0),b=Spawn(272,272,180))
        w._bullets=(BulletState('bullet-1',112,40,0,90,radius=1.5,owner_id='tank-2'),)
        sc=w.observe('tank-1');p=LaikaPolicy();p.decide(sc)
        p.goal=p._dodge(sc,sc['tanks'][0]);p.goal.period=10
        p._build_actions(sc,sc['tanks'][0]);s=AgentScheduler(InlineWorker(p),decision_hz=20)
        self.addCleanup(s.close)
        stopped=False
        for tick in range(25):
            scene=w.observe('tank-1');req=s.request(scene)
            if tick>=18 and abs(scene['tanks'][0]['x']-112)>9.875:
                self.assertEqual(req['throttle'],0)
                stopped=True;break
            w.submit_action('tank-1',req);w.step()
        self.assertTrue(stopped)
