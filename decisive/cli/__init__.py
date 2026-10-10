"""Decisive Lightning command line.

decisive analyze TRACK                    beats, phrases and drops of a track
decisive direct  TRACK [--director …]     the director's plan for it
decisive play    TRACK [--dmx [IP]]       play it with the lights (and the visualiser)
decisive live    [--dmx] [--remote …]     follow VirtualDJ (the DecisiveLink plugin), here or on a DJ laptop
decisive setup   [--lan]                  web UI for fixtures, node and stage

decisive set [NAME] [--copy-of SET | --grid MODEL:COUNT]   list, switch or create sets (rigs)
decisive library [WORDS] [--add KEY]                       fixture library: ours, QLC+, Open Fixture Library
decisive patch MODEL[:COUNT] …                             patch fixtures into the active set

decisive discover / simnode / test / gobos / colors / motion   hardware: find, simulate, calibrate
decisive monitor                                               watch VirtualDJ and the engine run
"""

from __future__ import annotations

import argparse

from decisive import paths
from decisive.cli import hardware, rig, show

GROUPS = (show, rig, hardware)
ANNOUNCE_SET = {"play", "live", "setup", "test", "discover", "patch"}


def main(argv: list[str] | None = None):
    paths.load_dotenv()
    ap = argparse.ArgumentParser(prog="decisive", description="AI-directed sound-to-light for DJ sets")
    sub = ap.add_subparsers(dest="cmd", required=True)
    handlers = {}
    for group in GROUPS:
        handlers.update(group.add_commands(sub))
    args = ap.parse_args(argv)
    paths.CACHE.mkdir(exist_ok=True)
    if hasattr(args, "set_name") and args.rig is None:  # commands that work on a set
        _resolve_set(args)
    handlers[args.cmd](args)


def _resolve_set(args):
    """--set NAME, else the active set; the setup page without either edits whichever set you pick there."""
    from decisive.rig import sets

    args.edit_any_set = args.cmd == "setup" and not args.set_name
    if args.set_name and sets.safe_name(args.set_name) not in sets.names():
        raise SystemExit(f"No set '{args.set_name}'. Sets: {', '.join(sets.names())}")
    args.rig = sets.path(sets.safe_name(args.set_name) if args.set_name else None)
    if args.cmd in ANNOUNCE_SET:
        print(f"Set: {args.rig.stem}")
