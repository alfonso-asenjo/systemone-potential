"""Launch a StarCraft II match with jev as the commander.

    python run.py                       # jev via the configured provider, vs Medium Terran AI
    python run.py --difficulty Hard --enemy zerg
    python run.py --no-jev              # rule mode: no API calls, to test the bot itself
    python run.py --fast                # not realtime: game runs as fast as it can (no video use)
    python run.py --time-limit 30       # stop after 30 s of game time
    python run.py --window 3840x2160    # bigger game window (or --fullscreen)
    python run.py --skip 240 --time-limit 540   # fast-forward 4 min in rule mode, then 5 min realtime with jev
"""
from __future__ import annotations

import argparse

from sc2 import maps
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

from jevcraft import compat
from jevcraft.bot import JevProtoss

RACES = {"terran": Race.Terran, "zerg": Race.Zerg, "protoss": Race.Protoss, "random": Race.Random}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--map", default="AcropolisLE")
    p.add_argument("--enemy", default="terran", choices=RACES)
    p.add_argument("--difficulty", default="Medium", choices=[d.name for d in Difficulty])
    p.add_argument("--no-jev", action="store_true", help="rule mode, no jev calls")
    p.add_argument("--fast", action="store_true", help="run as fast as possible instead of realtime")
    p.add_argument("--chat", action="store_true", help="post decision changes in the in-game chat (crashed SC2 once, off by default)")
    p.add_argument("--skip", type=float, default=0.0, help="fast-forward the first N game seconds in rule mode, then realtime with jev")
    p.add_argument("--port", type=int, default=8765, help="dashboard port")
    p.add_argument("--time-limit", type=float, default=None, help="end the match after N seconds of game time")
    p.add_argument("--window", default="2560x1440", help="game window size WxH (default 2560x1440)")
    p.add_argument("--fullscreen", action="store_true", help="launch the game fullscreen")
    args = p.parse_args()

    w, h = (int(v) for v in args.window.lower().split("x"))
    compat.WINDOW["resolution"] = (w, h)
    bot = JevProtoss(use_jev=not args.no_jev, dashboard_port=args.port, chat=args.chat, skip=args.skip)
    run_game(
        maps.get(args.map),
        [Bot(Race.Protoss, bot, name="jev", fullscreen=args.fullscreen), Computer(RACES[args.enemy], Difficulty[args.difficulty])],
        realtime=not args.fast and args.skip <= 0,
        game_time_limit=args.time_limit,
    )


if __name__ == "__main__":
    main()
