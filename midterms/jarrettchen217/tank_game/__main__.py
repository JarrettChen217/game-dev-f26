"""Launch public preview, or print a headless public snapshot."""

import argparse


def main():
    parser = argparse.ArgumentParser(description='Tank maze: single tank or selectable bot duel')
    parser.add_argument('--inspect', action='store_true', help='print public JSON without a window')
    parser.add_argument('--diagnostics', type=str, metavar='REPORT_PATH',
                        help='write package diagnostics JSON without opening a window')
    parser.add_argument('--duel', action='store_true', help='play against a local bot')
    parser.add_argument('--random-map', action='store_true', help='use validated seeded duel maps')
    parser.add_argument('--map-seed', type=int, help='reproduce a random map (0..4294967295)')
    parser.add_argument('--strategy', choices=('simple','hard','laika','hybrid'),
                        help='duel opponent: Simple, Hard, native Laika or learned Hybrid u19588 (default simple)')
    parser.add_argument('--collision-profile',choices=('circle','rectangle'),default='circle',
                        help='experimental oriented hull comparison (requires Laika duel); default circle')
    parser.add_argument('--rules-profile', choices=('native','laika-original','laika-60hz'), default='native',
                        help='optional original25Hz WASM or source60Hz native adaptation')
    parser.add_argument('--baseline-steps', type=int,
                        help='run a deterministic Simple-versus-Simple smoke reproduction')
    args = parser.parse_args()
    if args.diagnostics is not None:
        from tank_game.diagnostics import run_diagnostics

        raise SystemExit(run_diagnostics(args.diagnostics))
    if args.strategy is not None and not args.duel:
        parser.error('--strategy requires --duel')
    # Normal desktop duels all select controllers over the same source60 Game.
    if (args.duel and args.collision_profile == 'circle' and args.baseline_steps is None
            and args.rules_profile != 'laika-original'):
        from tank_game.session import GameSession
        from tank_game.ui import MenuSelection
        if args.map_seed is not None and not args.random_map:
            parser.error('--map-seed requires --random-map')
        strategy = args.strategy or 'simple'
        try:
            session = GameSession(MenuSelection(True, strategy, args.random_map), seed=args.map_seed)
        except (ValueError, OSError, RuntimeError, ImportError) as error:
            parser.error(str(error))
        try:
            if args.inspect:
                from tank_game.inspection import format_inspection
                if args.random_map:
                    print(f'RANDOM MAP / SEED:{session.random_session.record.seed} / killfield-source-60hz')
                print('\n'.join(format_inspection(session.world.observe('tank-1'))))
            else:
                from tank_game.app import main as launch
                launch(duel=True, strategy=strategy, game_session=session, menu=False)
        finally:
            session.close()
        return
    if args.strategy == 'hybrid':
        parser.error('Hybrid u19588 requires its native60Hz environment')
    if args.rules_profile in ('laika-original','laika-60hz'):
        if not args.duel or args.strategy != 'laika' or args.collision_profile != 'circle' or args.baseline_steps is not None:
            parser.error('original rules require --duel --strategy laika; cannot mix collision/baseline profiles')
        if args.rules_profile == 'laika-60hz':
            from tank_game.laika_60hz.session import Source60RoundSession as OriginalRoundSession
        else:
            from tank_game.original_laika.session import OriginalRoundSession
        try:
            session = OriginalRoundSession(1000 if args.map_seed is None else args.map_seed)
        except (ValueError, RuntimeError) as error:
            parser.error(str(error))
        if args.inspect:
            from tank_game.inspection import format_inspection
            try:
                print('\n'.join(format_inspection(session.world.observe('tank-1'))))
            finally:
                session.close()
        else:
            from tank_game.app import main as launch
            try:
                launch(duel=True, strategy='laika', random_session=session)
            finally:
                session.close()
        return
    if args.random_map and (not args.duel or args.baseline_steps is not None):
        parser.error('--random-map requires --duel and cannot use --baseline-steps')
    if args.map_seed is not None and not args.random_map:
        parser.error('--map-seed requires --random-map')
    if args.collision_profile!='circle' and (not args.duel or args.strategy!='laika' or args.baseline_steps is not None):
        parser.error('rectangle profile requires --duel --strategy laika')
    session = None
    if args.random_map:
        from random import SystemRandom

        from tank_game.random_rounds import RandomRoundSession
        seed = SystemRandom().randrange(2**32) if args.map_seed is None else args.map_seed
        try:
            session = RandomRoundSession(seed,collision_profile=args.collision_profile)
        except ValueError as error:
            parser.error(str(error))
    if args.baseline_steps is not None:
        import json

        from tank_game.baseline import run_baseline
        if args.baseline_steps <= 0:
            parser.error('--baseline-steps must be positive')
        print(json.dumps(run_baseline(steps=args.baseline_steps), indent=2, sort_keys=True))
    elif args.inspect:
        from tank_game.inspection import format_inspection
        from tank_game.laika_60hz.play_modes import SoloPlayWorld
        if session is not None:
            print(f'RANDOM MAP / SEED:{session.record.seed} / {session.record.generator_version}')
        if args.collision_profile != 'circle':
            from tank_game.world import World
            world = session.world if session is not None else World(duel=args.duel,collision_profile=args.collision_profile)
        else:
            world = session.world if session is not None else SoloPlayWorld()
        try:
            print('\n'.join(format_inspection(world.observe('tank-1'))))
        finally:
            if (close := getattr(world, 'close', None)) is not None:
                close()
    else:
        from tank_game.app import main as launch
        launch(duel=args.duel, strategy=args.strategy or 'simple', random_session=session,
               menu=not args.duel,collision_profile=args.collision_profile)


if __name__ == '__main__':
    main()
