"""Arguments several commands share."""

from __future__ import annotations

import argparse
from pathlib import Path


def add_set_args(p: argparse.ArgumentParser):
    p.add_argument("--rig", type=Path, default=None, help="rig file (default: the active set)")
    p.add_argument("--set", dest="set_name", metavar="NAME", help="use this set (default: the active one)")


def add_dmx_arg(p: argparse.ArgumentParser):
    p.add_argument(
        "--dmx",
        "--artnet",
        dest="artnet",
        nargs="?",
        const="rig",
        default=None,
        metavar="IP",
        help="send DMX to the lights: the set's output (Art-Net, sACN or USB), or this node IP",
    )


def add_fixture_arg(p: argparse.ArgumentParser):
    p.add_argument("fixture", help="fixture id from the rig, e.g. fuze1")
