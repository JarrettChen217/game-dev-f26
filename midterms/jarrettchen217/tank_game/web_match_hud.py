"""Thin web host adapter for the shared match_hud module, not another HUD."""
from tank_game.match_hud import (
    SCORE_FONT_SCALE,
    SETTLEMENT_BAR_OFFSET,
    SETTLEMENT_TEXT_GAP,
    SessionScore,
    score_primitives,
    settlement_primitives,
)
from tank_game.ui_rendering import board_origin, label


class WebMatchHudMixin:
    """A browser app owns one score for each normal-menu GameSession."""
    def __init__(self, *args, **kwargs):
        self.match_score = SessionScore(('tank-1', 'tank-2'))
        self._score_session = None
        super().__init__(*args, **kwargs)

    def _sync_match_score(self):
        if self.session is None or not self.is_duel or self.tutorial is not None or self._closed:
            self.match_score.clear()
            self._score_session = None
            return
        if self._score_session is not self.session:
            self.match_score.clear()
            self._score_session = self.session
        self.match_score.record(self.world.display_match())

    def update(self):
        # Catch a final result even if this update immediately retries/changes map.
        self._sync_match_score()
        try:
            super().update()
        finally:
            self._sync_match_score()

    def close(self):
        self.match_score.clear()
        self._score_session = None
        super().close()

    def draw(self):
        super().draw()
        if (self.session is None or not self.is_duel or self.tutorial is not None
                or self.ui.screen not in ('playing', 'dying', 'pause', 'results')):
            return
        pyxel = self.pyxel
        x, _ = board_origin(self.ui.inspection_visible)
        seats = (('tank-1', self.player_label),
                 ('tank-2', self.opponent_label or self.strategy.capitalize()))
        facts = self.world.display_match()
        # Existing map ends at424. Keep slots/fire426 and put hints at456 so
        # the shared larger score and compact settlement fit without covering play.
        pyxel.rect(x, 438, 512, 26, 7)
        for _kind, *values in score_primitives(
                seats, self.match_score.points, (x+144, 426, 200, 8*SCORE_FONT_SCALE),
                scale=SCORE_FONT_SCALE):
            label(pyxel, *values, scale=SCORE_FONT_SCALE, bold=True)
        for kind, *values in settlement_primitives(
                seats, facts, (x, 426+SETTLEMENT_BAR_OFFSET, 512, 14),
                text_gap=SETTLEMENT_TEXT_GAP):
            getattr(pyxel, kind)(*values)
        names = lambda action: self.keymap.names(action)[0]
        exit_hint = ('Esc: resume' if self.ui.screen == 'pause' else
                     'Esc: select Quit' if facts.phase == 'finished' else 'Esc: pause')
        hint = (f'{names("forward")}/{names("backward")}: drive  '
                f'{names("turn_left")}/{names("turn_right")}: turn  {names("fire")}: fire  '
                f'{names("inspection_toggle")}: information  {exit_hint}')
        pyxel.text(x, 456, hint[:128], 5)
