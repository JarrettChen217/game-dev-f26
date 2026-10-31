"""Lazy desktop resources; headless callers import no native implementation."""
import sys

from tank_game.agents import AgentScheduler


def create_desktop_scheduler(strategy: str, *, frozen: bool = False) -> AgentScheduler:
    if sys.platform == 'emscripten':
        from tank_game.agents import InlineWorker
        from tank_game.strategies import make_policy
        policy = make_policy(strategy)
        return AgentScheduler(InlineWorker(policy), decision_hz=getattr(policy, 'decision_hz', 10))
    from tank_game.process_worker import ProcessWorker
    from tank_game.strategies import make_policy
    options = {'startup_timeout': 2} if frozen else {}
    policy = make_policy(strategy)
    return AgentScheduler(ProcessWorker(policy, timeout=.25, **options),
                          decision_hz=getattr(policy, 'decision_hz', 10))


def create_desktop_window_observer():
    if sys.platform == 'emscripten':
        from tank_game.web_runtime import BrowserWindowObserver
        return BrowserWindowObserver()
    from tank_game.window_state import NativeWindowObserver
    return NativeWindowObserver()
