"""Rigs: sets, the fixture library, patching, and the setup web UI."""

from __future__ import annotations

import json
import socket
import time

from decisive.cli.common import add_set_args


def add_commands(sub) -> dict:
    p = sub.add_parser("setup", help="web UI for fixtures, node and stage (no show)")
    add_set_args(p)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument(
        "--lan", action="store_true", help="also reachable from your phone (same Wi-Fi): mobile setup at /m.html"
    )

    p = sub.add_parser("set", help="list, switch or create sets (several rigs side by side)")
    p.add_argument("name", nargs="?")
    p.add_argument("--copy-of", metavar="SET", help="create NAME as a copy of SET")
    p.add_argument(
        "--grid",
        metavar="MODEL:COUNT",
        help="create NAME with COUNT fixtures on a truss grid, e.g. qlc:Martin/Martin-MAC-Encore-Performance.qxf:60",
    )
    p.add_argument(
        "--layout",
        choices=["grid", "concert"],
        default="grid",
        help="grid: rows of hanging trusses; concert: overhead + back of stage + front edge + side towers",
    )
    p.add_argument("--rows", type=int, default=3, help="grid: truss rows (default 3)")
    p.add_argument("--lasers", type=int, default=0, help="concert: also N multicolour lasers (above the audience)")
    p.add_argument("--width", type=float, default=16.0, help="truss width in metres (default 16)")
    p.add_argument("--height", type=float, default=7.0, help="height of the front truss in metres (default 7)")
    p.add_argument("--depth", type=float, default=6.0, help="distance front → back truss in metres (default 6)")
    p.add_argument("--mode", help="DMX mode (default: the richest)")
    p.add_argument("--no-switch", action="store_true", help="create without making it the active set")

    p = sub.add_parser(
        "library", help="list fixture definitions, or search/add from the QLC+ and Open Fixture libraries"
    )
    p.add_argument("query", nargs="*", help="search words, e.g. 'beamz fuze'")
    p.add_argument(
        "--add", metavar="KEY", help="add a search result (e.g. qlc:Ayra/Ayra-Compar-Kit-3.qxf) to fixtures/"
    )

    p = sub.add_parser("patch", help="patch fixtures by model and count, assign addresses")
    p.add_argument("specs", nargs="+", metavar="MODEL[:COUNT]")
    p.add_argument("--universe", type=int, default=0)
    p.add_argument("--mode", action="append", default=[], metavar="MODEL=MODE")
    add_set_args(p)
    return {"setup": setup, "set": sets_command, "library": library, "patch": patch}


def setup(args):
    from decisive.web.server import serve

    serve(args.port, None if args.edit_any_set else args.rig, "0.0.0.0" if args.lan else "127.0.0.1")
    print(f"Fixture setup: http://localhost:{args.port}/setup.html   (Ctrl+C to stop)")
    if args.lan:
        print(f"On your phone (same Wi-Fi): http://{_lan_ip()}:{args.port}/m.html")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent: this only picks the outgoing interface
        return s.getsockname()[0]
    except OSError:
        return "<this-computer's-ip>"
    finally:
        s.close()


def sets_command(args):
    from decisive.rig import sets

    if not args.name:
        for s in sets.info():
            mark = "▶" if s["active"] else " "
            print(f" {mark} {s['name']:<16} {s['fixtures']:>3} fixtures  {s['summary']}  (Art-Net {s['artnet']})")
        print("Switch with: decisive set NAME")
        return
    name = sets.safe_name(args.name)
    if args.copy_of or args.grid:
        if name in sets.names():
            raise SystemExit(f"Set '{name}' already exists; pick another name (or switch to it: decisive set {name})")
        rig = _copied_rig(args) if args.copy_of else _grid_rig(args)
        p = sets.save(name, rig)
        print(f"Created set '{name}' ({len(rig['fixtures'])} fixtures) → {p}")
        if args.no_switch:
            return
    sets.switch(name)
    print(f"Active set: {name} (used by play/live/setup from their next start; or pick one with --set NAME)")


def _copied_rig(args) -> dict:
    from decisive.rig import sets

    rig = json.loads(sets.path(sets.safe_name(args.copy_of)).read_text())
    rig["description"] = f"copy of {args.copy_of}"
    return rig


def _grid_rig(args) -> dict:
    from decisive.rig.grid import concert_rig, grid_rig

    model, _, count = args.grid.rpartition(":")
    size = {"width": args.width, "height": args.height, "depth": args.depth, "mode": args.mode}
    if args.layout == "concert":
        return concert_rig(model, int(count), lasers=args.lasers, **size)
    return grid_rig(model, int(count), rows=args.rows, **size)


def library(args):
    from decisive.library import catalog
    from decisive.library import fixtures as fxlib

    if args.add:
        print(f"Added as '{catalog.add(args.add)}'. Check it once with `decisive test`.")
    elif args.query:
        for c in catalog.search(" ".join(args.query)):
            print(f"  {c['manufacturer']} {c['model']:<30} {catalog.SOURCES[c['source']]:<22} {c['key']}")
    else:
        for key, d in fxlib.library().items():
            modes = ", ".join(f"{m} ({len(ch)})" for m, ch in d["modes"].items())
            wheel = "" if "color_wheel" not in d or d["color_wheel"].get("verified") else "  ⚠ wheel colours unverified"
            print(f"  {key:<22} {d['manufacturer']} {d['model']:<14} {d['kind']:<11} modes: {modes}{wheel}")


def patch(args):
    from decisive.dmx.discover import manual_patch

    manual_patch(args.specs, args.universe, dict(m.split("=", 1) for m in args.mode), args.rig)
