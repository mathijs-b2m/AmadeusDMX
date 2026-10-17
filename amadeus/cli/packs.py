"""Optional packs: parts of the engine that are too big or too particular to ship with it, installed when you ask.

amadeus packs                      what there is and whether it's installed (--json for the Mac app)
amadeus packs install NAME         install it (pip, from PyPI)
amadeus packs install instruments --torch BUILD    Windows: PyTorch's build for the graphics card (cu130, cu126,
                                   xpu) or cpu, instead of the one picked for this PC

In a checkout a pack goes into the engine's own environment (.venv). The Mac app's Python is signed and never
written to: there a pack goes into an environment of its own in your data folder (DATA/python), on top of the
app's Python and its packages, and the app runs the engine with that one from then on (mac Workspace.builtIn).
The Windows app does the same (DATA\\python\\Scripts\\python.exe: Windows' layout of an environment).

Windows and the graphics card: torch from PyPI runs on the processor there (a track in one to a few minutes).
With an NVIDIA card the instrument pack installs PyTorch's CUDA build instead (from PyTorch's own index; the CUDA
libraries are inside, so it's big), and Demucs runs on the card (amadeus/audio/stems.py `device`); when the
card can't (driver, memory) it falls back to the processor. Not used: torch-directml (any DirectX 12 card) stops at
Python 3.12 and torch 2.4; Intel's XPU build runs on Arc graphics but is untried, so only on request (--torch xpu);
the instrument models stay on the processor (a track in about a second, onnxruntime-directml would replace
onnxruntime with an older version).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import venv
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path

from amadeus import paths, system

ENV = paths.DATA / "python"
HERE = "this PC" if system.WINDOWS else "this Mac"
TORCH, TORCHAUDIO = "2.14.1", "2.11.0"
TORCH_INDEX = "https://download.pytorch.org/whl/"
# PyTorch's Windows builds for a graphics card, with this torch, torchaudio and Python 3.14
BUILDS = {
    "cu130": ("NVIDIA graphics card", "about 4 GB"),  # CUDA 13: driver 580 or newer, GeForce 16/20 and later
    "cu126": ("NVIDIA graphics card", "about 5 GB"),  # CUDA 12.6: older drivers (528+) and cards (Maxwell to Volta)
    "xpu": ("Intel graphics", "about 3 GB"),  # Arc and Core Ultra graphics; on request only (untried)
}


SEPARATES = (
    "Separates every track into drums, bass, vocals and the rest (Demucs) and recognises the instruments in it, "
    "so accents follow the synth, the piano or the guitar."
)


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
        about=f"{SEPARATES} Runs on {HERE}; a track takes "
        + (
            "one to a few minutes (on the processor; it runs beside the show, and a track is only done once)."
            if system.WINDOWS
            else "about half a minute."
        ),
        size="about 1 GB",
        requirements=(f"torch=={TORCH}", f"torchaudio=={TORCHAUDIO}", "demucs==4.1.0", "onnxruntime==1.31.0"),
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
    p.add_argument("--torch", choices=["cpu", *BUILDS], help="Windows: which PyTorch build (default: for this PC)")
    return {"packs": packs_command}


def nvidia() -> tuple[float, float] | None:
    """Windows: the (first) NVIDIA card's driver version and compute capability, from nvidia-smi (it comes with the
    driver); None without one."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version,compute_cap", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, **system.background_flags(),
        ).stdout  # fmt: skip
        driver, cap = out.splitlines()[0].split(",")
        return float(".".join(driver.strip().split(".")[:2])), float(cap)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def build_for(card: tuple[float, float] | None) -> str:
    """The PyTorch build for an NVIDIA card (driver, compute capability); "cpu" for PyPI's."""
    if card is None:
        return "cpu"
    driver, cap = card
    if driver >= 580 and cap >= 7.5:
        return "cu130"
    if driver >= 528.33 and cap < 10:  # CUDA 12.6 has no kernels for Blackwell (RTX 50): a newer driver, cu130
        return "cu126"
    return "cpu"


@cache
def torch_build() -> str:
    """The PyTorch build the instrument pack installs here: on Windows the one for the NVIDIA card if there is
    one, else (and on the Mac, which uses its GPU with PyPI's) "cpu", PyPI's."""
    return build_for(nvidia()) if system.WINDOWS else "cpu"


def pack(name: str, build: str | None = None) -> Pack:
    """A pack as it installs here: the instrument pack with the PyTorch build for this PC."""
    p = PACKS[name]
    build = build or torch_build()
    if name != "instruments" or build == "cpu":
        return p
    where, size = BUILDS[build]
    return replace(
        p,
        about=f"{SEPARATES} Runs on {HERE}; a track takes "
        + ("well under a minute" if build.startswith("cu") else "a minute or less")
        + f" (on the {where}; it runs beside the show, and a track is only done once).",
        size=size,
        requirements=(f"torch=={TORCH}+{build}", f"torchaudio=={TORCHAUDIO}+{build}", *p.requirements[2:]),
        extra={"index": TORCH_INDEX + build},
    )


def installed(name: str) -> bool:
    p = PACKS[name]
    if not all(importlib.util.find_spec(m) for m in p.modules):
        return False
    if p.after == "instrument-models":
        from amadeus.audio import instruments

        return instruments.available()
    return True


def packs_command(args):
    if args.action == "install":
        if not args.name:
            raise SystemExit(f"Which pack? {', '.join(PACKS)}")
        install(args.name, args.torch)
        return
    rows = [{"name": n, "title": p.title, "about": p.about, "size": p.size, "note": p.note,
             "installed": installed(n)} for n, p in ((n, pack(n)) for n in PACKS)]  # fmt: skip
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


def _name(requirement: str) -> str:
    """A package's name as pip compares them (torch==2.14.1 → torch, Yt_DLP → yt-dlp)."""
    return re.split(r"[\[=<>!~; ]", requirement, maxsplit=1)[0].lower().replace("_", "-").replace(".", "-")


def install(name: str, build: str | None = None):
    p = pack(name, build)
    print(f"Installing {p.title} ({p.size}) …", flush=True)
    python = target_python()
    # what's already here stays as it is (the show's results depend on numpy and scipy), but the pack's own
    # packages: an installed torch 2.14.1+cpu would keep out the graphics card's 2.14.1+cu130
    own = {_name(r) for r in PACKS[name].requirements}
    have = sorted(
        {
            f"{d.metadata['Name']}=={d.version}"
            for d in importlib.metadata.distributions()
            if _name(d.metadata["Name"]) not in own
        }
    )
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("\n".join(have) + "\n")
        constraints = f.name
    cmd = [sys.executable, "-m", "pip"]
    if python != sys.executable:
        cmd += ["--python", python]
    cmd += ["install", "--disable-pip-version-check", "--progress-bar", "off", "-c", constraints]
    try:
        if "index" in p.extra:  # PyTorch's build for the graphics card, from its own index (the rest from PyPI)
            try:
                subprocess.run([*cmd, "--extra-index-url", p.extra["index"], *p.requirements], check=True)
            except subprocess.CalledProcessError:
                print("The graphics card's PyTorch didn't install; the one for the processor instead …", flush=True)
                p = PACKS[name]
        if "index" not in p.extra:
            subprocess.run([*cmd, *p.requirements], check=True)
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Could not install {p.title} (pip exited with {e.returncode})") from None
    finally:
        Path(constraints).unlink(missing_ok=True)
    if p.after == "instrument-models":
        print("Downloading the instrument models (~21 MB) …", flush=True)
        from amadeus.audio import instruments

        instruments.download()
        print(p.note, flush=True)
    print(f"Installed {p.title}. It takes effect at the next show.", flush=True)
