"""Manual-play checkpoint: optional source-aligned rules, no actor or training."""

import argparse
import json

from tank_game.episodes import create_world
from tank_game.killfield_rules import rules_episode


def simple_scheduler():
    from tank_game.agents import AgentScheduler
    from tank_game.patrol import SimplePatrol
    from tank_game.process_worker import ProcessWorker

    # Existing trusted Simple stays isolated. 5Hz divides25 and leaves time for
    # one asynchronous response; human controls and physics advance at25Hz.
    return AgentScheduler(
        ProcessWorker(SimplePatrol(), timeout=0.25, startup_timeout=2), decision_hz=5
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duel", action="store_true", help="include the existing Simple opponent")
    parser.add_argument(
        "--inspect", action="store_true", help="print optional public scene, no window"
    )
    args = parser.parse_args()
    world = create_world(rules_episode(duel=args.duel))
    if args.inspect:
        print(json.dumps(world.observe("tank-1"), indent=2))
        return
    import pyxel

    from tank_game.app import DrivingApp

    app = DrivingApp(
        pyxel,
        world,
        duel=args.duel,
        scheduler_factory=simple_scheduler if args.duel else None,
        tutorial_progress_path="reports/killfield-author/rules-preview-tutorial-unused.json",
    )
    app.close()


if __name__ == "__main__":
    main()
