"""The engine on Windows: the platform's own paths, processes, MIDI, djay's window, decoders and the way an app
stops it. Most of it runs everywhere (Windows' rules tested on a Mac too); what needs Windows itself is marked."""

import importlib.util
import io
import os
import struct
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from amadeus import shutdown, system

ROOT = Path(__file__).resolve().parent.parent
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows' own APIs")


# ---------------------------------------------------------------- paths and files


def test_file_urls_become_paths_on_either_system():
    assert system.file_url_path("file:///Users/me/a%20b.mp3", windows=False) == "/Users/me/a b.mp3"
    assert system.file_url_path("file:///C:/Users/me/Music/a%20b.mp3", windows=True) == r"C:\Users\me\Music\a b.mp3"
    assert system.file_url_path("file://nas/music/x.mp3", windows=True) == r"\\nas\music\x.mp3"


def test_an_environment_has_its_python_where_the_system_puts_it():
    env = Path("env")
    assert system.venv_python(env, windows=True) == env / "Scripts" / "python.exe"
    assert system.venv_python(env, windows=False) == env / "bin" / "python3"


def test_replace_tries_again_while_another_process_holds_the_file(tmp_path, monkeypatch):
    calls = []
    real = os.replace

    def busy_once(a, b):
        calls.append(a)
        if len(calls) == 1:
            raise PermissionError("in use")
        real(a, b)

    monkeypatch.setattr(system, "WINDOWS", True)
    monkeypatch.setattr(system.os, "replace", busy_once)
    (tmp_path / "a.tmp").write_text("new", encoding="utf-8")
    system.replace(tmp_path / "a.tmp", tmp_path / "a")
    assert len(calls) == 2 and (tmp_path / "a").read_text(encoding="utf-8") == "new"


def test_a_link_falls_back_to_a_hard_link_without_the_right_to_symlink(tmp_path, monkeypatch):
    target = tmp_path / "copy.m4a"
    target.write_bytes(b"audio")

    def no_right(self, *a, **k):
        raise OSError("A required privilege is not held by the client")

    monkeypatch.setattr(Path, "symlink_to", no_right)
    system.link_or_copy(target, tmp_path / "other name.m4a")
    assert (tmp_path / "other name.m4a").read_bytes() == b"audio"


def test_music_folders_are_separated_as_the_system_separates_paths(monkeypatch):
    from amadeus.show.sources import resolve

    monkeypatch.setenv("AMADEUS_MUSIC", os.pathsep.join(["one", "two"]))
    assert resolve.roots() == [Path("one"), Path("two")]


def test_ffmpeg_given_or_shipped_with_the_engine_comes_first(tmp_path, monkeypatch):
    from amadeus.audio import analysis

    exe = tmp_path / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    exe.write_text("", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("AMADEUS_FFMPEG", str(exe))
    assert analysis.ffmpeg() == str(exe)
    monkeypatch.delenv("AMADEUS_FFMPEG")
    shipped = tmp_path / "bin" / exe.name
    shipped.parent.mkdir()
    exe.replace(shipped)
    monkeypatch.setattr(analysis.paths, "ROOT", tmp_path)
    assert analysis.ffmpeg() == str(shipped)


def test_virtualdj_home_on_windows(tmp_path, monkeypatch):
    from amadeus.show.sources import streamed

    monkeypatch.setattr(system, "user_folder", lambda name: tmp_path / name)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    homes = streamed.vdj_homes(windows=True)
    assert homes == [tmp_path / "Documents/VirtualDJ", tmp_path / "Local/VirtualDJ", tmp_path / "Roaming/VirtualDJ"]
    assert streamed.vdj_database(windows=True) == tmp_path / "Documents/VirtualDJ/database.xml"  # none yet
    (tmp_path / "Local/VirtualDJ").mkdir(parents=True)
    (tmp_path / "Local/VirtualDJ/database.xml").write_text("<VirtualDJ_Database/>", encoding="utf-8")
    assert streamed.vdj_database(windows=True) == tmp_path / "Local/VirtualDJ/database.xml"


def test_djays_library_on_windows_is_in_the_music_folder(tmp_path, monkeypatch):
    from amadeus.show.sources import djay

    monkeypatch.setattr(system, "user_folder", lambda name: tmp_path / name)
    plain = tmp_path / "Music/djay/djay Media Library/MediaLibrary.db"
    assert (
        djay.library_file(windows=True) == tmp_path / "Music/djay/djay Media Library.djayMediaLibrary/MediaLibrary.db"
    )
    plain.parent.mkdir(parents=True)
    plain.write_bytes(b"")
    assert djay.library_file(windows=True) == plain


# ---------------------------------------------------------------- what ships


def test_requirements_pick_each_systems_packages():
    from packaging.requirements import Requirement

    lines = (ROOT / "requirements-app.txt").read_text(encoding="utf-8").splitlines()
    reqs = [Requirement(x) for x in lines if x.strip() and not x.startswith(("#", "-r"))]

    def wanted(platform):
        env = {"sys_platform": platform, "platform_system": {"win32": "Windows", "darwin": "Darwin"}[platform]}
        return {r.name for r in reqs if r.marker is None or r.marker.evaluate(env)}

    win, mac = wanted("win32"), wanted("darwin")
    assert {"comtypes", "zeroconf", "aalink"} <= win and not {"python-rtmidi", "pyobjc-core"} & win
    assert {"python-rtmidi", "pyobjc-core", "pyobjc-framework-ApplicationServices", "aalink"} <= mac
    assert not {"comtypes", "zeroconf"} & mac
    assert all("==" in str(r.specifier) for r in reqs)  # pinned, as the apps ship them


def test_the_integrations_say_what_differs_on_windows():
    from amadeus.show.sources import load

    win, mac = load(windows=True), load(windows=False)
    assert set(win) == set(mac)
    for name in ("vdj", "mixxx", "djay"):
        assert win[name].verified == "built, not yet verified on Windows"
        assert mac[name].verified != win[name].verified and "macOS" in mac[name].verified
    assert "UI Automation" in win["djay"].about and "Accessibility" in mac["djay"].about


def test_usb_dmx_ports_on_each_system():
    from amadeus.dmx.outputs import candidate

    assert candidate("COM3", "USB Serial Port (COM3)", 0x0403, windows=True)
    assert not candidate("COM1", "Communications Port (COM1)", None, windows=True)  # the motherboard's
    assert not candidate("COM5", "Standard Serial over Bluetooth link (COM5)", 0x0000, windows=True)
    assert candidate("/dev/cu.usbserial-EN123", "", 0x0403, windows=False)
    assert not candidate("/dev/cu.Bluetooth-Incoming-Port", "", None, windows=False)
    assert candidate("/dev/ttyUSB0", "", 0x0403, windows=False)


# ---------------------------------------------------------------- Mixxx: MIDI on Windows


def test_the_midi_port_is_found_by_its_name_as_each_system_shows_it():
    from amadeus.show.sources.winmidi import matching

    assert matching(["Microsoft GS Wavetable Synth", "Amadeus DMX"], "Amadeus DMX") == 1
    assert matching(["Amadeus DMX 1"], "Amadeus DMX") == 0  # numbered
    assert matching(["Amadeus DMX group 1"], "Amadeus DMX") == 0  # Windows MIDI Services, a port per group
    assert matching(["IAC Driver Bus 1"], "Bus 1") == 0  # CoreMIDI: the device's name in front
    assert matching(["Amadeus DMX 1"], "Amadeus DMX", loose=False) is None  # macOS: makes its own instead
    assert matching(["Amadeus DMXX", "loopMIDI Port"], "Amadeus DMX") is None


def test_sysex_is_put_together_across_winmms_buffers():
    from amadeus.show.sources.mixxx import decode
    from amadeus.show.sources.winmidi import SysEx

    msg = bytes([0xF0, 0x7D, 0x44, 0x4C, 0x01, 0x02, 0x40, 0x00, 0xF7])
    sx = SysEx()
    assert sx.feed(msg[:4]) == []
    got = sx.feed(msg[4:] + msg)
    assert got == [list(msg), list(msg)]
    assert decode(got[0]) == {"xfader": (0x40 * 128) / 16383 * 2 - 1}
    assert sx.feed(b"\x05\xf7") == []  # stray bytes outside a message


def test_mixxx_on_windows_says_how_to_get_the_port(monkeypatch):
    from amadeus.show.sources import mixxx, winmidi

    monkeypatch.setattr(mixxx.sys, "platform", "win32")
    monkeypatch.setattr(mixxx, "SETTINGS", [])
    monkeypatch.setattr(mixxx, "Resolver", lambda: None)
    monkeypatch.setattr(winmidi, "input_names", lambda: ["Microsoft GS Wavetable Synth"])
    with pytest.raises(SystemExit, match="loopMIDI"):
        mixxx.Mixxx()


# ---------------------------------------------------------------- djay: the same labels on both systems


def test_djays_labels_are_shared():
    from amadeus.show.sources import djay

    labels = {"Elapsed time, Deck 1": 0, "Elapsed time, Deck 2": 0, "125.5, Deck 2": 0, "Crossfader": 0}
    assert djay.decks_in(labels) == [1, 2] and djay.bpm_in(labels, 2) == 125.5 and djay.bpm_in(labels, 1) == 0.0
    assert djay.label(djay.PLAY, 3) == "Play / Pause, Deck 3"
    assert djay.wanted("Crossfader") and djay.wanted("Title, Deck 1") and not djay.wanted("Library")


def test_ui_automation_values_read_like_accessibility_values():
    from amadeus.show.sources import djay

    assert djay.uia_text("01:07") == "01:07"  # a text: as it is
    assert djay.uia_text(toggle=1) == djay.ACTIVE and djay.uia_text(toggle=0) != djay.ACTIVE
    assert djay.percent(djay.uia_text(rng=(0.85, 0.0, 1.0), label="Line volume, Deck 1")) == pytest.approx(0.85)
    assert djay.percent(djay.uia_text(rng=(64.0, 0.0, 127.0), label="Crossfader")) == pytest.approx(64 / 127)
    assert djay.percent(djay.uia_text(rng=(2.5, -8.0, 8.0), label="Tempo, Deck 1")) == pytest.approx(0.025)
    assert djay.uia_text() is None


# ---------------------------------------------------------------- stopping cleanly


def test_closing_stdin_stops_the_engine():
    stopped = []
    shutdown.watch(io.BytesIO(b"anything the app writes is ignored\n"), lambda: stopped.append(1))
    assert stopped == [1]


@pytest.mark.skipif(sys.platform != "win32", reason="PeekNamedPipe: Windows only")
def test_a_pipe_is_watched_without_a_read_waiting_on_it():
    r, w = os.pipe()
    stopped = threading.Event()
    t = threading.Thread(target=shutdown.watch_pipe, args=(r, stopped.set, 0.01), daemon=True)
    t.start()
    os.write(w, b"anything the app writes is ignored\n")
    time.sleep(0.2)
    assert not stopped.is_set()
    os.close(w)
    assert stopped.wait(5)
    os.close(r)


def test_stdin_is_watched_on_windows_when_it_is_a_pipe(monkeypatch):
    monkeypatch.setattr(shutdown.os, "fstat", lambda fd: os.stat_result((0o010600,) + (0,) * 9))  # a FIFO
    assert shutdown.watches_stdin({}, windows=True) and not shutdown.watches_stdin({}, windows=False)
    assert shutdown.watches_stdin({shutdown.ENV: "1"}, windows=False)
    assert not shutdown.watches_stdin({shutdown.ENV: "0"}, windows=True)
    monkeypatch.setattr(shutdown.os, "fstat", lambda fd: os.stat_result((0o020600,) + (0,) * 9))  # a console
    assert not shutdown.watches_stdin({}, windows=True)


def test_only_the_first_stop_is_passed_on(monkeypatch):
    sent = []
    monkeypatch.setattr(shutdown, "_stopping", shutdown.threading.Event())
    monkeypatch.setattr(shutdown._thread, "interrupt_main", lambda *a: sent.append(a))
    shutdown.stop_now()
    shutdown._as_ctrl_c()  # Ctrl+Break a moment later: the blackout is already under way
    assert len(sent) == 1


def test_an_engine_stops_cleanly_when_the_app_closes_its_stdin(tmp_path):
    """A real engine (`amadeus monitor`, which ends on Ctrl+C with exit code 0), stopped as the Windows app does."""
    env = {**os.environ, "AMADEUS_DATA": str(tmp_path), shutdown.ENV: "1", "PYTHONUNBUFFERED": "1"}
    p = subprocess.Popen(
        [sys.executable, "-m", "amadeus", "monitor", "--interval", "0.2"],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        first = p.stdout.readline().decode("utf-8")
        assert "Monitoring" in first, first
        p.stdin.close()
        assert p.wait(timeout=20) == 0, p.stdout.read().decode("utf-8", "replace")
    finally:
        if p.poll() is None:
            p.kill()


# ---------------------------------------------------------------- processes


def test_processes_and_this_one():
    me = os.getpid()
    assert system.alive(me)
    assert system.peak_memory_mb() > 1
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    assert not system.alive(done.pid)
    if sys.platform == "win32":
        stats = system.process_stats(me)
        assert stats["threads"] >= 1 and stats["mem_mb"] > 1 and stats["cpu_s"] > 0
        assert 0 <= system.system_stats()["mem_free_pct"] <= 100
    assert any(pid == me for pid, _ in system.processes())


# ---------------------------------------------------------------- Windows itself


@windows_only
def test_media_foundation_decodes_what_soundfile_wrote(tmp_path):
    from amadeus.audio import winmf

    rate, t = 44100, np.arange(44100) / 44100
    src = tmp_path / "tone.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1) * 12000).astype("<i2").tobytes())
    out = tmp_path / "out.wav"
    winmf.decode(src, out)
    with wave.open(str(out), "rb") as w:
        assert (w.getnchannels(), w.getframerate()) == (2, rate) and abs(w.getnframes() - rate) < 2048
    assert winmf.duration(src) == pytest.approx(1.0, abs=0.05)


@windows_only
def test_winmm_lists_its_midi_inputs():
    from amadeus.show.sources import winmidi

    assert isinstance(winmidi.input_names(), list)


@windows_only
def test_djays_window_is_looked_for_with_ui_automation():
    if importlib.util.find_spec("comtypes") is None:  # not imported here: COM may be single-threaded on this thread
        pytest.skip("needs comtypes")
    from amadeus.show.sources import djay

    w = djay.UiaWindow()
    assert w.scan() is False and w.decks() == []  # no djay on the test machine: nothing found, nothing raised
    assert w.value(djay.label(djay.ELAPSED, 1)) is None


@windows_only
def test_known_folders():
    assert system.user_folder("Music").is_absolute() and system.user_folder("Documents").is_absolute()


def test_set_names_windows_keeps_for_devices_get_a_number(monkeypatch):
    from amadeus.rig import store

    monkeypatch.setattr(system, "WINDOWS", True)
    assert (
        store.safe_name("Con") == "con-1" and store.safe_name("COM1") == "com1-1" and store.safe_name("club") == "club"
    )
    monkeypatch.setattr(system, "WINDOWS", False)
    assert store.safe_name("aux") == "aux"


def test_the_packs_environment_is_only_remade_when_the_app_moved(tmp_path, monkeypatch):
    from amadeus.cli import packs

    env = tmp_path / "python"
    env.mkdir()
    here = Path(sys.executable).resolve().parent
    (env / "pyvenv.cfg").write_text(f"home = {here}\ninclude-system-site-packages = true\n", encoding="utf-8")
    made = []
    monkeypatch.setattr(packs, "ENV", env)
    monkeypatch.setattr(packs.paths, "DATA", tmp_path)
    monkeypatch.setattr(packs.sys, "prefix", packs.sys.base_prefix)  # the app's own Python, no environment
    builder = type("Builder", (), {"create": lambda self, d: made.append(d)})
    monkeypatch.setattr(packs.venv, "EnvBuilder", lambda **kw: builder())
    packs.target_python()
    assert made == []  # on this Python already: its python.exe is left alone
    (env / "pyvenv.cfg").write_text("home = C:\\\\elsewhere\\\\runtime\n", encoding="utf-8")
    packs.target_python()
    assert made == [env]


def _box(typ: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + typ + body


def test_an_edit_list_is_taken_out_and_its_lead_in_kept():
    """YouTube's DASH M4A often skips the encoder's first 1600 samples with an edit list, which Media Foundation
    can't read in a fragmented file (it decodes nothing): the copy without it starts 1600 samples early."""
    from amadeus.audio import winmf

    mdhd = _box(b"mdhd", bytes(4) + bytes(8) + struct.pack(">II", 44100, 0) + bytes(4))
    hdlr = _box(b"hdlr", bytes(8) + b"soun" + bytes(12))
    elst = _box(b"elst", bytes(4) + struct.pack(">IIiI", 1, 11699648, 1600, 0x00010000))
    trak = _box(b"trak", _box(b"tkhd", bytes(84)) + _box(b"edts", elst) + _box(b"mdia", mdhd + hdlr))
    data = _box(b"ftyp", b"dash" + bytes(12)) + _box(b"moov", _box(b"mvhd", bytes(100)) + trak) + _box(b"mdat", b"x")
    out, skip = winmf.without_edit_list(data)
    assert len(out) == len(data) and b"edts" not in out and out.count(b"free") == 1
    assert skip * 44100 == pytest.approx(1600)
    assert winmf.without_edit_list(out) is None  # nothing left to take out


def test_an_empty_decode_is_not_kept(tmp_path, monkeypatch):
    from amadeus.audio import analysis

    track = tmp_path / "a.m4a"
    track.write_bytes(b"not audio soundfile reads")
    st = track.stat()
    import hashlib

    key = hashlib.sha1(f"{track.resolve()}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:8]
    stale = tmp_path / f"a.{key}.decoded.wav"
    stale.write_bytes(b"RIFF" + bytes(40))  # a header and nothing else, from a decode that went wrong
    monkeypatch.setattr(analysis, "ffmpeg", lambda: None)
    monkeypatch.setattr(analysis.sys, "platform", "linux")
    monkeypatch.setattr(analysis, "AFCONVERT", str(tmp_path / "no-afconvert"))
    with pytest.raises(SystemExit):
        analysis.readable_audio(track, tmp_path)
    assert not stale.exists()
