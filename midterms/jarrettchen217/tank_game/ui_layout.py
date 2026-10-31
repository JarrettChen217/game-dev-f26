"""Logical rectangles shared by drawing and menu hit testing."""
from dataclasses import dataclass

from tank_game.ui import tutorial_actions


@dataclass(frozen=True)
class Control:
    id: str
    rect: tuple[int, int, int, int]
    focus: str
    operation: str | None
    value: str | bool | None = None
    label: str = ''

    def contains(self, point):
        x, y, w, h = self.rect
        return x <= point[0] < x+w and y <= point[1] < y+h


HELP_BACK = Control('back', (228, 402, 464, 26), 'back', 'back', label='Back')


def menu_controls(ui):
    labels = {'tutorial': 'Replay tutorial' if ui.tutorial_completed else 'Tutorial',
              'bot': f'[{"x" if ui.selection.bot_enabled else " "}] Enable bot',
              'start': 'Start game', 'help': 'How to play', 'quit': 'Quit the Game'}
    controls = []
    for i, row in enumerate(ui.rows()):
        y = 126+i*32+(12 if not ui.selection.bot_enabled and i > 0 else 0)
        if row not in ('strength', 'map'):
            controls.append(Control(row, (228, y-6, 464, 26), row, row, label=labels[row]))
            continue
        prefix = 'Bot strength: ' if row == 'strength' else 'Map: '
        cursor = 276+len(prefix)*8
        controls.append(Control(row+':label', (252, y-6, cursor-256, 26), row, None,
                                label=prefix))
        for value in (('simple', 'hard', 'laika', 'hybrid') if row == 'strength' else ('fixed', 'random')):
            label = value.capitalize()
            controls.append(Control(row+':'+value, (cursor-4, y-6, len(label)*8+8, 26),
                                    row, row, value, label))
            cursor += len(label)*8+24
    return tuple(controls)


def layout_controls(ui, *, tutorial_phase=None, tutorial_paused=False, origin=(204, 40)):
    if tutorial_phase is not None:
        actions = tutorial_actions(tutorial_phase, paused=tutorial_paused)
        if tutorial_phase == 'complete':
            return (Control('return_menu', (540, 340, 364, 26), 'return_menu', 'return_menu',
                            label='Return to main menu'),)
        if tutorial_paused or tutorial_phase == 'error':
            labels = {'resume': 'Resume', 'retry_step': 'Retry this step',
                      'skip_tutorial': 'Skip tutorial'}
            return tuple(Control(a, (80, 176+i*32, 384, 26), a, a, label=labels[a])
                         for i, a in enumerate(actions))
        skip = Control('skip_tutorial', (744, 8, 160, 24), 'skip_tutorial', 'skip_tutorial',
                       label='Skip tutorial')
        return ((Control('advance', (540, 340, 364, 26), 'advance', 'advance',
                         label='Continue'), skip) if tutorial_phase == 'success' else (skip,))
    if ui.screen == 'menu':
        return menu_controls(ui)
    if ui.screen == 'help':
        return (HELP_BACK,)
    if ui.screen in ('pause', 'results'):
        rows = ui.rows()
        height = 112+len(rows)*28
        x, y = origin[0]+64, origin[1]+(384-height)//2
        labels = {'resume': 'Resume', 'retry': 'Retry same map', 'next_map': 'New map',
                  'menu': 'Main menu', 'quit': 'Quit the Game'}
        return tuple(Control(a, (x+16, y+60+i*28, 352, 26), a, a, label=labels[a])
                     for i, a in enumerate(rows))
    return ()
