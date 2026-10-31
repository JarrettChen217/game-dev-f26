"""Browser window metadata; no native libraries or alternate game simulation."""
from tank_game.window_contract import WindowSnapshot


def browser_settlement_seconds(world, scene, tutorial=None):
    """Practice has no duel contract; tutorial owns its own teaching facts."""
    if tutorial is not None:
        return tutorial.round_facts.remaining_seconds
    if world is not None and scene is not None and 'duel' in scene:
        return world.presentation_facts()['settlement']['remaining_seconds']
    return None


class BrowserPyxel:
    """Keep the existing quit/cleanup flow, then return the browser to startup."""
    def __init__(self, engine, return_to_start):
        self.engine = engine
        self.return_to_start = return_to_start

    def __getattr__(self, name):
        return getattr(self.engine, name)

    def quit(self):
        try:
            self.engine.quit()
        finally:
            self.return_to_start()


class BrowserWindowObserver:
    def __init__(self, read_state=None):
        if read_state is None:
            from js import window
            read_state = lambda: window.tankWindow.to_py()
        self.read_state = read_state

    def sample(self, pyxel):
        state = self.read_state()
        return WindowSnapshot(bool(state['focused']),
                              ('browser', state['epoch'], state['width'], state['height']),
                              0 <= pyxel.mouse_x < pyxel.width
                              and 0 <= pyxel.mouse_y < pyxel.height)

    def close(self):
        pass
