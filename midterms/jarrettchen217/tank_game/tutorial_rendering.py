"""Tutorial-only guidance, identity markers and a brief procedural celebration."""

from math import ceil, cos, pi, sin
from textwrap import wrap

from tank_game.firing_status import make_firing_status
from tank_game.firing_status_rendering import draw_firing_status
from tank_game.inspection import scene_geometry
from tank_game.match_hud import score_primitives, settlement_primitives
from tank_game.original_laika.rendering import draw_tank
from tank_game.tutorial import AMMO_DEMO_SHOT_SECONDS, TUTORIAL_STEPS
from tank_game.ui_layout import layout_controls
from tank_game.ui_rendering import choice_row, label

ORIGIN = (16, 40)
SCALE = 2
PANEL_X = 564
AMMO_STATUS_BOUNDS = (564,224,340,188)
CELEBRATION_DURATION = .7
TITLES = ('Meet your tank', 'Navigate a corner', 'Fire a shot', 'Watch the ricochet',
          'Watch your ammo slots')


def skip_button_bounds() -> tuple[int, int, int, int]:
    return 744, 8, 160, 24


def _binding(keymap, action):
    names = keymap.names(action)
    if action == 'fire' and 'SPACE' in names:
        names = ('SPACE',) + tuple(name for name in names if name != 'SPACE')
    # Two usable bindings stay readable even for an unusually long custom list.
    return ' / '.join(names[:2]) + (f' (+{len(names)-2} more)' if len(names) > 2 else '')


def _paragraph(pyxel, text, y, color=0):
    for line in wrap(text, 42):
        label(pyxel, PANEL_X, y, line, color, scale=2)
        y += 16
    return y + 8


def _draw_board(pyxel, session):
    scene = session.scenario.world.observe('tank-1')
    ox, oy = ORIGIN
    maze = scene['map']
    height = 360 if session.step_number in (3, 4) else 384
    scale = min(SCALE,512/maze['width'],height/maze['height'])
    cell = maze['tile_size'] * scale
    for row in range(maze['rows']):
        for column in range(maze['columns']):
            pyxel.rect(ox+column*cell, oy+row*cell, cell, cell,
                       6 if (row+column) % 2 == 0 else 13)
    goal = session.scenario.goal
    if goal is not None:
        x, y = ox+goal.x*scale, oy+goal.y*scale
        pyxel.rectb(x, y, goal.width*scale, goal.height*scale, 3)
        pyxel.rectb(x+2, y+2, goal.width*scale-4, goal.height*scale-4, 3)
        label(pyxel, x+8, y+6, 'GOAL', 3, scale=2, bold=True)
    for primitive in scene_geometry(scene):
        kind, *values = primitive
        if kind == 'wall':
            x, y, width, height = values
            pyxel.rect(ox+x*scale, oy+y*scale, width*scale, height*scale, 5)
        elif kind == 'tank':
            pass  # source hulls below use the exact normal-game renderer
        elif kind == 'bullet':
            x, y, _radius = values
            radius = max(2.,2.5*maze['tile_size']/50)
            pyxel.circ(ox+x*scale, oy+y*scale, radius*scale, 10)
    for tank in scene['tanks']:
        draw_tank(pyxel,tank,origin=ORIGIN,scale=scale)
        player = tank['id'] == 'tank-1'
        x, y = ox+tank['x']*scale, oy+tank['y']*scale
        pyxel.circb(x, y, (tank['radius']+1)*scale, 12 if player else 8)
        label(pyxel, x-8 if player else x-12, y-25, 'YOU' if player else 'TARGET',
              12 if player else 8)
    for effect in scene['effects']:
        progress = effect['progress']
        x, y = ox+effect['x']*scale, oy+effect['y']*scale
        radius = (4+12*progress)*scale
        pyxel.circ(x, y, radius, 9 if progress < .5 else 10)
        pyxel.circb(x, y, radius+2, 8)


def _celebration(pyxel, session, age):
    if (session.phase != 'success' or session.scenario.goal is None
            or age is None or not 0 <= age < CELEBRATION_DURATION):
        return
    goal = session.scenario.goal
    maze = session.scenario.world.observe('tank-1')['map']
    scale = min(SCALE,512/maze['width'],384/maze['height'])
    cx = ORIGIN[0] + (goal.x + goal.width/2)*scale
    cy = ORIGIN[1] + (goal.y + goal.height/2)*scale
    right = ORIGIN[0] + maze['width']*scale - 5
    bottom = ORIGIN[1] + maze['height']*scale - 5
    for i in range(16):
        angle = i * 2*pi/16
        distance = 20 + age * (45 + (i % 3)*12)
        x = cx + cos(angle)*distance
        y = cy + sin(angle)*distance + 26*age*age
        # Clip to the map so confetti never covers guidance/header/controls.
        if ORIGIN[0]+2 <= x <= right and ORIGIN[1]+2 <= y <= bottom:
            pyxel.rect(x, y, 3, 3, (9, 10, 11, 12, 14)[i % 5])


def draw_tutorial(pyxel, session, keymap, *, paused=False, focus='resume', pending=None,
                  celebration_age=None, bullet_offset=0) -> None:
    label(pyxel, 16, 12, f'Tutorial {session.step_number}/{TUTORIAL_STEPS}', scale=2, bold=True)
    controls = layout_controls(None, tutorial_phase=session.phase, tutorial_paused=paused)
    _draw_board(pyxel, session)
    _celebration(pyxel, session, celebration_age)
    label(pyxel, PANEL_X, 52, TITLES[session.step_number-1], scale=2, bold=True)
    y = 86
    phase, step = session.phase, session.step_number
    if phase == 'error':
        y = _paragraph(pyxel, 'The demonstration did not finish as expected.', y, 8)
        y = _paragraph(pyxel, 'Retry this step or skip the tutorial.', y)
    elif phase == 'complete':
        y = _paragraph(pyxel, 'Tutorial complete', y, 3)
        y = _paragraph(pyxel, 'Slots refill when your bullets disappear.', y, 3)
        y = _paragraph(pyxel, 'You can drive, turn, and fire. Watch out for every bullet - even your own.', y)
        y = _paragraph(pyxel, 'You are ready to try a match. Simple is a good first opponent.', y)
        y = _paragraph(pyxel, 'Press Enter to return to the menu.', y, 3)
    elif phase == 'success':
        messages = ('Nice! Turn first, then drive toward your destination.',
                    'Good positioning starts with controlled movement.',
                    'A hit destroys the other tank.',
                    'Your own shots can destroy you. Watch every bullet.')
        y = _paragraph(pyxel, messages[step-1], y, 3)
        y = _paragraph(pyxel, 'Press Enter to continue.', y)
    elif step <= 2:
        y = _paragraph(pyxel, 'You are the tank marked YOU with the blue outline.', y)
        for action, title in (('forward', 'Forward'), ('backward', 'Reverse'),
                              ('turn_left', 'Turn left'), ('turn_right', 'Turn right')):
            y = _paragraph(pyxel, f'{title}: {_binding(keymap, action)}', y)
        if step == 1:
            y = _paragraph(pyxel, 'Left and right turn the tank. They do not move it sideways.', y)
            y = _paragraph(pyxel, 'Drive into the area marked GOAL.', y, 3)
        else:
            y = _paragraph(pyxel, 'Follow the corridor and reach GOAL.', y, 3)
            y = _paragraph(pyxel, 'Touching a wall will not damage your tank.', y)
            # Keep the normal-game boundary legible without another large paragraph.
            label(pyxel, PANEL_X, 416, 'GOAL is a tutorial marker, not a rule in normal matches.', 5)
        label(pyxel, PANEL_X, 438, 'Driving only in this step.', 5)
    elif step == 5:
        capacity = session.config.max_bullets
        y = _paragraph(pyxel, 'Movement is paused for this demonstration.', y)
        if session.ammo_stage == 'ready':
            y = _paragraph(pyxel, f'One press starts {capacity} shots, {AMMO_DEMO_SHOT_SECONDS:.1f}s apart for clarity.', y)
            y = _paragraph(pyxel, f'Press {_binding(keymap, "fire")} to start.', y, 3)
        else:
            messages = {'loading': 'Demo pacing only: normal play has no timed firing cooldown. Release and press to fire again.',
                        'full': 'All slots are occupied. Watch the bullets bounce.',
                        'recharging': 'Expired bullets free your slots.'}
            y = _paragraph(pyxel, messages[session.ammo_stage], y, 3)
        label(pyxel,PANEL_X,196,'Hits or round end can shorten flight.',5)
        label(pyxel,PANEL_X,208,f'{_binding(keymap,"inspection_previous")} / '
              f'{_binding(keymap,"inspection_next")}: bullet pages',5)
    else:
        if step == 3:
            y = _paragraph(pyxel, 'Your tank is already aimed at the target.', y)
        else:
            y = _paragraph(pyxel, 'Bullets bounce off walls, and your own shots can hit you.', y)
            y = _paragraph(pyxel, 'This demonstration will destroy your tank. That is expected.', y, 8)
        y = _paragraph(pyxel, 'Movement is paused for this demonstration.', y)
        y = _paragraph(pyxel, ('Watch the shot bounce back.' if step == 4 else
                               'Watch the shot hit the target.') if session.shot_fired else
                        f'Press {_binding(keymap, "fire")} to fire.', y, 3)
    if step == 5:
        _draw_ammo_slots(pyxel, session)
        if phase=='active':
            scene=session.scenario.world.observe('tank-1')
            draw_firing_status(pyxel,make_firing_status(scene),bounds=AMMO_STATUS_BOUNDS,
                               offset=bullet_offset,scale=2)
    if step in (3, 4):
        _draw_round_hud(pyxel, session)
    footer_y = 456 if step in (3, 4) else 442
    if phase == 'complete':
        label(pyxel, 16, footer_y, 'Enter / Esc: return to main menu', 5)
    else:
        label(pyxel, 16, footer_y, 'Esc: pause / Retry this step or Skip tutorial', 5)
    if paused or phase == 'error':
        rows = [('resume', 'Resume')] if paused else []
        rows += [('retry_step', 'Retry this step'), ('skip_tutorial', 'Skip tutorial')]
        height = 90+len(rows)*32
        x, y = 64, 130
        pyxel.rect(x, y, 416, height, 7)
        pyxel.rectb(x, y, 416, height, 0)
        label(pyxel, x+24, y+16, 'Paused' if paused else 'Try again', scale=2, bold=True)
        label(pyxel, x+24, y+height-24, 'Arrows: select / Release Enter: confirm', 5)
        if paused:
            label(pyxel, x+24, y+height-12, 'Esc: resume on release', 5)
    for control in controls:
        x, y, width, _ = control.rect
        choice_row(pyxel, x, y+6, width, control.label,
                   focused=focus == control.focus or phase == 'complete',
                   acknowledged=pending == control.operation)


def _draw_ammo_slots(pyxel, session):
    scene = session.scenario.world.observe('tank-1')
    capacity = scene['rules']['max_bullets']
    free = capacity - scene['self_status']['active_bullets']
    for index in range(min(capacity, 10)):
        x = 18 + index*18
        pyxel.rect(x, 427, 12, 7, 10 if index < free else 5)
        if session.ammo_flash_seconds > 0 and index in session.ammo_changed_slots:
            pyxel.rectb(x-2, 424, 16, 13, 3 if index < free else 12)
    label(pyxel, 18+min(capacity, 10)*18+12, 426, f'Free slots {free}/{capacity}', 3,
          scale=2, bold=True)


def _draw_round_hud(pyxel, session):
    facts = session.round_facts
    seats = (('tank-1', 'YOU'), ('tank-2', 'TARGET'))
    target_lesson = session.step_number == 3
    if facts.phase == 'settling':
        explanation = ('Target hit! Still-live bullets can change the result.' if target_lesson else
                       'Self-hit: wait for the same round settlement. No point awarded.')
    elif facts.phase == 'finished':
        explanation = ('Round settled: YOU earn one point.' if target_lesson else
                       'Round settled: your own ricochet destroyed YOU. No point awarded.')
    else:
        explanation = 'Scores are confirmed after settlement; live bullets can still hit.'
    label(pyxel, 16, 410, explanation, 5)
    if target_lesson:
        for _kind, *args in score_primitives(seats, session.round_score.points,
                                             (160, 426, 200, 16), scale=2):
            label(pyxel, *args, scale=2, bold=True)
    else:
        label(pyxel, 16, 426, f'YOU {session.round_score.points["tank-1"]} | Self-hit: no point',
              scale=2, bold=True)
    primitives = settlement_primitives(seats, facts, (16, 442, 512, 14), text_gap=6)
    for kind, *args in primitives:
        if kind == 'text' and not target_lesson:
            seconds = ceil(facts.remaining_seconds*10-1e-9)/10
            args = [16, 448, f'Self-hit | settling {seconds:.1f}s | no points', 8]
        getattr(pyxel, kind)(*args)
