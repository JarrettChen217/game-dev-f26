"""Readable keyboard UI using original palette and public scenes only."""
from textwrap import wrap

from tank_game.ui_layout import HELP_BACK, layout_controls, menu_controls


def label(pyxel, x, y, value, color=0, *, scale=1, bold=False):
    if scale == 1 or not hasattr(pyxel, 'Image'):
        pyxel.text(x, y, value, color)
        if bold:
            pyxel.text(x+1, y, value, color)
        return
    mask = pyxel.Image(max(1, len(value)*4), 8)
    mask.text(0, 0, value, 1)
    for sy in range(8):
        for sx in range(len(value)*4):
            if mask.pget(sx, sy):
                pyxel.rect(x+sx*scale, y+sy*scale, scale+(1 if bold else 0), scale, color)


def choice_row(pyxel, x, y, width, value, *, focused, acknowledged):
    color = 3 if acknowledged else 0
    pyxel.rectb(x, y-6, width, 26, color if focused or acknowledged else 5)
    if focused:
        label(pyxel, x+8, y, '>', color, bold=True)
    label(pyxel, x+24, y, value, color, scale=2, bold=focused)


def option_row(pyxel, x, y, width, prefix, options, selected, *, focused, acknowledged):
    color = 3 if acknowledged else 0
    if focused:
        pyxel.rectb(x, y-6, width, 26, color)
        label(pyxel, x+8, y, '>', color, bold=True)
    cursor = x+24
    label(pyxel, cursor, y, prefix, 0, scale=2)
    cursor += len(prefix)*8
    for index, option in enumerate(options):
        if index:
            label(pyxel, cursor, y, ' / ', 5, scale=2)
            cursor += 24
        active = option == selected
        label(pyxel, cursor, y, option, color if active else 5, scale=2, bold=active)
        if active:
            pyxel.rect(cursor, y+14, len(option)*8, 1, color)
        cursor += len(option)*8


def draw_menu(pyxel, ui, keymap, now):
    label(pyxel, (920-len('Tank Maze')*12)//2, 54, 'Tank Maze', scale=3, bold=True)
    label(pyxel, 320, 91, 'Ricochet shots. Avoid every bullet.', 5)
    controls = menu_controls(ui)
    if not ui.selection.bot_enabled:
        label(pyxel, 252, 183, 'Single tank / Fixed map', 5)
    for control in controls:
        x, y, width, height = control.rect
        row = control.focus
        acknowledged = (ui.pressed_control == control.id if ui.pressed_control is not None else
                        ui.pending_result == row or
                        ui.feedback_focus == row and now < ui.feedback_until)
        if row not in ('strength', 'map'):
            choice_row(pyxel, x, y+6, width, control.label, focused=ui.focus == row,
                       acknowledged=acknowledged)
        elif control.operation is None:
            label(pyxel, 276, y+6, control.label, scale=2)
            if ui.focus == row:
                label(pyxel, 260, y+6, '>', bold=True)
                if ui.pointer_focus == control.id:
                    pyxel.rectb(x, y, width, height, 0)
        else:
            selected = (ui.selection.strategy if row == 'strength' else
                        'random' if ui.selection.random_map else 'fixed')
            active = control.value == selected
            focused = ui.focus == row and (ui.pointer_focus == control.id
                      if ui.pointer_focus is not None else active)
            value_ack = acknowledged and (active if ui.pressed_control is None else True)
            color = 3 if value_ack else 0 if active or focused else 5
            label(pyxel, x+4, y+6, control.label, color, scale=2, bold=active or focused)
            if active:
                pyxel.rect(x+4, y+20, len(control.label)*8, 1, color)
            pyxel.rectb(x, y, width, height, color if focused or value_ack else 5)
    description = {'simple': 'Simple: patrol and opportunistic fire.',
                   'hard': 'Hard: pursuit, aiming and evasion.',
                   'laika': 'Laika: goal-driven pursuit, ricochet aim and dodge.',
                   'hybrid': 'Hybrid: learned CPU model (default u19588) / native60Hz.'}[ui.selection.strategy]
    if not ui.tutorial_completed:
        label(pyxel, 252, 346, 'Recommended for first-time players.', 3)
    label(pyxel, 252, 364, description if ui.selection.bot_enabled else 'Practice moving and shooting.', 5)
    if ui.error:
        for i, line in enumerate(wrap(ui.error, 104)[:3]):
            label(pyxel, 252, 375+i*8, line, 8)
    back = 'cancel' if ui.screen == 'starting' else 'select Quit / press again to confirm'
    label(pyxel, 252, 414, f'Arrows: select / Enter: confirm / Esc: {back}', 5)
    exit_hint = ('Starting... / Esc: cancel' if ui.screen == 'starting' else
                 'Click a button / Hold: green / Release inside: confirm')
    label(pyxel, 252, 428, exit_hint, 5)


def draw_help(pyxel, keymap, *, pending=None):
    label(pyxel, (920-len('How to play')*12)//2, 56, 'How to play', scale=3, bold=True)
    rows = ['Turn the tank, then drive forward or backward.',
            'Press fire, release, then press again; holding does not repeat.',
            'Shots bounce off walls and can destroy your own tank.',
            'Slots show how many more shots can be in flight.',
            'Ready means a free slot; a blocked muzzle may still fail.', '']
    rows += [f'{action.replace("_", " ").capitalize()}: {" / ".join(keymap.names(action))}'
             for action in ('forward', 'backward', 'turn_left', 'turn_right', 'fire',
                            'inspection_toggle')]
    rows += ['Esc during play: pause / Esc in Pause: resume',
             'Results: arrows select / Enter release confirms',
             'Start/Results: Esc selects Quit, press again then release to exit']
    y = 108
    for row in rows:
        for line in wrap(row, 104) or ['']:
            label(pyxel, 252, y, line, 0)
            y += 16
    control = HELP_BACK
    x, y, width, _ = control.rect
    choice_row(pyxel, x, y+6, width, control.label, focused=True, acknowledged=pending == 'back')
    label(pyxel, 252, 440, 'Click / Enter / Esc: back', 5)


def board_origin(inspection_visible):
    return (16, 40) if inspection_visible else (204, 40)


def draw_hud(pyxel, scene, *, strategy, seed, keymap, origin, paused=False, match_hud=False):
    x, _y = origin
    duel = scene.get('duel')
    heading = scene.get('presentation_heading') or (f'YOU / BOT - {strategy.capitalize()}' if duel else 'Single tank practice')
    if scene.get('collision_profile'):
        heading += ' / RECT hull'
    if scene.get('rules_profile') == 'laika-original-v1':
        heading += ' / Original'
    label(pyxel, x, 10, heading, scale=2, bold=True)
    if duel:
        remaining = max(0, duel['limit']-duel['elapsed']) if duel['limit'] is not None else None
        timer = f'{remaining:.1f}s' if remaining is not None else f"{scene['rules']['tick_rate']}Hz"
        label(pyxel, x+512-len(timer)*8, 10, timer, scale=2)
    label(pyxel, x, 29, f'Random / Seed:{seed}' if seed is not None else 'Fixed map', 5)
    status = scene['self_status']
    maximum = scene['rules']['max_bullets']
    available = max(0, maximum-status['active_bullets'])
    for i in range(min(maximum, 10)):
        pyxel.rect(x+i*10, 426, 7, 7, 10 if i < available else 5)
    capacity = f'Slots {available}/{maximum}'
    label(pyxel, x+min(maximum, 10)*10+8, 426, capacity)
    ready = 'Destroyed' if not status['alive'] else 'Ready' if status['can_fire'] else 'Wait'
    label(pyxel, x+350, 426, f'Fire: {ready}', 3 if ready == 'Ready' else 5)
    names = lambda action: keymap.names(action)[0]
    exit_hint = ('Esc: resume' if paused else 'Esc: select Quit'
                 if scene['round_status'] == 'GAME_OVER' else 'Esc: pause')
    hint = (f'{names("forward")}/{names("backward")}: drive  '
            f'{names("turn_left")}/{names("turn_right")}: turn  {names("fire")}: fire  '
            f'{names("inspection_toggle")}: information  {exit_hint}')
    if scene.get('presentation_mode') == 'watch':
        hint = (f'Watching {scene.get("presentation_strategy", "Hybrid")} vs Laika / '
                f'{names("inspection_toggle")}: information / {exit_hint}')
    for i, line in enumerate(wrap(hint, 128)[:1 if match_hud else 2]):
        label(pyxel, x, (456 if match_hud else 442)+i*10, line, 5)


def draw_results(pyxel, scene, ui, *, strategy, seed, keymap, origin, now):
    paused = ui.screen == 'pause'
    rows = [('resume', 'Resume')] if paused else []
    rows.append(('retry', 'Retry same map'))
    if seed is not None:
        rows.append(('next_map', 'New map'))
    if not ui.original_rules:
        rows.append(('menu', 'Main menu'))
    rows.append(('quit', 'Quit the Game'))
    height = 112 + len(rows)*28
    x, y = origin[0]+64, origin[1]+(384-height)//2
    pyxel.rect(x, y, 384, height, 7)
    pyxel.rectb(x, y, 384, height, 0)
    result = scene.get('duel', {}).get('result')
    title = ('Paused' if paused else
             {'tank-1': 'You win', 'tank-2': 'Bot wins', 'draw': 'Draw'}.get(result, 'Game over'))
    label(pyxel, x+(384-len(title)*12)//2, y+12, title, scale=3, bold=True)
    detail = (f"{scene.get('presentation_strategy', strategy).capitalize()} / " if 'duel' in scene else '')
    detail += f'Random / Seed:{seed}' if seed is not None else 'Fixed map'
    label(pyxel, x+24, y+40, detail, 5)
    for control in layout_controls(ui, origin=origin):
        x_control, y_control, width, _ = control.rect
        choice_row(pyxel, x_control, y_control+6, width, control.label,
                   focused=ui.focus == control.focus,
                   acknowledged=(ui.pending_result == control.operation
                                 or ui.pressed_control == control.id))
    footer = y+66+len(rows)*28
    label(pyxel, x+24, footer, 'Up/Down: select / Release Enter: confirm', 5)
    shortcuts = ('Esc: resume on release' if paused else
                 'Esc: select Quit / press again, release to exit')
    for i, line in enumerate(wrap(shortcuts, 84)[:2]):
        label(pyxel, x+24, footer+12+i*8, line, 5)
    if seed is not None and not paused:
        label(pyxel, x+24, footer+24, f'{keymap.names("next_map")[0]}: NEXT MAP', 5)
    if ui.error:
        for i, line in enumerate(wrap(ui.error, 120)[:4]):
            label(pyxel, origin[0]+16, y+height+8+i*8, line, 8)
