"""Sets (your gear) and rigs (the venue), the fixture library, patching, and the setup web UI."""

from __future__ import annotations

import socket
import time

from amadeus.cli.common import add_set_args


def add_commands(sub) -> dict:
    p = sub.add_parser("setup", help="web UI for fixtures, node and stage (no show)")
    add_set_args(p)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument(
        "--lan", action="store_true", help="also reachable from your phone (same Wi-Fi): mobile setup at /m.html"
    )

    p = sub.add_parser("set", help="your fixtures: list, switch or create sets")
    p.add_argument("name", nargs="?")
    p.add_argument("--new", action="store_true", help="create NAME (empty: add fixtures with patch / the setup page)")
    p.add_argument("--copy-of", metavar="SET", help="create NAME as a copy of SET")
    p.add_argument(
        "--grid",
        metavar="MODEL:COUNT",
        help="create NAME with COUNT fixtures on a truss grid (and a rig NAME they hang on), "
        "e.g. qlc:Martin/Martin-MAC-Encore-Performance.qxf:60",
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

    from amadeus.rig.templates import TEMPLATES

    p = sub.add_parser("rig", help="the venue: list, switch or create rigs; auto-mount the set on it")
    p.add_argument("name", nargs="?")
    p.add_argument("--template", choices=list(TEMPLATES), help="create NAME from a template: "
                   + "; ".join(f"{k}: {v}" for k, v in TEMPLATES.items()))  # fmt: skip
    p.add_argument("--copy-of", metavar="RIG", help="create NAME as a copy of RIG")
    p.add_argument("--width", type=float, default=8.0, help="stage width in metres (default 8)")
    p.add_argument("--height", type=float, default=4.5, help="truss height in metres (default 4.5)")
    p.add_argument("--depth", type=float, default=15.0, help="room depth in front of the stage (default 15)")
    p.add_argument("--screen", action="store_true", help="an LED wall behind the DJ")
    p.add_argument("--automount", action="store_true", help="mount the active set's fixtures that aren't yet")
    p.add_argument("--all", action="store_true", help="with --automount: re-mount every fixture")
    p.add_argument("--hang-sheet", nargs="?", const="", metavar="FILE",
                   help="write the hang sheet of the active set on this rig (where every fixture goes, its DMX "
                   "address, labels) as a printable HTML file (default: hang-sheet-SET-RIG.html)")  # fmt: skip

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

    p = sub.add_parser("mcp", help="your own AI assistant works on your sets and rigs (an MCP server on stdio)")
    p.add_argument("--guide", action="store_true", help="print the guide the assistant gets, and stop")
    p.add_argument(
        "--claude-desktop",
        choices=["status", "on", "off"],
        help="let Claude Desktop start this server (on), stop that (off), or say whether it does (JSON)",
    )
    return {"setup": setup, "set": sets_command, "rig": rigs_command, "library": library, "patch": patch, "mcp": mcp}


def setup(args):
    from amadeus.web.server import serve

    serve(args.port, None if args.edit_any_set else args.show, "0.0.0.0" if args.lan else "127.0.0.1")
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
    from amadeus.rig import manage, store

    if not args.name:
        for i in store.set_info():
            mark = "▶" if i["active"] else " "
            print(f" {mark} {i['name']:<16} {i['fixtures']:>3} fixtures  {i['summary']}  ({i['output']})")
        print("Switch with: amadeus set NAME")
        return
    name = store.safe_name(args.name)
    if args.new or args.copy_of or args.grid:
        generated = _grid_rig(args) if args.grid else None
        manage.new_set(name, copy_of=args.copy_of, generated=generated)
        print(f"Created the set '{name}' ({len(store.sets.load(name).get('fixtures', []))} fixtures)"
              + (f" and the rig '{name}' it hangs on" if generated else ""))  # fmt: skip
        if args.no_switch:
            return
        if generated:
            store.rigs.switch(name)
    store.sets.switch(name)
    print(f"Active set: {name} (used by play/live/setup from their next start; or pick one with --set NAME)")


def rigs_command(args):
    from amadeus.rig import manage, store

    if not args.name and not args.automount and args.hang_sheet is None:
        for i in store.rig_info():
            mark = "▶" if i["active"] else " "
            parts = [f"{i['width_m'] or '?'} m wide", f"{i['trusses']} trusses"]
            parts += [f"{i['towers']} towers"] if i["towers"] else []
            parts += ["LED wall"] if i["screen"] else []
            parts += [f"sets mounted: {', '.join(i['sets'])}"] if i["sets"] else []
            print(f" {mark} {i['name']:<16} {', '.join(parts)}")
        print("Switch with: amadeus rig NAME · new: amadeus rig NAME --template club")
        return
    if args.name:
        name = store.safe_name(args.name)
        if args.template or args.copy_of:
            manage.new_rig(name, args.template or "booth", args.width, args.height, args.depth, args.screen,
                           copy_of=args.copy_of)  # fmt: skip
            print(f"Created the rig '{name}'")
        store.rigs.switch(name)
        print(f"Active rig: {name}")
    if args.automount:
        show = store.current()
        places = manage.mount(show, everything=args.all)
        print(f"Mounted {len(places)} fixtures of the set '{show.set}' on the rig '{show.rig}'"
              + (" (all were mounted already)" if not places else ""))  # fmt: skip
    if args.hang_sheet is not None:
        from pathlib import Path

        from amadeus.rig import hangsheet

        show = store.current()
        out = Path(args.hang_sheet or f"hang-sheet-{show.set}-{show.rig}.html")
        out.write_text(hangsheet.html(show.load(), show.set, show.rig), encoding="utf-8")
        print(f"Hang sheet of the set '{show.set}' on the rig '{show.rig}': {out} (open it in a browser to print)")


def _grid_rig(args) -> dict:
    from amadeus.rig.grid import concert_rig, grid_rig

    model, _, count = args.grid.rpartition(":")
    size = {"width": args.width, "height": args.height, "depth": args.depth, "mode": args.mode}
    if args.layout == "concert":
        return concert_rig(model, int(count), lasers=args.lasers, **size)
    return grid_rig(model, int(count), rows=args.rows, **size)


def library(args):
    from amadeus.library import catalog
    from amadeus.library import fixtures as fxlib

    if args.add:
        key = catalog.add(args.add)
        d = fxlib.get(key)
        print(f"Added as '{key}'. Check it once with `amadeus test`.")
        if fxlib.inert(d):
            print(f"  Not driven by the show: {fxlib.inert(d)}.")
        if d.get("warning"):
            print(f"  ⚠ {d['warning']}.")
    elif args.query:
        for c in catalog.search(" ".join(args.query)):
            print(f"  {c['manufacturer']} {c['model']:<30} {catalog.SOURCES[c['source']]:<22} {c['key']}")
    else:
        for key, d in fxlib.library().items():
            modes = ", ".join(f"{m} ({len(ch)})" for m, ch in d["modes"].items())
            wheel = "" if "color_wheel" not in d or d["color_wheel"].get("verified") else "  ⚠ wheel colours unverified"
            dark = "  (not driven: inert)" if fxlib.inert(d) else ""
            print(f"  {key:<22} {d['manufacturer']} {d['model']:<14} {d['kind']:<11} modes: {modes}{wheel}{dark}")


def patch(args):
    from amadeus.dmx.discover import manual_patch

    manual_patch(args.specs, args.universe, dict(m.split("=", 1) for m in args.mode), args.show)


def mcp(args):
    from amadeus import mcp as server

    if args.guide:
        print(server.GUIDE.read_text(encoding="utf-8"))
        return
    if args.claude_desktop:
        import json

        from amadeus.mcp import claude_desktop

        try:
            r = (
                claude_desktop.status()
                if args.claude_desktop == "status"
                else claude_desktop.switch(args.claude_desktop == "on")
            )
        except (OSError, ValueError) as e:  # a config that isn't JSON: left alone, said why
            r = {**claude_desktop.status(), "problem": f"Claude Desktop's config wasn't changed: {e}"}
        print(json.dumps(r))
        return
    server.serve()
