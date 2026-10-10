"""Shows: analyse and direct a track, play it, follow VirtualDJ live, watch it run."""

from __future__ import annotations

import asyncio
from pathlib import Path

from decisive import paths
from decisive.cli.common import add_dmx_arg, add_set_args


def add_commands(sub) -> dict:
    for name in ("analyze", "direct", "play"):
        p = sub.add_parser(
            name,
            help={
                "analyze": "beats, phrases and drops of a track",
                "direct": "the director's plan for a track",
                "play": "play a track with the lights and the visualiser",
            }[name],
        )
        p.add_argument("wav", type=Path, metavar="TRACK")
        p.add_argument("--tempo", choices=["half", "double"], help="the song is half / double as fast as detected")
        if name == "analyze":
            continue
        p.add_argument(
            "--director",
            default="auto",
            help="auto | openai | rules | ollama (local decision model nimble) | ollama:<decision model>",
        )
        p.add_argument("--redo", action="store_true", help="re-run the director even if a plan is cached")
        if name == "play":
            add_set_args(p)
            add_dmx_arg(p)
            p.add_argument("--mute", action="store_true", help="don't play audio (clock runs silently)")
            p.add_argument("--start", type=float, default=0.0, help="start position in seconds")
            p.add_argument("--port", type=int, default=8080)
            p.add_argument("--ws-port", type=int, default=8765, help="visualiser feed (open /?ws=PORT for another)")

    p = sub.add_parser("live", help="follow a VirtualDJ mix (DecisiveLink plugin as master effect)")
    p.add_argument(
        "--director",
        default=None,
        help="rules | openai | ollama:<model> (default: the rig's setting, switchable in /setup.html)",
    )
    add_dmx_arg(p)
    add_set_args(p)
    p.add_argument(
        "--remote",
        metavar="HOST:PORT",
        default=None,
        help="VirtualDJ on another computer: its Decisive Link app (HOST:PORT, dj:NAME, or 'auto' to find it)",
    )
    p.add_argument("--code", default=None, help="the pairing code the Decisive Link app shows")
    p.add_argument("--ws-port", type=int, default=8765, help="visualiser feed (a second show next to another)")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument(
        "--health",
        type=float,
        nargs="?",
        const=5.0,
        default=0.0,
        metavar="SECONDS",
        help="print vital signs every few seconds (default 5): VirtualDJ packets, decks, loop timing",
    )

    p = sub.add_parser("monitor", help="watch VirtualDJ + live mode: CPU, memory, threads, GPU, crashes")
    p.add_argument("--interval", type=float, default=1.0)
    return {"analyze": analyze, "direct": direct_or_play, "play": direct_or_play, "live": live, "monitor": monitor}


def analyze(args):
    from decisive.audio.analysis import analyze as run

    a = run(args.wav, paths.CACHE, tempo=args.tempo)
    print(f"{a.duration:.0f} s, {a.bpm:.1f} BPM, {len(a.beats)} beats, {len(a.phrases)} phrases")


def direct_or_play(args):
    from decisive.pipeline import get_plan, pick_director, separate_now
    from decisive.rig.loader import load_rig

    if args.director == "auto" and args.cmd == "play":  # the model chosen on the setup page
        args.director = args.show.load().get("director", "auto")
    director = pick_director(args.director, args.wav, args.redo, args.tempo)
    rig = load_rig(args.show) if args.cmd == "play" else None
    separate_now(args.wav)
    a, plan = get_plan(args.wav, director, args.redo, args.tempo, rig=rig)
    if args.cmd != "play":
        return
    from decisive.show.player import play

    try:
        asyncio.run(
            play(
                a,
                plan,
                rig,
                director=director,
                audio=not args.mute,
                artnet_ip=args.artnet,
                start=args.start,
                http_port=args.port,
                ws_port=args.ws_port,
            )
        )
    except KeyboardInterrupt:
        pass


def live(args):
    from decisive.rig.loader import load_rig
    from decisive.show.live import run

    try:
        asyncio.run(
            run(
                load_rig(args.show),
                args.director,
                args.artnet,
                http_port=args.port,
                cache=paths.CACHE,
                show=args.show,
                health=args.health,
                remote=args.remote,
                code=args.code,
                ws_port=args.ws_port,
            )
        )
    except KeyboardInterrupt:
        pass


def monitor(args):
    from decisive.show.monitor import run

    try:
        run(args.interval)
    except KeyboardInterrupt:
        pass
