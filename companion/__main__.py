"""Command line entry point.

    python -m companion serve            # dashboard at http://localhost:8000
    python -m companion check            # one-off check: generate + send alerts (for cron)
    python -m companion login            # connect Yahoo from the terminal
    python -m companion lineup           # print this week's recommended lineup
"""
from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="companion", description="Gridiron Griddle: Yahoo fantasy football companion")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the dashboard + background monitor")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    sub.add_parser("check", help="run one monitoring pass and send notifications")
    sub.add_parser("login", help="connect your Yahoo account")
    lp = sub.add_parser("lineup", help="print the recommended lineup")
    lp.add_argument("--week", type=int)
    sub.add_parser("test-notify", help="send a test notification")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from .app import State, create_app
    from .config import Settings

    settings = Settings.from_env()
    if args.cmd == "serve":
        import uvicorn
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return 0
    state = State(settings)
    if args.cmd == "login":
        if settings.demo_mode:
            print("Demo mode is on. Add YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET to .env first.")
            return 1
        print("Open this URL, approve access, then paste the code Yahoo shows you:\n")
        print(state.auth.authorize_url(), "\n")
        state.auth.exchange_code(input("Code: "))
        leagues = state.league.leagues()
        print("Connected. Leagues:", ", ".join(f"{l['name']} ({l['league_key']})" for l in leagues) or "none found")
        return 0
    if not state.ready:
        print("Not connected to Yahoo. Run: python -m companion login")
        return 1
    if args.cmd == "check":
        from .monitor import run_check
        print(json.dumps(run_check(state.companion, settings, state.notifier), indent=2))
    elif args.cmd == "test-notify":
        print(state.notifier.send("Gridiron Griddle test", "Notifications are working!", 3) or "No channels configured")
    elif args.cmd == "lineup":
        dash = state.companion.dashboard(args.week)
        lu = dash["lineup"]
        print(f"Week {dash['week']} — {dash['my_team']['name']}")
        for s in lu["slots"]:
            p = s["player"]
            print(f"  {s['slot']:<7} {(p['name'] if p else '— empty —'):<24} {p['projection'] if p else 0:>6.1f}")
        print(f"Projected {lu['total']:.1f} (current lineup {lu['current_total']:.1f}, gain {lu['gain']:+.1f})")
        for n in lu["notes"]:
            print(f"  [{n['level']}] {n['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
