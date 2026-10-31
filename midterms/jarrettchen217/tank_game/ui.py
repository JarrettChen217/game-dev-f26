"""Keyboard presentation model; never mutates the simulation."""
from dataclasses import dataclass


@dataclass
class MenuSelection:
    bot_enabled: bool = True
    strategy: str = 'simple'
    random_map: bool = True

    def effective(self):
        if type(self.bot_enabled) is not bool or type(self.random_map) is not bool:
            raise ValueError('bot and map selections must be booleans')
        if self.strategy not in ('simple', 'hard', 'laika', 'hybrid'):
            raise ValueError('choose Simple, Hard, Laika or Hybrid')
        return self.bot_enabled, self.strategy, self.random_map and self.bot_enabled


def result_actions(random_map):
    return ('retry', 'next_map', 'menu', 'quit') if random_map else ('retry', 'menu', 'quit')


def tutorial_actions(phase: str, *, paused: bool) -> tuple[str, ...]:
    if phase == 'complete':
        return ('return_menu',)
    if paused:
        return ('resume', 'retry_step', 'skip_tutorial')
    return {'active': ('skip_tutorial',), 'success': ('advance', 'skip_tutorial'),
            'error': ('retry_step', 'skip_tutorial')}[phase]


class UIState:
    def __init__(self):
        self.screen = 'menu'
        self.selection = MenuSelection()
        self.focus = 'start'
        self.tutorial_completed = False
        self.tutorial_recommended_this_run = False
        self.inspection_visible = False
        self.original_rules = False
        self.feedback_until = 0.0
        self.feedback_focus = None
        self.error = None
        self.pending_result = None
        self.pending_key = None
        self.quit_armed = False
        self.pointer_focus = None
        self.pressed_control = None

    def rows(self):
        if self.screen in ('results', 'pause'):
            actions = result_actions(self.selection.effective()[2])
            if self.original_rules:
                actions = tuple(action for action in actions if action != 'menu')
            return ('resume',) + actions if self.screen == 'pause' else actions
        return (('tutorial', 'bot', 'strength', 'map', 'start', 'help', 'quit')
                if self.selection.bot_enabled else ('tutorial', 'bot', 'start', 'help', 'quit'))

    def acknowledge(self, now):
        self.feedback_until = now + .12
        self.feedback_focus = self.focus

    def activate(self, operation, now, *, value=None):
        """Execute a finalized semantic operation, independent of input device."""
        if self.screen == 'help' and operation == 'back':
            self.screen, self.focus = 'menu', 'help'
            return None
        if operation not in self.rows() or self.screen not in ('menu', 'pause', 'results'):
            return None
        self.focus, self.quit_armed, self.error = operation, False, None
        self.acknowledge(now)
        if operation == 'bot':
            self.selection.bot_enabled = not self.selection.bot_enabled if value is None else value
        elif operation == 'strength':
            if value in ('simple', 'hard', 'laika', 'hybrid'):
                self.selection.strategy = value
        elif operation == 'map':
            if value in ('fixed', 'random'):
                self.selection.random_map = value == 'random'
        elif operation == 'start':
            self.screen = 'starting'
        elif operation == 'help':
            self.screen, self.focus = 'help', 'back'
        else:
            return operation
        return None

    def handle(self, event, now):
        if self.screen == 'help':
            if event == 'back':
                self.pending_result = self.pending_key = None
                self.activate('back', now)
            elif event == 'confirm':
                self.pending_result, self.pending_key = 'back', 'confirm'
            elif event == 'release' and self.pending_result == 'back':
                self.pending_result = self.pending_key = None
                self.activate('back', now)
            return None
        if self.screen == 'starting':
            if event == 'back':
                self.screen, self.focus = 'menu', 'start'
            elif event == 'tick' and now >= self.feedback_until:
                return 'start'
            return None
        if event in ('back', 'quit_shortcut'):
            self.pending_result = self.pending_key = None
            if self.screen == 'pause' and event == 'back':
                self.focus = 'resume'
                self.pending_result, self.pending_key = 'resume', event
                self.acknowledge(now)
            elif self.quit_armed and self.focus == 'quit':
                self.pending_result, self.pending_key = 'quit', event
                self.acknowledge(now)
            else:
                self.focus, self.quit_armed = 'quit', True
                self.feedback_focus = None
            return None
        if self.pending_result is not None:
            if event == 'release':
                operation = self.pending_result
                self.pending_result = self.pending_key = None
                self.quit_armed = False
                self.feedback_until = now
                return self.activate(operation, now)
            return None
        rows = self.rows()
        if self.focus not in rows:
            self.focus = rows[0]
        if event in ('up', 'down'):
            self.quit_armed = False
            index = rows.index(self.focus) + (-1 if event == 'up' else 1)
            self.focus = rows[max(0, min(index, len(rows)-1))]
        elif event in ('left', 'right', 'confirm'):
            self.quit_armed = False
            if self.screen in ('results', 'pause'):
                if event == 'confirm':
                    self.acknowledge(now)
                    self.pending_result, self.pending_key = self.focus, 'confirm'
                return None
            if self.focus == 'bot':
                self.activate('bot', now, value=(not self.selection.bot_enabled if event == 'confirm'
                                                else event == 'right'))
            elif self.focus == 'strength':
                if event != 'confirm':
                    choices = ('simple', 'hard', 'laika', 'hybrid')
                    index = choices.index(self.selection.strategy) + (-1 if event == 'left' else 1)
                    self.activate('strength', now, value=choices[max(0,min(index,len(choices)-1))])
            elif self.focus == 'map':
                if event != 'confirm':
                    self.activate('map', now, value='random' if event == 'right' else 'fixed')
            elif event == 'confirm':
                if self.focus == 'tutorial':
                    self.pending_result, self.pending_key = 'tutorial', 'confirm'
                elif self.focus == 'start':
                    self.activate('start', now)
                elif self.focus == 'help':
                    self.activate('help', now)
                elif self.focus == 'quit':
                    self.pending_result, self.pending_key = 'quit', 'confirm'
            self.error = None
            self.acknowledge(now)
        return None
