"""Pure control math shared by prediction and scheduling."""


def target_turn(turn, heading, target, step):
    """Keep the original pulse direction only while a whole tick improves aim."""
    if target is None:
        return turn
    error=(target-heading+180)%360-180
    return turn if error*turn > step/2 else 0


