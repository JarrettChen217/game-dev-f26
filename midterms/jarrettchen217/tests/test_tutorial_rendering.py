"""Lesson UI exposes real bindings/warnings and stays inside the current window."""

import unittest
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from tank_game.keymap import Keymap, load_keymap
from tank_game.tutorial import TutorialSession, make_tutorial_scenario
from tests.test_ui_rendering import FakeWindow

try:
    from tank_game import tutorial_rendering as rendering
except ImportError:
    rendering = None


class TutorialRenderingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(rendering, 'tutorial rendering is missing')
        self.window = FakeWindow()
        self.session = TutorialSession()
        self.addCleanup(self.session.close)
        self.window.tri = lambda *args: None
        self.keys = load_keymap()

    def lesson(self, step, **kwargs):
        self.session.scenario.world.close()
        self.session.scenario = make_tutorial_scenario(step)
        rendering.draw_tutorial(self.window, self.session, self.keys, **kwargs)
        return ' '.join(t[2] for t in self.window.texts)

    def test_custom_fire_without_space_uses_real_binding(self):
        bindings = dict(self.keys.bindings)
        bindings['fire'] = ('F1',)
        self.keys = Keymap(MappingProxyType(bindings), Path('custom keys'))
        text = self.lesson(3)
        self.assertIn('F1', text)
        self.assertNotIn('SPACE', text.upper())
        self.assertIn('TARGET', text)
        self.assertIn('YOU', text)

    def test_long_bindings_keep_essential_copy_visible(self):
        bindings = dict(self.keys.bindings)
        bindings['forward'] = ('LEFTBRACKET', 'RIGHTBRACKET', 'BACKSPACE', 'PAGEDOWN', 'PAGEUP')
        self.keys = replace(self.keys, bindings=MappingProxyType(bindings))
        text = self.lesson(1)
        self.assertIn('LEFTBRACKET', text)
        self.assertIn('RIGHTBRACKET', text)
        self.assertIn('sideways', text)
        self.assertIn('GOAL', text)
        for x, y, value, _ in self.window.texts:
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + 4*len(value), 920)
            self.assertLess(y, 456)

    def test_lesson_copy_precedes_locked_action(self):
        text = self.lesson(4)
        self.assertIn('own shots', text)
        self.assertIn('destroy your tank', text)
        self.assertIn('expected', text)
        self.assertIn('Movement is paused', text)
        self.assertIn('SPACE', text)
        self.assertFalse(self.session.shot_fired)

    def test_expected_death_shows_success_not_game_over(self):
        self.session.phase = 'success'
        text = self.lesson(4)
        self.assertNotIn('Tutorial complete', text)
        self.assertIn('Enter', text)
        self.assertNotIn('Game over', text)
        self.assertNotIn('Bot wins', text)

    def test_success_has_continue_and_complete_has_only_return(self):
        self.session.phase = 'success'
        self.assertIn('Continue', self.lesson(1, focus='advance'))
        self.window.texts.clear()
        self.session.phase = 'complete'
        text = self.lesson(5, focus='return_menu')
        self.assertIn('Return to main menu', text)
        self.assertNotIn('Skip tutorial', text)
        self.assertNotIn('Esc: pause', text)

    def test_modal_layers_hide_duplicate_top_skip(self):
        for phase, paused in (('active', True), ('error', False)):
            self.window.texts.clear()
            self.session.phase = phase
            self.lesson(3, paused=paused)
            self.assertFalse(any(y < 40 and 'Skip tutorial' in value
                                 for _, y, value, _ in self.window.texts))

    def test_error_and_pause_keep_retry_skip_and_keyboard_path_visible(self):
        self.session.phase = 'error'
        text = self.lesson(3)
        self.assertIn('did not finish', text)
        self.assertIn('Retry this step', text)
        self.assertIn('Skip tutorial', text)
        self.assertIn('Enter', text)
        self.window.texts.clear()
        text = self.lesson(2, paused=True)
        for label in ('Paused', 'Resume', 'Retry this step', 'Skip tutorial', 'Esc'):
            self.assertIn(label, text)

    def test_celebration_is_brief_and_only_on_goal_success(self):
        self.session.phase = 'success'
        self.lesson(1, celebration_age=.2)
        confetti = [r for r in self.window.rectangles if r[-1] in (9, 10, 11, 12, 14)
                    and r[2:4] == (3, 3)]
        self.assertGreater(len(confetti), 5)
        self.window.rectangles.clear()
        rendering.draw_tutorial(self.window, self.session, self.keys, celebration_age=1)
        self.assertFalse(any(r[2:4] == (3, 3) for r in self.window.rectangles))
        self.window.rectangles.clear()
        self.session.phase = 'active'
        rendering.draw_tutorial(self.window, self.session, self.keys, celebration_age=.2)
        self.assertFalse(any(r[2:4] == (3, 3) for r in self.window.rectangles))


    def test_compact_goal_confetti_stays_inside_its_actual_map(self):
        self.session.phase = 'success'
        self.lesson(1, celebration_age=.69)
        particles = [r for r in self.window.rectangles if r[2:4] == (3, 3)]
        self.assertTrue(particles)
        for x, y, width, height, _color in particles:
            self.assertGreaterEqual(x, 16)
            self.assertGreaterEqual(y, 40)
            self.assertLessEqual(x+width, 528)
            self.assertLessEqual(y+height, 212)


    def test_ammo_lesson_shows_actual_slots_and_changes_highlight(self):
        from tests.test_tutorial_scenarios import drive
        self.session.scenario = make_tutorial_scenario(5)
        self.session.retry()
        rendering.draw_tutorial(self.window,self.session,self.keys)
        self.assertIn('Tutorial 5/5', ' '.join(t[2] for t in self.window.texts))
        self.assertIn('Free slots 5/5', ' '.join(t[2] for t in self.window.texts))
        drive(self.session, fire=True)
        drive(self.session, count=120)
        self.window.texts.clear()
        self.window.rectangles.clear()
        rendering.draw_tutorial(self.window,self.session,self.keys)
        text=' '.join(t[2] for t in self.window.texts)
        self.assertIn('Free slots 0/5',text)
        self.assertIn('In flight: 5/5',text)
        self.assertTrue(self.session.ammo_changed_slots)
        self.assertGreater(self.session.ammo_flash_seconds,0)
        drive(self.session,count=480)
        self.window.texts.clear()
        rendering.draw_tutorial(self.window,self.session,self.keys)
        self.assertIn('Free slots 1/5',' '.join(t[2] for t in self.window.texts))
        self.assertIn('Expired bullets',' '.join(t[2] for t in self.window.texts))

    def test_hit_lessons_share_native_progress_bar_and_explain_score(self):
        from tank_game.match_hud import settlement_primitives
        from tests.test_tutorial_scenarios import drive
        for step in (3,4):
            self.session.scenario.world.close()
            self.session.scenario=make_tutorial_scenario(step)
            self.session._reset()
            drive(self.session,fire=True)
            while not self.session.scenario.world.hit_events:drive(self.session)
            drive(self.session,count=90)
            before=self.session.scenario.world.observe('tank-1')
            self.window.texts.clear();self.window.rectangles.clear()
            rendering.draw_tutorial(self.window,self.session,self.keys,paused=True)
            text=' '.join(t[2] for t in self.window.texts)
            self.assertIn('1.5s',text)
            self.assertIn('Paused',text)
            self.assertIn('Still-live bullets' if step==3 else 'Self-hit',text)
            expected=settlement_primitives((('tank-1','YOU'),('tank-2','TARGET')),
                                           self.session.round_facts,(16,442,512,14),text_gap=6)
            for kind,*args in expected[:3]:
                if kind=='rect':self.assertIn(tuple(args),self.window.rectangles)
            self.assertEqual(before,self.session.scenario.world.observe('tank-1'))
            drive(self.session,count=90)
            self.window.texts.clear();self.window.rectangles.clear()
            rendering.draw_tutorial(self.window,self.session,self.keys)
            text=' '.join(t[2] for t in self.window.texts)
            self.assertIn('YOU 1 : 0 TARGET' if step==3 else 'YOU 0 | Self-hit: no point',text)
            self.assertFalse(any(r[1]==442 and r[3]==4 for r in self.window.rectangles))
            for x,y,value,_ in self.window.texts:
                self.assertLessEqual(x+4*len(value),920)
                self.assertLessEqual(y+8,464)

    def test_space_is_primary_even_when_third_fire_alias(self):
        bindings=dict(self.keys.bindings)
        bindings['fire']=('F1','F2','SPACE')
        self.keys=replace(self.keys,bindings=MappingProxyType(bindings))
        text=self.lesson(5)
        self.assertIn('SPACE / F1',text)
        self.assertIn('One press',text)

    def test_fifth_completion_shows_all_lessons_finished(self):
        self.session.phase='complete'
        text=self.lesson(5)
        self.assertIn('Tutorial complete',text)
        self.assertIn('Slots refill',text)
        self.assertNotIn('Game over',text)
