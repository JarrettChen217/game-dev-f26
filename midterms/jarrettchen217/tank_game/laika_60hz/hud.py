"""Source60Hz host facts to the unchanged portable HUD contract."""
from tank_game.match_hud import (
    SCORE_FONT_SCALE,
    SETTLEMENT_BAR_OFFSET,
    SETTLEMENT_TEXT_GAP,
    MatchFacts,
    score_primitives,
    settlement_primitives,
)
from tank_game.ui_rendering import label

SEATS = (('tank-1', 'YOU'), ('tank-2', 'Laika'))


def match_facts(data):
    """Source per-round scores are deliberately not added to the session ledger."""
    return MatchFacts(round_id=data['round_id'],
                      phase={'active': 'playing', 'settling': 'settling', 'frozen': 'finished'}[data['round_phase']],
                      alive_ids=tuple(data['survivors']),
                      remaining_seconds=data['settlement']['remaining_seconds'],
                      total_seconds=data['settlement']['total_seconds'],
                      winner_id=data['result'] if data['result'] in ('tank-1', 'tank-2') else None)


def draw_match_hud(pyxel, facts, score, *, origin, seats=SEATS):
    x, _y = origin
    for _kind, *args in score_primitives(
            seats, score.points, (x+144, 426, 200, 8*SCORE_FONT_SCALE), scale=SCORE_FONT_SCALE):
        label(pyxel, *args, scale=SCORE_FONT_SCALE, bold=True)
    for kind, *args in settlement_primitives(
            seats, facts, (x, 426+SETTLEMENT_BAR_OFFSET, 512, 14), text_gap=SETTLEMENT_TEXT_GAP):
        getattr(pyxel, kind)(*args)
