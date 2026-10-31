"""Public timer panels explain waits, bound drawing, and retain existing input."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tank_game.app import DrivingApp
from tank_game.config import GameConfig
from tank_game.entities import BulletState
from tank_game.tutorial import TutorialSession, make_tutorial_scenario
from tank_game.tutorial_rendering import draw_tutorial
from tank_game.world import World
from tests.test_driving import open_map
from tests.test_shooting import request
from tests.test_tutorial_scenarios import drive
from tests.test_ui_rendering import FakeWindow

try:
    from tank_game.firing_status import make_firing_status
    from tank_game.firing_status_rendering import draw_firing_status
except ImportError:
    make_firing_status = draw_firing_status = None


def bullets(world, count):
    world._bullets = tuple(BulletState(f'bullet-{i}',200,150+i%5,90,0,
                                      owner_id='tank-1',age=i/4)
                           for i in range(count,0,-1))


class FiringStatusTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(make_firing_status, 'public firing status view is missing')
        self.assertIsNotNone(draw_firing_status, 'shared firing status renderer is missing')

    def test_full_and_cooling_reasons_and_positive_rounding(self):
        world=World(open_map())
        bullets(world,5)
        world._tanks['tank-1']=replace(world._tanks['tank-1'],cooldown_remaining=.001)
        status=make_firing_status(world.observe('tank-1'))
        self.assertEqual(status.free_slots,0)
        self.assertEqual([b.id for b in status.bullets], [f'bullet-{i}' for i in range(1,6)])
        window=FakeWindow()
        draw_firing_status(window,status,bounds=(564,224,340,188),scale=2)
        text=' '.join(t[2] for t in window.texts)
        for value in ('Slots full','cooling down','0.01 s','5/5','0/5'):
            self.assertIn(value,text)
        world._tanks['tank-1']=replace(world._tanks['tank-1'],cooldown_remaining=0)
        window.texts.clear()
        draw_firing_status(window,make_firing_status(world.observe('tank-1')),
                           bounds=(564,224,340,188),scale=2)
        text=' '.join(t[2] for t in window.texts)
        self.assertIn('Waiting for a bullet',text)
        self.assertIn('0.00 s',text)

    def test_all_ten_rows_bars_and_small_bounds_are_safe(self):
        world=World(open_map(),GameConfig(max_bullets=10))
        bullets(world,10)
        world._bullets=(replace(world._bullets[0],id='a-very-long-projectile-identifier'*5),
                        *world._bullets[1:])
        for bounds,scale in (((564,40,344,180),1),((0,0,160,110),1),((20,20,24,16),2)):
            with self.subTest(bounds=bounds):
                w=FakeWindow()
                status=make_firing_status(world.observe('tank-1'))
                capacity=draw_firing_status(w,status,bounds=bounds,scale=scale)
                x,y,width,height=bounds
                for tx,ty,s,_ in w.texts:
                    self.assertGreaterEqual(tx,x)
                    self.assertGreaterEqual(ty,y)
                    self.assertLessEqual(tx+len(s)*4*scale,x+width)
                    self.assertLessEqual(ty+8*scale,y+height)
                for rx,ry,rw,rh,_ in w.rectangles:
                    self.assertGreaterEqual(rx,x)
                    self.assertGreaterEqual(ry,y)
                    self.assertLessEqual(rx+rw,x+width)
                    self.assertLessEqual(ry+rh,y+height)
                if scale==1 and width==344:
                    self.assertGreaterEqual(capacity,10)
                    self.assertIn('10/10',' '.join(t[2] for t in w.texts))
                    bars=[r for r in w.rectangles if r[-1]==10 and r[3]==4]
                    self.assertEqual(len(bars),10)
                    self.assertGreater(len({r[2] for r in bars}),1)

    def test_terminal_marks_round_ended_without_inventing_a_countdown(self):
        world=World(open_map())
        bullets(world,1)
        world._round_status='DYING'
        scene=world.observe('tank-1')
        w=FakeWindow()
        draw_firing_status(w,make_firing_status(scene),bounds=(564,40,344,180))
        self.assertIn('Round ended',' '.join(t[2] for t in w.texts))
        self.assertEqual(scene,world.observe('tank-1'))

    def test_ready_is_eligibility_even_when_muzzle_is_blocked(self):
        world=World()
        world._tanks['tank-1']=replace(world._tanks['tank-1'],x=54.9,y=16)
        request(world,True)
        self.assertEqual(world.observe('tank-1')['bullets'],[])
        status=make_firing_status(world.observe('tank-1'))
        self.assertTrue(status.can_fire)
        self.assertEqual(status.cooldown_remaining,0)
        self.assertIn('clear muzzle',status.reasons[0])


class FiringPanelIntegrationTests(unittest.TestCase):
    def test_tutorial_paging_while_paused_and_retry_preserve_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            w=FakeWindow()
            app=DrivingApp(w,menu=True,clock=w.clock,
                           tutorial_progress_path=Path(directory)/'progress.json')
            self.addCleanup(app.close)
            app._start_tutorial()
            app.tutorial.scenario.world.close()
            app.tutorial.scenario=make_tutorial_scenario(5)
            app.tutorial._reset()
            app.world=app.tutorial.scenario.world
            from tests.test_tutorial_scenarios import drive
            drive(app.tutorial,fire=True);drive(app.tutorial,count=120)
            app.scene=app.world.observe('tank-1')
            app._reset_tutorial_input()
            app.update()  # release barrier
            app.ui.screen='tutorial_pause'
            before=app.world.observe('tank-1')
            w.pressed={'pgdn'}
            app.update()
            app.draw()
            self.assertIn('#5',' '.join(t[2] for t in w.texts))
            self.assertEqual(app.world.observe('tank-1'),before)
            app._tutorial_operation('retry_step')
            w.texts.clear()
            app.draw()
            self.assertEqual(app.tutorial_bullet_offset,0)
            self.assertIn('No bullets in flight',' '.join(t[2] for t in w.texts))
            self.assertFalse((Path(directory)/'progress.json').exists())

    def test_normal_inspection_keeps_json_below_summary_and_pages_overflow(self):
        w=FakeWindow()
        world=World(open_map(),GameConfig(max_bullets=30))
        bullets(world,25)
        app=DrivingApp(w,world,clock=w.clock)
        self.addCleanup(app.close)
        app.ui.inspection_visible=True
        app._update_inspection()
        app.draw()
        self.assertIn('Cooldown',' '.join(t[2] for t in w.texts))
        self.assertIn('Hits or round end can shorten flight.',
                      ' '.join(t[2] for t in w.texts))
        self.assertTrue(any(y>=248 and 'schema_version' in s for _,y,s,_ in w.texts)
                        or any(y>=248 and '{' in s for _,y,s,_ in w.texts))
        seen=' '.join(t[2] for t in w.texts)
        for _ in range(4):
            w.pressed={'pgdn'}
            app.update()
            w.texts.clear()
            app.draw()
            seen+=' '+' '.join(t[2] for t in w.texts)
            if app.scroll:break
        for i in range(1,26):self.assertIn(f'#{i} ',seen)
        self.assertGreater(app.scroll,0)
        world._bullets=()
        w.pressed=set()
        app.update()
        self.assertEqual(app.bullet_offset,0)
        self.assertLessEqual(app.scroll,max(0,len(app.lines)-app.inspection_page_lines))

    def test_lesson_five_shows_distinct_lifetimes_and_released_slot(self):
        session=TutorialSession()
        self.addCleanup(session.close)
        session.scenario.world.close()
        session.scenario=make_tutorial_scenario(5)
        session.retry()
        drive(session,fire=True)
        drive(session,count=121)
        w=FakeWindow()
        from tank_game.keymap import load_keymap
        draw_tutorial(w,session,load_keymap())
        text=' '.join(t[2] for t in w.texts)
        for i in range(1,6):self.assertIn(f'#{i}',text)
        self.assertIn('Waiting for a bullet',text)
        self.assertEqual(len({b['remaining_lifetime'] for b in
                              session.scenario.world.observe('tank-1')['bullets']}),5)
        for x,y,s,_ in w.texts:
            self.assertLessEqual(x+4*len(s),920)
            self.assertLess(y,456)
        drive(session,count=15)
        w.texts.clear()
        draw_tutorial(w,session,load_keymap())
        self.assertIn('Waiting for a bullet',' '.join(t[2] for t in w.texts))
        drive(session,count=464)
        w.texts.clear()
        draw_tutorial(w,session,load_keymap())
        self.assertIn('Free slots 1/5',' '.join(t[2] for t in w.texts))
        self.assertNotIn('#1 ', ' '.join(t[2] for t in w.texts))
