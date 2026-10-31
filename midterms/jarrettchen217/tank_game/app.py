"""Pyxel presentation and human input adapter; simulation remains window-free."""

import sys
from pathlib import Path
from textwrap import wrap
from time import monotonic
from types import ModuleType

from tank_game.actions import Action
from tank_game.controllers import BufferedController
from tank_game.firing_status import make_firing_status
from tank_game.firing_status_rendering import bullet_row_capacity, draw_firing_status
from tank_game.inputs import StateKeyboard
from tank_game.inspection import format_inspection, scene_geometry
from tank_game.keymap import load_keymap
from tank_game.match_hud import SessionScore
from tank_game.rendering import PALETTE, SmoothTankRenderer
from tank_game.runner import MatchRunner
from tank_game.runtime_factories import create_desktop_scheduler, create_desktop_window_observer
from tank_game.session import GameSession
from tank_game.tutorial import TutorialSession
from tank_game.tutorial_progress import default_progress_path, load_completed, save_completed
from tank_game.tutorial_rendering import draw_tutorial
from tank_game.ui import MenuSelection, UIState, tutorial_actions
from tank_game.ui_interaction import InteractionFrame, MenuInteraction
from tank_game.ui_layout import layout_controls
from tank_game.ui_rendering import board_origin, draw_help, draw_hud, draw_menu, draw_results
from tank_game.window_contract import WindowSnapshot
from tank_game.world import World

MAP_ORIGIN = (16, 40)
MAP_SCALE = 2
PANEL_X = 552
STATUS_BOUNDS = (564,40,344,180)
JSON_Y = 248


class DrivingApp:
    def __init__(self, pyxel, world: World | None = None, *, keymap_path=None,
                 duel=False, scheduler=None, clock=None, strategy='simple',
                 random_session=None, scheduler_factory=None, menu=False,
                 tutorial_progress_path=None, window_observer=None, collision_profile='circle', game_session=None):
        if (not menu and game_session is None and world is None and random_session is None
                and scheduler is None and collision_profile == 'circle'):
            game_session = GameSession(MenuSelection(duel,strategy,False), scheduler_factory=scheduler_factory)
            scheduler_factory = None  # session owns the only controller factory
        if game_session is not None:
            if menu or world is not None or random_session is not None or scheduler is not None:
                raise ValueError('game_session owns its world and controllers')
            random_session, strategy, duel = game_session.random_session, game_session.strategy, True
        if strategy not in ('simple','hard','laika','hybrid'):

            raise ValueError('select simple, hard, laika or hybrid for a duel')
        self.strategy = strategy
        self.random_session = random_session
        self.scheduler_factory = scheduler_factory
        if random_session is not None and world is not None:
            raise ValueError('random session owns its World')
        if random_session is not None and scheduler is not None and scheduler_factory is None:
            raise ValueError('random-map injected scheduler needs a restart factory')
        self.pyxel = pyxel
        self.ui = UIState()
        self.tutorial_progress_path = (default_progress_path() if tutorial_progress_path is None
                                       else Path(tutorial_progress_path))
        self.ui.tutorial_completed = load_completed(self.tutorial_progress_path)
        self.ui.tutorial_recommended_this_run = menu and not self.ui.tutorial_completed
        if self.ui.tutorial_recommended_this_run:
            self.ui.focus = 'tutorial'
        self._tutorial_completion_recorded = False
        self.session = game_session
        self.tutorial = None
        self.tutorial_focus = 'resume'
        self.tutorial_bullet_offset = 0
        self.bullet_offset = 0
        self.tutorial_celebration_age = None
        self._tutorial_pending = None
        self._tutorial_context = None
        self._tutorial_release_pending = False
        self._menu_release_pending = False
        self._ui_held = set()
        self.interaction = MenuInteraction()
        self.window_observer = window_observer
        self._native_token = None
        self._layout_token = None
        self._native_blocked = False
        self._ui_blocked = False
        self._mouse_was_down = False
        self._pointer_control = None
        self._pointer_consumed = False
        self._confirmation_key = None
        self._closed = False
        self._keymap_path = keymap_path
        if menu and (world is not None or random_session is not None or scheduler is not None):
            raise ValueError('menu owns its session; do not inject an existing world')
        self._clock = monotonic if clock is None else clock
        self.keymap = load_keymap(keymap_path, enable_next_map=random_session is not None, enable_ui=True)
        self.keys = self.keymap.resolve(pyxel)
        release_keys = [pyxel.KEY_RETURN, pyxel.KEY_ESCAPE]
        if (mouse_left := getattr(pyxel, 'MOUSE_BUTTON_LEFT', None)) is not None:
            release_keys.append(mouse_left)
        self.input = StateKeyboard(pyxel, self.keys, release_keys=tuple(release_keys))
        self.controls_hint = ' / '.join(
            f'{self.keymap.names(action)[0]}: {label}' for action, label in
            (('forward', 'forward'), ('backward', 'back'), ('turn_left', 'left'),
             ('turn_right', 'right'), ('fire', 'fire')))
        self.quit_hint = f'{self.keymap.names("quit")[0]}: quit'
        self.inspection_hint = (f'PUBLIC INSPECTION / {self.keymap.names("inspection_previous")[0]}'
                                f' + {self.keymap.names("inspection_next")[0]}')
        self.world = (None if menu else random_session.world if random_session is not None else
                      world if world is not None else World(duel=duel,collision_profile=collision_profile))
        self.is_duel = self.world is not None and 'duel' in self.world.observe('tank-1')
        profile = self.world.observe('tank-1').get('rules_profile') if self.world is not None else None
        self._source60_engine = profile == 'laika-source-60hz-v1'
        self._original_engine = profile in ('laika-original-v1', 'laika-source-60hz-v1')
        self.match_score = (getattr(random_session, 'score', None) or SessionScore(('tank-1', 'tank-2'))
                            if self._source60_engine and self.is_duel else None)
        self.ui.original_rules = self._original_engine and not hasattr(self.world, 'strategy')
        if self._original_engine and (scheduler is not None or scheduler_factory is not None):
            raise ValueError('Original Laika owns its opponent; do not attach another policy')
        self._owns_scheduler = (self.is_duel and not self._original_engine
                                and (scheduler is None or scheduler_factory is not None))
        self.scheduler = (game_session.scheduler if game_session is not None else
                          self._new_scheduler() if self._owns_scheduler else scheduler)
        self.human_controller = self.runner = None
        self._bind_runtime()
        self.scroll = 0
        self.scene = None if self.world is None else self.world.observe('tank-1')
        if not menu:
            self.ui.screen = 'playing'
            self.ui.selection.bot_enabled = self.is_duel
            self.ui.selection.strategy = strategy
            self.ui.selection.random_map = (random_session is not None
                                            and getattr(random_session, 'random_map', True))
        self.lines = []
        self.tank_renderer = SmoothTankRenderer()
        pyxel.init(920, 464, title=(f'Tank maze - {self.strategy.capitalize()} duel'
                           +(' [60Hz SOURCE ADAPTER]' if self._source60_engine else
                             ' [ORIGINAL /25Hz]' if self._original_engine else ' [RECT hull]'
                             if self.world is not None and self.world.observe('tank-1').get('collision_profile') else '')) if self.is_duel
                   else 'Tank maze - single tank', fps=60,
                   quit_key=pyxel.KEY_NONE)
        # Original base colors plus fixed antialias shades; no palette churn.
        pyxel.colors.clear()
        pyxel.colors.extend(PALETTE)
        self._last_update_time = self._clock()
        self._time_bank = 0.0
        self._pending_fire = False
        if self.window_observer is None and isinstance(pyxel, ModuleType):
            self.window_observer = create_desktop_window_observer()
        self._sync_cursor()
        pyxel.run(self.update, self.draw)

    def _bind_runtime(self):
        if self.world is None:
            self.human_controller = self.runner = None
        elif self.session is not None:
            self.human_controller = self.session.controllers['tank-1']
            self.runner = self.session.runner
        else:
            self.human_controller = BufferedController()
            bindings = {'tank-1': self.human_controller}
            if self.scheduler is not None:
                bindings['tank-2'] = self.scheduler
            self.runner = MatchRunner(self.world, bindings)

    def _new_scheduler(self):
        if self.scheduler_factory is not None:
            return self.scheduler_factory()
        return create_desktop_scheduler(self.strategy, frozen=bool(getattr(sys, 'frozen', False)))

    def close(self):
        if not self._closed:
            self._closed = True
            if self.tutorial is not None:
                self.tutorial.close()
            if self.match_score is not None:
                self.match_score.clear()
            if self.session is not None:
                self.session.close()
            else:
                if self.human_controller is not None:
                    self.human_controller.close()
                if self.scheduler is not None:
                    self.scheduler.close()
            if self._source60_engine and self.random_session is not None:
                self.random_session.close()
            else:
                close_world = getattr(self.world, 'close', None)
                if close_world is not None:
                    close_world()

    def _record_source60_result(self):
        if self._source60_engine and self.match_score is not None and not self._closed and self.world is not None:
            from tank_game.laika_60hz.hud import match_facts
            self.match_score.record(match_facts(self.world.presentation_facts()))

    def _reset_round_input(self):
        if self.human_controller is not None:
            self.human_controller.pause(self.world.observe('tank-1'))
        self.scroll = 0
        self.bullet_offset = self.tutorial_bullet_offset = 0
        self._time_bank = 0.0
        self._pending_fire = False
        self._last_update_time = self._clock()
        self.input.wait_for_release = True
        self.input.next_map_enabled = self.random_session is not None

    def _menu_update(self, now):
        self._last_update_time = now
        self._time_bank = 0.0
        if self._menu_release_pending:
            if not self._all_input_down():
                self._menu_release_pending = False
            return
        operation = self._menu_operation(now)
        if operation == 'quit':
            self.close()
            self.pyxel.quit()
        elif operation == 'start':
            self.ui.tutorial_recommended_this_run = False
            try:
                self.keymap.validate_mode(random_map=self.ui.selection.effective()[2])
                candidate = GameSession(self.ui.selection, scheduler_factory=self.scheduler_factory)
            except (ValueError, OSError, RuntimeError) as error:
                self.ui.screen = 'menu'
                self.ui.error = str(error)
                return
            self.session = candidate
            self.world, self.scheduler = candidate.world, candidate.scheduler
            self._bind_runtime()
            self.random_session = candidate.random_session
            self.strategy = candidate.strategy
            self.is_duel = self.ui.selection.bot_enabled
            profile = self.world.observe('tank-1').get('rules_profile')
            self._original_engine = profile in ('laika-original-v1', 'laika-source-60hz-v1')
            self._source60_engine = profile == 'laika-source-60hz-v1'
            self.ui.original_rules = self._original_engine and not hasattr(self.world, 'strategy')
            self.match_score = (getattr(self.random_session, 'score', None)
                                if self._source60_engine else None)
            self._owns_scheduler = False
            self.ui.screen = 'playing'
            self.ui.inspection_visible = False
            self._closed = False
            self._reset_round_input()
            self.scene = self.world.observe('tank-1')
        elif operation == 'tutorial':
            self._start_tutorial()

    def _all_input_down(self):
        keys = {key for group in self.keys.values() for key in group}
        keys.update((self.pyxel.KEY_RETURN, self.pyxel.KEY_ESCAPE))
        mouse = getattr(self.pyxel, 'MOUSE_BUTTON_LEFT', None)
        if mouse is not None:
            keys.add(mouse)
        return any(self.pyxel.btn(key) or self.pyxel.btnp(key) for key in keys)

    def _reset_tutorial_input(self):
        self._reset_round_input()
        self._tutorial_release_pending = True
        self._tutorial_pending = None

    def _start_tutorial(self):
        try:
            candidate = TutorialSession()
        except (ValueError, OSError, RuntimeError) as error:
            self.ui.error = str(error)
            return False
        self.tutorial = candidate
        self._source60_engine = self._original_engine = True
        self.match_score = None
        self.is_duel = False
        self.tutorial_celebration_age = None
        self._tutorial_completion_recorded = False
        self.world = candidate.scenario.world
        self.scene = self.world.observe('tank-1')
        self.ui.screen, self.ui.error = 'tutorial', None
        self.ui.inspection_visible = False
        self.tutorial_focus = 'resume'
        if hasattr(self.pyxel, 'mouse'):
            self.pyxel.mouse(True)
        self._reset_tutorial_input()
        return True

    def _skip_tutorial(self):
        if self.tutorial is not None:
            self.tutorial.close()
        self.tutorial = self.world = self.scene = None
        self.ui.screen, self.ui.focus, self.ui.error = 'menu', 'start', None
        self.ui.tutorial_recommended_this_run = False
        self.ui.pending_result = self.ui.pending_key = None
        self.ui.quit_armed = False
        self._reset_tutorial_input()
        self._menu_release_pending = True

    def _tutorial_operation(self, operation):
        if operation in ('skip_tutorial', 'return_menu'):
            self._skip_tutorial()
            return
        if operation == 'resume':
            self.ui.screen = 'tutorial'
        elif operation in ('retry_step', 'advance'):
            self.tutorial_celebration_age = None
            if operation == 'retry_step':
                self.tutorial.retry()
            else:
                self.tutorial.advance()
            self.world = self.tutorial.scenario.world
            self.scene = self.world.observe('tank-1')
            self.ui.screen = 'tutorial'
        self._reset_tutorial_input()

    def _tutorial_update(self, now):
        pyxel = self.pyxel
        session = self.tutorial
        elapsed = max(0.0, now - self._last_update_time)
        self._last_update_time = now
        paused = self.ui.screen == 'tutorial_pause'
        context = (session.phase, paused)
        rows = tutorial_actions(session.phase, paused=paused)
        if self._tutorial_context != context:
            self.tutorial_focus = rows[0]
            self._tutorial_context = context
        if self.tutorial_celebration_age is not None and not paused:
            self.tutorial_celebration_age += min(elapsed, .25)
        if self._ui_blocked:
            self._time_bank = 0.0
            return
        if self._pointer_control is not None:
            operation = self._pointer_control.operation
            if operation in rows:
                self._tutorial_operation(operation)
            return
        if self._edge(pyxel.KEY_ESCAPE):
            self._time_bank = 0.0
            self._pending_fire = False
            if session.phase == 'complete':
                self._tutorial_pending = ('return_menu', pyxel.KEY_ESCAPE)
            elif paused:
                self._tutorial_pending = ('resume', pyxel.KEY_ESCAPE)
            else:
                self.ui.screen = 'tutorial_pause'
                self.tutorial_focus = 'resume'
                self._reset_tutorial_input()
            return
        if self._tutorial_pending is not None:
            operation, key = self._tutorial_pending
            self._time_bank = 0.0
            if not (pyxel.btn(key) or pyxel.btnp(key)):
                self._tutorial_operation(operation)
            return
        if self._tutorial_release_pending:
            self._time_bank = 0.0
            if not self._all_input_down():
                self._tutorial_release_pending = False
                self.input.wait_for_release = False
            return
        if session.step_number==5:
            from tank_game.tutorial_rendering import AMMO_STATUS_BOUNDS
            capacity=bullet_row_capacity(AMMO_STATUS_BOUNDS,scale=2)
            count=len(self.world.observe('tank-1')['bullets'])
            if self._pressed('inspection_next',15,4):
                self.tutorial_bullet_offset+=capacity
            if self._pressed('inspection_previous',15,4):
                self.tutorial_bullet_offset-=capacity
            self.tutorial_bullet_offset=max(0,min(self.tutorial_bullet_offset,max(0,count-capacity)))
        if paused or session.phase in ('error', 'success', 'complete'):
            self._time_bank = 0.0
            if self.tutorial_focus not in rows:
                self.tutorial_focus = rows[0]
            for key, delta in ((pyxel.KEY_UP, -1), (pyxel.KEY_DOWN, 1)):
                if not self._pointer_consumed and pyxel.btnp(key, 15, 4):
                    index = max(0, min(len(rows)-1, rows.index(self.tutorial_focus)+delta))
                    self.tutorial_focus = rows[index]
                    break
            if not self._pointer_consumed and self._edge(pyxel.KEY_RETURN):
                self._tutorial_pending = (self.tutorial_focus, pyxel.KEY_RETURN)
            return
        scene = self.world.observe('tank-1')
        request, _ = self.input.read(scene)
        if request is not None:
            self._pending_fire |= request['fire']
        dt = 1 / scene['rules']['tick_rate']
        self._time_bank += elapsed
        steps = int((self._time_bank + dt*1e-9) / dt)
        self._time_bank = max(0.0, self._time_bank - steps*dt)
        for _ in range(steps):
            current = self.world.observe('tank-1')
            stamped = (dict(request, observation_tick=current['observation_tick'],
                            round_id=current['round_id'], fire=self._pending_fire)
                       if request is not None else None)
            self._pending_fire = False
            session.tick(stamped)
            if session.phase != 'active':
                if session.phase == 'success' and session.scenario.goal is not None:
                    self.tutorial_celebration_age = 0.0
                self._reset_tutorial_input()
                break
        self.scene = self.world.observe('tank-1')
        if session.phase == 'complete' and not self._tutorial_completion_recorded:
            self._tutorial_completion_recorded = True
            self.ui.tutorial_completed = True
            self.ui.tutorial_recommended_this_run = False
            save_completed(self.tutorial_progress_path)

    def _edge(self, key):
        return key not in self._ui_held and self.pyxel.btnp(key)

    def _menu_operation(self, now):
        if self._ui_blocked:
            return None
        if self._pointer_control is not None:
            c = self._pointer_control
            return self.ui.activate(c.operation, now, value=c.value)
        if self._pointer_consumed:
            return None
        custom_key = next((key for key in self.keys['quit']
                           if key != self.pyxel.KEY_ESCAPE and self._edge(key)), None)
        event, key = 'tick', None
        if self._edge(self.pyxel.KEY_ESCAPE):
            event, key = 'back', self.pyxel.KEY_ESCAPE
        elif self.ui.pending_result is not None:
            held = (self.pyxel.btn(self._confirmation_key)
                    or self.pyxel.btnp(self._confirmation_key))
            event = 'tick' if held else 'release'
        elif custom_key is not None and self.ui.screen != 'pause':
            event, key = 'quit_shortcut', custom_key
        else:
            for name, candidate in (('confirm', self.pyxel.KEY_RETURN),
                                    ('up', self.pyxel.KEY_UP), ('down', self.pyxel.KEY_DOWN),
                                    ('left', self.pyxel.KEY_LEFT), ('right', self.pyxel.KEY_RIGHT)):
                if (self._edge(candidate) if name == 'confirm' else
                        self.pyxel.btnp(candidate, 15, 4)):
                    event, key = name, candidate
                    break
        operation = self.ui.handle(event, now)
        if key is not None and self.ui.pending_result is not None:
            self._confirmation_key = key
        return operation

    def _sync_cursor(self):
        if hasattr(self.pyxel, 'mouse'):
            self.pyxel.mouse(self.tutorial is not None or self.ui.screen not in ('playing', 'dying'))

    def _controls(self):
        return layout_controls(self.ui, tutorial_phase=self.tutorial.phase if self.tutorial else None,
                               tutorial_paused=self.ui.screen == 'tutorial_pause',
                               origin=board_origin(self.ui.inspection_visible))

    def _prepare_ui_input(self):
        p = self.pyxel
        if self.tutorial is not None:
            context = (self.tutorial.phase, self.ui.screen == 'tutorial_pause')
            if self._tutorial_context != context:
                self.tutorial_focus = tutorial_actions(context[0], paused=context[1])[0]
                self._tutorial_context = context
        position = (getattr(p, 'mouse_x', -1), getattr(p, 'mouse_y', -1))
        window = (self.window_observer.sample(p) if self.window_observer else
                  WindowSnapshot(True, ('injected-window',),
                                 0 <= position[0] < 920 and 0 <= position[1] < 464))
        changed = self._native_token is not None and self._native_token != window.viewport_token
        self._native_token = window.viewport_token
        controls = self._controls()
        layout = tuple((c.id, c.rect, c.operation, c.value) for c in controls)
        layout_changed = self._layout_token is not None and self._layout_token != layout
        self._layout_token = layout
        pending = (self.ui.pending_result is not None or self._tutorial_pending is not None
                   or self.interaction.target is not None)
        if changed or not window.focused or layout_changed and pending:
            self.interaction.invalidate()
            self.ui.pending_result = self.ui.pending_key = self._tutorial_pending = None
            self.ui.quit_armed = False
            self.ui.feedback_focus = None
            if self.ui.screen == 'starting':
                self.ui.screen, self.ui.focus = 'menu', 'start'
            self._native_blocked = True
        self._ui_blocked = self._native_blocked
        if self._native_blocked and window.focused and not self._all_input_down():
            self._native_blocked = False
        self._pointer_control = None
        self._pointer_consumed = False
        self.ui.pressed_control = None
        key = getattr(p, 'MOUSE_BUTTON_LEFT', None)
        pressed = key is not None and self._edge(key)
        held = key is not None and p.btn(key)
        released = (key is not None and (p.btnr(key) if hasattr(p, 'btnr') else
                    self._mouse_was_down and not (held or pressed)))
        self._mouse_was_down = bool(held or pressed) and not released
        navigation = next((name for name, k in (('up', p.KEY_UP), ('down', p.KEY_DOWN),
                          ('left', p.KEY_LEFT), ('right', p.KEY_RIGHT)) if p.btnp(k, 15, 4)), None)
        keyboard_busy = (self.ui.pending_result is not None or self._tutorial_pending is not None
                         or self._edge(p.KEY_RETURN) or self._edge(p.KEY_ESCAPE)
                         or any(self._edge(k) for k in self.keys['quit']))
        # Existing keyboard confirmation owns dispatch; a mouse gesture may never
        # coexist with it. Pointer capture blocks new keyboard input until release.
        if (self.interaction.target is None and keyboard_busy) or self._edge(p.KEY_ESCAPE):
            self.interaction.invalidate()
            self.ui.pointer_focus = None
            return
        captured = self.interaction.target is not None
        result = self.interaction.update(InteractionFrame(
            position=position, window=window, pressed=pressed, held=held, released=released,
            navigation=navigation, all_released=not self._all_input_down()), controls,
            context_token=(self.ui.screen, self.tutorial.phase if self.tutorial else None))
        if self._ui_blocked:
            return
        self._pointer_consumed = (captured or self.interaction.target is not None
                                  or result.activate_control is not None)
        if navigation and not self._pointer_consumed:
            self.ui.pointer_focus = None
        by_id = {c.id: c for c in controls}
        if result.focus_control in by_id:
            control = by_id[result.focus_control]
            self.ui.pointer_focus = control.id
            if self.tutorial:
                self.tutorial_focus = control.focus
            else:
                if self.ui.focus != control.focus:
                    self.ui.quit_armed = False
                self.ui.focus = control.focus
        self.ui.pressed_control = result.pressed_control
        if result.activate_control in by_id:
            self._pointer_control = by_id[result.activate_control]

    def update(self):
        before = (self.ui.screen, self.tutorial.phase if self.tutorial else None)
        try:
            self._record_source60_result()
            self._prepare_ui_input()
            self._update()
        finally:
            self._record_source60_result()
            after = (self.ui.screen, self.tutorial.phase if self.tutorial else None)
            if before != after:
                self.interaction.invalidate()
                self.ui.pointer_focus = self.ui.pressed_control = None
                if self.tutorial is not None:
                    paused = self.ui.screen == 'tutorial_pause'
                    self._tutorial_context = (self.tutorial.phase, paused)
                    self.tutorial_focus = tutorial_actions(self.tutorial.phase, paused=paused)[0]
                # A keyboard confirmation can begin in a newly entered Results
                # screen in this update. Its capture belongs to that new layout.
                self._layout_token = tuple((c.id, c.rect, c.operation, c.value)
                                           for c in self._controls())
                if after[0] == 'menu':
                    self._menu_release_pending = self._all_input_down()
            self._sync_cursor()
            keys = (*self.keys['quit'], self.pyxel.KEY_ESCAPE, self.pyxel.KEY_RETURN,
                    getattr(self.pyxel, 'MOUSE_BUTTON_LEFT', None))
            self._ui_held = {key for key in keys
                             if self.pyxel.btn(key) or self.pyxel.btnp(key)}

    def _update(self):
        pyxel = self.pyxel
        if self.tutorial is not None:
            self._tutorial_update(self._clock())
            return
        if self.ui.screen in ('menu', 'help', 'starting'):
            self._menu_update(self._clock())
            return
        if self.ui.screen == 'pause':
            self._results_update(self._clock())
            return
        if self.world.observe('tank-1')['round_status'] == 'GAME_OVER':
            self._results_update(self._clock())
            return
        escape = self._edge(pyxel.KEY_ESCAPE)
        custom_quit = any(self._edge(key) for key in self.keys['quit']
                          if key != pyxel.KEY_ESCAPE)
        if escape or custom_quit:
            self.ui.screen, self.ui.focus = 'pause', 'resume' if escape else 'quit'
            self.ui.pending_result = self.ui.pending_key = None
            self.ui.quit_armed = False
            self.ui.error = None
            self._time_bank = 0.0
            self._pending_fire = False
            self._last_update_time = self._clock()
            self.runner.pause()
            return
        scene = self.world.observe('tank-1')
        now = self._clock()
        elapsed = max(0.0, now-self._last_update_time)
        self._last_update_time = now
        dt = 1/scene['rules']['tick_rate']
        # A bounded fixed-step accumulator decouples play speed from drawing.
        # Long pauses discard excess time rather than teleporting on resume.
        # The60Hz source profile preserves all active elapsed time; pause paths
        # reset the clock separately. Its performance report includes catch-up.
        self._time_bank += elapsed if self._source60_engine else min(elapsed, 15*dt)
        if self.random_session is not None and scene['round_status'] == 'GAME_OVER':
            operation = self.input.read_postgame(scene, allow_next_map=True)
            request, restart = None, bool(operation)
        else:
            request, restart = self.input.read(scene)
            operation = 'retry' if restart else None
        if restart:
            changed = (self.random_session.transition(operation) if self.random_session is not None
                       else self.world.restart())
            if not changed:
                self.scene = self.world.observe('tank-1')
                return
            if self._owns_scheduler:
                self.close()
                self.scheduler = self._new_scheduler()
            self._bind_runtime()
            self.scroll = 0
            self._time_bank = 0.0
            self._pending_fire = False
        else:
            if request is not None:
                self.human_controller.set_input(Action(request['throttle'], request['turn'], request['fire']))
            else:
                self.human_controller.pause(scene)
            available_steps = int((self._time_bank+dt*1e-9)/dt)
            steps = available_steps if self._source60_engine else min(15, available_steps)
            self._time_bank = max(0.0, self._time_bank-steps*dt)
            for _ in range(steps):
                self.runner.tick()
        self.scene = self.world.observe('tank-1')
        if self.scene['round_status'] == 'GAME_OVER':
            self.ui.screen, self.ui.focus = 'results', 'retry'
        elif self.scene['round_status'] == 'DYING':
            self.ui.screen = 'dying'
        self._update_inspection()

    def _update_inspection(self):
        self.lines = [part for line in format_inspection(self.scene)
                      for part in (wrap(line, width=86, replace_whitespace=False,
                                        drop_whitespace=False) or [''])]
        if self._pressed('inspection_toggle'):
            self.ui.inspection_visible = not self.ui.inspection_visible
            self.scroll = 0
            self.bullet_offset = 0
        capacity=bullet_row_capacity(STATUS_BOUNDS)
        maximum=max(0,len(self.scene['bullets'])-capacity)
        self.bullet_offset=max(0,min(self.bullet_offset,maximum))
        if self.ui.inspection_visible and self._pressed("inspection_next", 15, 4):
            if self.bullet_offset<maximum:
                self.bullet_offset=min(maximum,self.bullet_offset+capacity)
            else:
                self.scroll += self.inspection_page_lines
        if self.ui.inspection_visible and self._pressed("inspection_previous", 15, 4):
            if self.scroll:
                self.scroll -= self.inspection_page_lines
            else:
                self.bullet_offset=max(0,self.bullet_offset-capacity)
        self.scroll = max(0, min(self.scroll, max(0, len(self.lines)-self.inspection_page_lines)))

    @property
    def inspection_page_lines(self):
        return (464-JSON_Y-8)//8

    def _results_update(self, now):
        self._last_update_time = now
        self._time_bank = 0.0
        self._pending_fire = False
        paused = self.ui.screen == 'pause'
        if not paused and self.ui.screen != 'results':
            self.ui.screen, self.ui.focus = 'results', 'retry'
        if paused and self.scheduler is not None:
            self.scheduler.worker.poll()  # drain discarded requests; never advance the policy
        if (not paused and not self._ui_blocked and not self._pointer_consumed
                and self.ui.pending_result is None
                and not self._edge(self.pyxel.KEY_ESCAPE)
                and not any(self._edge(key) for key in self.keys['quit'])
                and not self._edge(self.pyxel.KEY_RETURN)
                and self.random_session is not None and self._pressed('next_map')):
            operation = 'next_map'
        else:
            operation = self._menu_operation(now)
        if operation == 'quit':
            self.close()
            self.pyxel.quit()
            return
        if operation == 'resume':
            self.ui.screen = ('dying' if self.scene['round_status'] == 'DYING' else 'playing')
            self.ui.error = None
            self._reset_round_input()
            return
        if operation == 'menu':
            self.close()
            self.world = self.scene = self.scheduler = self.session = self.random_session = None
            self.is_duel = self._owns_scheduler = False
            self._bind_runtime()
            self.ui.screen, self.ui.focus, self.ui.error = 'menu', 'start', None
            self.ui.quit_armed = False
            self.lines = []
            self.scroll = 0
            return
        if operation in ('retry', 'next_map'):
            if (paused and self.scheduler is not None and self.session is None
                    and not self._owns_scheduler):
                self.ui.error = 'Active replay with an injected bot requires scheduler_factory.'
                return
            candidate = None
            try:
                if self.session is not None:
                    changed = self.session.transition(operation, allow_active=paused)
                    self.scheduler = self.session.scheduler
                else:
                    candidate = self._new_scheduler() if self._owns_scheduler else None
                    changed = (self.random_session.transition(operation, allow_active=paused)
                               if self.random_session is not None else self.world.restart(allow_active=paused))
                    if changed and candidate is not None:
                        self.scheduler.close()
                        self.scheduler, candidate = candidate, None
                if not changed:
                    self.ui.error = (self.random_session.last_error if self.random_session else
                                     'Round could not restart.')
                else:
                    self._bind_runtime()
                    self.ui.screen, self.ui.error = 'playing', None
                    self._reset_round_input()
            except (ValueError, OSError, RuntimeError) as error:
                self.ui.error = str(error)
            finally:
                if candidate is not None:
                    candidate.close()
        self.scene = self.world.observe('tank-1')
        self._update_inspection()

    def _pressed(self, action, *repeat):
        return any(self.pyxel.btnp(key, *repeat) for key in self.keys[action])

    def draw(self):
        pyxel = self.pyxel
        pyxel.cls(7)
        if self.tutorial is not None:
            draw_tutorial(pyxel, self.tutorial, self.keymap,
                          paused=self.ui.screen == 'tutorial_pause', focus=self.tutorial_focus,
                          pending=(self._tutorial_pending[0] if self._tutorial_pending else
                                   self.ui.pressed_control),
                          celebration_age=self.tutorial_celebration_age,
                          bullet_offset=self.tutorial_bullet_offset)
            return
        if self.ui.screen in ('menu', 'starting'):
            draw_menu(pyxel, self.ui, self.keymap, self._clock())
            return
        if self.ui.screen == 'help':
            draw_help(pyxel, self.keymap, pending=self.ui.pressed_control or self.ui.pending_result)
            return
        ox, oy = board_origin(self.ui.inspection_visible)
        alpha = 1 if self.ui.screen in ('pause','results') else self._time_bank*25
        scene = (self.world.render_scene(alpha) if self._original_engine and not self._source60_engine
                 else self.scene)
        seed = (self.random_session.record.seed if self.random_session is not None
                and getattr(self.random_session, 'random_map', True) else None)
        draw_hud(pyxel, scene, strategy=self.strategy, seed=seed,
                 keymap=self.keymap, origin=(ox, oy), paused=self.ui.screen == 'pause',
                 match_hud=self._source60_engine and self.is_duel)
        if self._source60_engine and self.match_score is not None:
            from tank_game.laika_60hz.hud import draw_match_hud, match_facts
            draw_match_hud(pyxel, match_facts(self.world.presentation_facts()), self.match_score,
                           origin=(ox, oy), seats=getattr(self.world, 'presentation_seats',
                                                         (('tank-1', 'YOU'), ('tank-2', 'Laika'))))
        maze = scene['map']
        scale = (min(MAP_SCALE,512/maze['width'],384/maze['height']) if self._original_engine
                 else MAP_SCALE)
        cell = maze['tile_size'] * scale
        for row in range(maze['rows']):
            for column in range(maze['columns']):
                pyxel.rect(ox + column * cell, oy + row * cell, cell, cell,
                           6 if (row + column) % 2 == 0 else 13)
        for primitive in scene_geometry(scene):
            kind, *values = primitive
            if kind == 'wall':
                x, y, width, height = values
                pyxel.rect(ox + x * scale, oy + y * scale,
                           width * scale, height * scale, 5)
            elif kind == 'tank':
                if not self._original_engine:
                    self.tank_renderer.draw(pyxel, tuple(values), origin=(ox, oy), scale=scale)
            elif kind == 'bullet':
                x, y, radius = values
                if self._original_engine:
                    radius = max(2.,2.5*maze['tile_size']/50)
                pyxel.circ(ox + x * scale, oy + y * scale, radius * scale, 10)
        if self._original_engine:
            from tank_game.original_laika.rendering import draw_tank
            for tank in scene['tanks']:
                draw_tank(pyxel,tank,origin=(ox,oy),scale=scale)
        if self.is_duel:
            for tank in scene['tanks']:
                player = tank['id'] == 'tank-1'
                x, y = ox+tank['x']*scale, oy+tank['y']*scale
                pyxel.circb(x, y, (tank['radius']+1)*scale, 12 if player else 8)
                pyxel.text(x-8, y-25, dict(getattr(self.world, 'presentation_seats',
                             (('tank-1', 'YOU'), ('tank-2', 'BOT'))))[tank['id']], 12 if player else 8)
        phase = scene['round_status']
        for effect in scene['effects']:
            progress = effect['progress']
            x, y = ox + effect['x'] * scale, oy + effect['y'] * scale
            radius = (4 + 12 * progress) * scale
            pyxel.circ(x, y, radius, 9 if progress < .5 else 10)
            pyxel.circb(x, y, radius + 2, 8)
        if phase == 'GAME_OVER' or self.ui.screen == 'pause':
            draw_results(pyxel, self.scene, self.ui, strategy=self.strategy, seed=seed,
                         keymap=self.keymap, origin=(ox, oy), now=self._clock())
        if self.ui.inspection_visible:
            pyxel.rect(PANEL_X, 0, 368, 464, 1)
            pyxel.text(PANEL_X + 12, 12, self.inspection_hint, 10)
            draw_firing_status(pyxel,make_firing_status(self.scene),bounds=STATUS_BOUNDS,
                               offset=self.bullet_offset)
            pyxel.text(PANEL_X + 12,224,'Hits or round end can shorten flight.',6)
            end = min(self.scroll + self.inspection_page_lines, len(self.lines))
            pyxel.text(PANEL_X + 12, 232, f'JSON Lines {self.scroll + 1}-{end}'
                       f' of {len(self.lines)} / {phase}', 6)
            for index, line in enumerate(self.lines[self.scroll:end]):
                pyxel.text(PANEL_X + 12, JSON_Y + index * 8, line, 7)


def main(*, duel=False, strategy='simple', random_session=None, menu=False,collision_profile='circle', game_session=None):
    import pyxel

    app = DrivingApp(pyxel, duel=duel, strategy=strategy, random_session=random_session, menu=menu,collision_profile=collision_profile, game_session=game_session)
    app.close()
