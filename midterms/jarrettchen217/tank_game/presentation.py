"""Detached display poses between completed ticks; never controller observations."""


def interpolate_scene(previous: dict | None, current: dict, alpha: float) -> dict:
    """Lag by one tick instead of predicting physics or running extra decisions.

    Discontinuities use current authoritative state immediately. In particular,
    projectile reflection endpoints do not describe the path around a corner;
    snapping that one tick is safer than drawing an invented wall-crossing chord.
    New/deleted entities also appear/disappear immediately, without ghost poses.
    This projection is for original tank/bullet art, not hit-shape inspection.
    """
    if (previous is None or current['round_status'] != 'PLAYING'
            or previous['round_status'] != 'PLAYING'
            or previous['round_id'] != current['round_id']
            or previous['observation_tick'] + 1 != current['observation_tick']
            or previous['map'] != current['map']
            or {t['id'] for t in previous['tanks']} != {t['id'] for t in current['tanks']}):
        return current
    alpha = max(0.0, min(1.0, alpha))
    old_tanks = {t['id']: t for t in previous['tanks']}
    tanks = []
    for tank in current['tanks']:
        old = old_tanks[tank['id']]
        turn = (tank['heading_deg'] - old['heading_deg'] + 180) % 360 - 180
        tanks.append(dict(tank,
            x=old['x'] + (tank['x'] - old['x']) * alpha,
            y=old['y'] + (tank['y'] - old['y']) * alpha,
            heading_deg=(old['heading_deg'] + turn * alpha) % 360))
    old_bullets = {b['id']: b for b in previous['bullets']}
    before = previous.get('research', {}).get('bullets', {})
    after = current.get('research', {}).get('bullets', {})
    bullets = []
    for bullet in current['bullets']:
        old = old_bullets.get(bullet['id'])
        reflected = (before.get(bullet['id'], {}).get('bounces')
                     != after.get(bullet['id'], {}).get('bounces'))
        if (old is None or reflected or old['vx'] != bullet['vx'] or old['vy'] != bullet['vy']):
            bullets.append(bullet)
        else:
            bullets.append(dict(bullet,
                x=old['x'] + (bullet['x'] - old['x']) * alpha,
                y=old['y'] + (bullet['y'] - old['y']) * alpha))
    return dict(current, tanks=tanks, bullets=bullets)
