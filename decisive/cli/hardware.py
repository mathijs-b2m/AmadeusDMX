"""Hardware: find nodes and fixtures, simulate a node, and calibrate fixtures by eye."""

from __future__ import annotations

from decisive.cli.common import add_fixture_arg, add_set_args


def add_commands(sub) -> dict:
    p = sub.add_parser("discover", help="find Art-Net nodes and RDM fixtures")
    p.add_argument(
        "--sim",
        nargs="?",
        const="127.0.0.1:6455",
        default=None,
        metavar="HOST:PORT",
        help="talk to the simulated node instead of broadcasting",
    )
    p.add_argument("--readdress", action="store_true", help="give fixtures new non-overlapping addresses over RDM")
    p.add_argument("--write", action="store_true", help="write the result to the rig file")
    add_set_args(p)

    p = sub.add_parser("simnode", help="run a simulated Net-2/5 with virtual fixtures")
    p.add_argument("fixtures", metavar="MODEL[:COUNT],...")
    p.add_argument("--port", type=int, default=6455)
    p.add_argument("--no-rdm", action="store_true", help="fixtures don't speak RDM (like most budget fixtures)")
    p.add_argument(
        "--factory",
        action="store_true",
        help="start every fixture at address 1 (to try discover --readdress) instead of the rig's addresses",
    )
    add_set_args(p)

    p = sub.add_parser("test", help="light each fixture on its own and calibrate head orientation")
    p.add_argument("--level", type=float, default=0.3, help="test brightness 0..1 (default 0.3)")
    p.add_argument("--ip", help="Art-Net node IP (default: the rig's)")
    add_set_args(p)

    p = sub.add_parser("gobos", help="project a fixture's gobos one by one and name them")
    add_fixture_arg(p)
    add_set_args(p)

    p = sub.add_parser("colors", help="show a colour wheel slot by slot and name the colours")
    add_fixture_arg(p)
    add_set_args(p)

    p = sub.add_parser("motion", help="measure how fast a moving head really swings on the beat")
    add_fixture_arg(p)
    p.add_argument("--axis", choices=["tilt", "pan"], default="tilt")
    add_set_args(p)
    return {"discover": discover, "simnode": simnode, "test": test, "gobos": gobos, "colors": colors, "motion": motion}


def discover(args):
    from decisive.dmx.discover import discover as run

    target = None
    if args.sim:
        host, _, port = args.sim.partition(":")
        target = (host, int(port or 6455))
    run(target, args.rig, args.readdress, args.write)


def simnode(args):
    from decisive.dmx.simnode import run

    try:
        run(args.fixtures, port=args.port, rdm_capable=not args.no_rdm, rig_path=None if args.factory else args.rig)
    except KeyboardInterrupt:
        print("\nSimulator stopped")


def test(args):
    from decisive.setup.bringup import run

    run(args.rig, args.level, args.ip)


def gobos(args):
    from decisive.setup.gobos import run

    run(args.rig, args.fixture)


def colors(args):
    from decisive.setup.colors import run

    run(args.rig, args.fixture)


def motion(args):
    from decisive.setup.motion import run

    run(args.rig, args.fixture, args.axis)
