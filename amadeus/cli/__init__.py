"""Amadeus DMX command line.

amadeus analyze TRACK                    beats, phrases and drops of a track
amadeus direct  TRACK [--director …]     the director's plan for it
amadeus play    TRACK [--dmx [IP]]       play it with the lights (and the visualiser)
amadeus live    [--dmx] [--remote …]     follow VirtualDJ (the AmadeusLink plugin), here or on a DJ laptop
amadeus setup   [--lan]                  web UI for fixtures, node and stage

amadeus set [NAME] [--copy-of SET | --grid MODEL:COUNT]   your gear: list, switch or create sets
amadeus rig [NAME] [--template T] [--automount]          the venue: list, switch, create rigs; mount the set
amadeus library [WORDS] [--add KEY]                       fixture library: ours, QLC+, Open Fixture Library
amadeus patch MODEL[:COUNT] …                             patch fixtures into the active set

A show runs with a set (your fixtures) placed on a rig (the trusses and stage): --set NAME --rig NAME, or
the active ones (`amadeus set NAME`, `amadeus rig NAME`).

amadeus discover / simnode / test / gobos / colors / motion   hardware: find, simulate, calibrate
amadeus monitor                                               watch VirtualDJ and the engine run
amadeus probe [NAME] [--emit 127.0.0.1:9123] [--record F]     watch another DJ software's integration, pass it on
"""

from __future__ import annotations

import argparse

from amadeus import paths
from amadeus.cli import hardware, rig, show

GROUPS = (show, rig, hardware)
ANNOUNCE_SET = {"play", "live", "setup", "test", "discover", "patch"}


def main(argv: list[str] | None = None):
    paths.load_dotenv()
    ap = argparse.ArgumentParser(prog="amadeus", description="AI-directed sound-to-light for DJ sets")
    sub = ap.add_subparsers(dest="cmd", required=True)
    handlers = {}
    for group in GROUPS:
        handlers.update(group.add_commands(sub))
    args = ap.parse_args(argv)
    paths.CACHE.mkdir(exist_ok=True)
    if hasattr(args, "set_name"):  # commands that work on a show's rig and set
        _resolve_show(args)
    handlers[args.cmd](args)


def _resolve_show(args):
    """--rig / --set, else the active ones; the setup page without either edits whichever you pick there."""
    from amadeus.rig import store

    args.edit_any_set = args.cmd == "setup" and not args.set_name and not args.rig
    args.show = store.current(args.rig, args.set_name)
    if args.cmd in ANNOUNCE_SET:
        placed, total = args.show.placed()
        note = f" ({total - placed} of {total} fixtures not mounted yet)" if placed < total else ""
        print(
            f"Set '{args.show.set}' on the rig '{args.show.rig}'{note}"
            if not args.show.file
            else f"Rig file: {args.show.file}"
        )
