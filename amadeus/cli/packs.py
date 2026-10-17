"""Optional packs: parts of the engine that are too big or too particular to ship with it, installed when you ask.

amadeus packs                      what there is and whether it's installed (--json for the Mac app)
amadeus packs install NAME         install it (pip, from PyPI)

In a checkout a pack goes into the engine's own environment (.venv). The Mac app's Python is signed and never
written to: there a pack goes into an environment of its own in your data folder (DATA/python), on top of the
app's Python and its packages, and the app runs the engine with that one from then on (mac Workspace.builtIn).
The Windows app does the same (DATA\\python\\Scripts\\python.exe: Windows' layout of an environment).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import subprocess
import sys
import tempfile
import venv
from dataclasses import dataclass, field
from pathlib import Path

from amadeus import paths, system

ENV = paths.DATA / "python"
HERE = "this PC" if system.WINDOWS else "this Mac"


@dataclass(frozen=True)
class Pack:
    title: str
    about: str
    size: str
    requirements: tuple[str, ...]  # pinned as in requirements-ml.txt / pyproject.toml
    modules: tuple[str, ...]  # importable when installed
    note: str = ""
    after: str = ""  # a step once the packages are there
    extra: dict = field(default_factory=dict)


PACKS = {
    "instruments": Pack(
        title="Instrument analysis",
        about="Separates every track into drums, bass, vocals and the rest (Demucs) and recognises the instruments "
        f"in it, so accents follow the synth, the piano or the guitar. Runs on {HERE}; a track takes "
        + (
            "one to a few minutes (on the processor; it runs beside the show, and a track is only done once)."
            if system.WINDOWS
            else "about half a minute."
        ),
        size="about 1 GB",
        requirements=("torch==2.14.1", "torchaudio==2.11.0", "demucs==4.1.0", "onnxruntime==1.31.0"),
        modules=("torch", "demucs", "onnxruntime"),
        note="The instrument models (Music Technology Group, Universitat Pompeu Fabra) are CC BY-NC-SA 4.0: "
        "free for non-commercial use only.",
        after="instrument-models",
    ),
    "streamed": Pack(
        title="Streamed tracks (yt-dlp)",
        about="Lets djay Pro's Spotify tracks light: a copy of the same recording is downloaded to analyse it. "
        "Switch it on in Integrations.",
        size="about 20 MB",
        requirements=("yt-dlp[default]==2026.8.19",),
        modules=("yt_dlp",),
    ),
}


def add_commands(sub) -> dict:
    p = sub.add_parser("packs", help="optional packs: instrument analysis, streamed tracks")
    p.add_argument("action", nargs="?", choices=["install"], help="install a pack")
    p.add_argument("name", nargs="?", choices=sorted(PACKS))
    p.add_argument("--json", action="store_true", help="the list as JSON")
    return {"packs": packs_command}


def installed(name: str) -> bool:
    pack = PACKS[name]
    if not all(importlib.util.find_spec(m) for m in pack.modules):
        return False
    if pack.after == "instrument-models":
        from amadeus.audio import instruments

        return instruments.available()
    return True


def packs_command(args):
    if args.action == "install":
        if not args.name:
            raise SystemExit(f"Which pack? {', '.join(PACKS)}")
        install(args.name)
        return
    rows = [{"name": n, "title": p.title, "about": p.about, "size": p.size, "note": p.note,
             "installed": installed(n)} for n, p in PACKS.items()]  # fmt: skip
    if args.json:
        print(json.dumps(rows))
        return
    for r in rows:
        print(f"  {'✓' if r['installed'] else '–'} {r['name']:<12} {r['title']} ({r['size']})")


def target_python() -> str:
    """The Python a pack goes into: this one in an environment of its own (a checkout's .venv, the packs'
    environment), else (the app's Python, which is never written to) the packs' environment on top of it."""
    if sys.prefix != sys.base_prefix or paths.DATA == paths.ROOT:
        return sys.executable
    # made, or upgraded so it points at this Python again after the app moved (Windows: copies, symlinks need
    # rights there); not otherwise: on Windows its python.exe can't be replaced while an engine runs from it
    if not ENV.exists() or _home(ENV) != Path(sys.executable).resolve().parent:
        venv.EnvBuilder(
            system_site_packages=True, with_pip=False, symlinks=not system.WINDOWS, upgrade=ENV.exists()
        ).create(ENV)
    return str(system.venv_python(ENV))


def _home(env: Path) -> Path | None:
    """The Python an environment was made on (`home` in its pyvenv.cfg)."""
    try:
        for line in (env / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "home":
                return Path(value.strip()).resolve()
    except OSError:
        pass
    return None


def install(name: str):
    pack = PACKS[name]
    print(f"Installing {pack.title} ({pack.size}) …", flush=True)
    python = target_python()
    # what's already here stays as it is (the show's results depend on numpy and scipy)
    have = sorted({f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions()})
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("\n".join(have) + "\n")
        constraints = f.name
    cmd = [sys.executable, "-m", "pip"]
    if python != sys.executable:
        cmd += ["--python", python]
    cmd += ["install", "--disable-pip-version-check", "--progress-bar", "off", "-c", constraints, *pack.requirements]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Could not install {pack.title} (pip exited with {e.returncode})") from None
    finally:
        Path(constraints).unlink(missing_ok=True)
    if pack.after == "instrument-models":
        print("Downloading the instrument models (~21 MB) …", flush=True)
        from amadeus.audio import instruments

        instruments.download()
        print(pack.note, flush=True)
    print(f"Installed {pack.title}. It takes effect at the next show.", flush=True)
