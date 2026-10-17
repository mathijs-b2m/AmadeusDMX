"""What differs between macOS, Linux and Windows, in one place: the user's folders, other processes, files that
another process may be reading while we replace them, Python environments, and the text the engine prints.

Everything else in the engine is the same on every system. Windows parts use ctypes only (no pywin32).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"

# ---------------------------------------------------------------- folders

# Windows' known folders: where they really are (Music and Documents are often moved, e.g. into OneDrive)
_KNOWN_FOLDERS = {
    "Music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
}


def user_folder(name: str) -> Path:
    """The user's Music or Documents folder: on Windows where Windows keeps it, elsewhere ~/Music, ~/Documents."""
    if WINDOWS:
        found = _known_folder(_KNOWN_FOLDERS[name])
        if found:
            return found
    return Path.home() / name


def _known_folder(guid: str) -> Path | None:
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

    u = uuid.UUID(guid)
    g = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    out = ctypes.c_wchar_p()
    try:
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) != 0:
            return None
        return Path(out.value) if out.value else None
    except OSError:
        return None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def local_app_data() -> Path:
    """%LOCALAPPDATA% (Windows), for other programs' settings folders."""
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


# ---------------------------------------------------------------- files


def replace(tmp: Path, dest: Path, tries: int = 20):
    """`tmp.replace(dest)`, also on Windows, where it fails while another process (another engine) has `dest`
    open for a moment: tried again a few times."""
    for i in range(tries):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if not WINDOWS or i == tries - 1:
                raise
            time.sleep(0.025)


def save_npz(path: Path, compressed: bool = True, **arrays):
    """np.savez(_compressed) as one step: written under a name of its own, then put in place, so another
    process (a second engine, a test worker) never reads a half-written cache file."""
    import numpy as np

    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "wb") as f:
            (np.savez_compressed if compressed else np.savez)(f, **arrays)
        replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_text(path: Path, text: str):
    """Path.write_text (UTF-8) as one step, like save_npz."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def link_or_copy(target: Path, link: Path):
    """`link` pointing at `target` (in the same folder): a symlink; where that needs rights we don't have
    (Windows without developer mode), a hard link, else a copy."""
    try:
        link.symlink_to(target.name)
        return
    except OSError:
        pass
    try:
        os.link(target, link)
    except OSError:
        import shutil

        shutil.copy2(target, link)


def file_url_path(url: str, windows: bool = WINDOWS) -> str:
    """'file:///Users/me/a%20b.mp3' → '/Users/me/a b.mp3'; on Windows 'file:///C:/Music/a.mp3' → 'C:\\Music\\a.mp3'."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    path = unquote(parsed.path)
    if not windows:
        return path
    if parsed.netloc and parsed.netloc != "localhost":  # file://server/share/a.mp3
        return "\\\\" + parsed.netloc + path.replace("/", "\\")
    if len(path) > 2 and path[0] == "/" and path[2] in ":|":  # /C:/Music → C:\Music
        path = path[1] + ":" + path[3:]
    return path.replace("/", "\\")


# ---------------------------------------------------------------- Python environments


def venv_python(env: Path, windows: bool = WINDOWS) -> Path:
    """An environment's Python: Scripts\\python.exe on Windows, bin/python3 elsewhere."""
    return env / "Scripts" / "python.exe" if windows else env / "bin" / "python3"


def utf8_output():
    """Windows: what the engine prints is UTF-8 also into a pipe (the app reads it so; the default there would be
    the ANSI code page, which can't print ♥ ▶ ⚠ and would stop the show with an error)."""
    if not WINDOWS:
        return
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if stream is not None and enc != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


# ---------------------------------------------------------------- processes


def processes() -> list[tuple[int, str]]:
    """Every process: (pid, its command line; on Windows the program's name where the command line can't be
    read)."""
    if WINDOWS:
        return [(pid, cmd or exe) for pid, exe, _, cmd in _win_processes(command_lines=True)]
    try:
        out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if pid.isdigit():
            found.append((int(pid), cmd.strip()))
    return found


def running(*names: str) -> bool:
    """Is a process running whose command line holds one of these (like `pgrep -f`)? Not this process."""
    me = os.getpid()
    return any(pid != me and any(n in cmd for n in names) for pid, cmd in processes())


def alive(pid: int) -> bool:
    """Does process `pid` still run? (Not `os.kill(pid, 0)`: on Windows that sends it Ctrl+C.)"""
    if pid <= 0:
        return False
    if WINDOWS:
        import ctypes

        k = _kernel32()
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def peak_memory_mb() -> float:
    """This process's peak memory (MB)."""
    if WINDOWS:
        return process_stats(os.getpid()).get("peak_mb", 0.0)
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1e6 if MACOS else peak / 1e3  # bytes on macOS, KB on Linux


def lower_priority():
    """This process a little below the show's (a background separation)."""
    if WINDOWS:
        k = _kernel32()
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
    else:
        os.nice(5)


def background_flags() -> dict:
    """Popen arguments for a helper process that outlives a stop of its parent and shows no window."""
    if WINDOWS:
        # CREATE_NEW_PROCESS_GROUP: a Ctrl+Break meant for the engine doesn't reach it; CREATE_NO_WINDOW
        return {"creationflags": 0x00000200 | 0x08000000}
    return {"start_new_session": True}


def process_stats(pid: int) -> dict:
    """Windows: one process's CPU time (s), memory (MB, peak too) and threads; {} when it can't be read."""
    import ctypes
    from ctypes import wintypes

    k = _kernel32()
    h = k.OpenProcess(0x1000 | 0x0010, False, pid) or k.OpenProcess(0x1000, False, pid)  # (+ VM_READ)
    if not h:
        return {}
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h, *[ctypes.byref(t) for t in times]):
            return {}
        cpu = sum(_seconds(t) for t in times[2:])  # kernel + user
        c = _MemoryCounters()
        c.cb = ctypes.sizeof(c)
        mem = k.K32GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
        threads = next((n for p, _, n, _ in _win_processes() if p == pid), 0)
        return {
            "cpu_s": cpu,
            "mem_mb": c.ws / 2**20 if mem else 0.0,
            "peak_mb": c.peak_ws / 2**20 if mem else 0.0,
            "threads": threads,
        }
    finally:
        k.CloseHandle(h)


def system_stats() -> dict:
    """Windows: the whole computer's busy and total CPU time (s) and the share of memory free (%)."""
    import ctypes
    from ctypes import wintypes

    k = _kernel32()
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    k.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    total = _seconds(kernel) + _seconds(user)  # kernel time includes idle time
    m = _MemoryStatus()
    m.length = ctypes.sizeof(m)
    k.GlobalMemoryStatusEx(ctypes.byref(m))
    return {"busy_s": total - _seconds(idle), "total_s": total, "mem_free_pct": 100 - int(m.load)}


def _win_processes(command_lines: bool = False) -> list[tuple[int, str, int, str]]:
    """Windows: (pid, program, threads, command line or "") of every process (a Toolhelp snapshot)."""
    import ctypes

    k = _kernel32()
    snap = k.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == INVALID_HANDLE:
        return []
    out = []
    try:
        e = _ProcessEntry()
        e.size = ctypes.sizeof(e)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((int(e.pid), e.exe, int(e.threads), _command_line(e.pid) if command_lines else ""))
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return out


def _command_line(pid: int) -> str:
    """Windows 8.1 and later: another process's command line (NtQueryInformationProcess, class 60)."""
    import ctypes
    from ctypes import wintypes

    class Unicode(ctypes.Structure):
        _fields_ = [("length", wintypes.USHORT), ("max", wintypes.USHORT), ("buffer", ctypes.c_void_p)]

    k = _kernel32()
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return ""
    try:
        query = ctypes.WinDLL("ntdll").NtQueryInformationProcess
        query.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]
        query.restype = ctypes.c_long
        size = wintypes.ULONG()
        query(h, 60, None, 0, ctypes.byref(size))
        if not size.value:
            return ""
        buf = ctypes.create_string_buffer(size.value)
        if query(h, 60, buf, size, ctypes.byref(size)) != 0:
            return ""
        u = Unicode.from_buffer(buf)
        return ctypes.wstring_at(u.buffer, u.length // 2) if u.buffer else ""
    finally:
        k.CloseHandle(h)


def _seconds(t) -> float:
    return (t.dwHighDateTime << 32 | t.dwLowDateTime) / 1e7  # a FILETIME: 100 ns


INVALID_HANDLE = 2**64 - 1 if sys.maxsize > 2**32 else 2**32 - 1
_api: dict = {}


def _kernel32():
    """kernel32 with the prototypes we call (an instance of our own: other code's prototypes stay theirs)."""
    if "k" in _api:
        return _api["k"]
    import ctypes
    from ctypes import wintypes

    global _MemoryCounters, _MemoryStatus, _ProcessEntry

    class _MemoryCounters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in ("peak_ws", "ws", "qpp", "qp", "qnpp", "qnp", "pagefile", "peak_pagefile")
        ]

    class _MemoryStatus(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
            (n, ctypes.c_ulonglong) for n in ("total", "avail", "pf_total", "pf_avail", "v_total", "v_avail", "x")
        ]

    class _ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("usage", wintypes.DWORD),
            ("pid", wintypes.DWORD),
            ("heap", ctypes.c_size_t),
            ("module", wintypes.DWORD),
            ("threads", wintypes.DWORD),
            ("parent", wintypes.DWORD),
            ("priority", ctypes.c_long),
            ("flags", wintypes.DWORD),
            ("exe", wintypes.WCHAR * 260),
        ]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    H, B, D, P = wintypes.HANDLE, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p
    for name, res, args in (
        ("OpenProcess", H, [D, B, D]),
        ("CloseHandle", B, [H]),
        ("GetExitCodeProcess", B, [H, P]),
        ("GetCurrentProcess", H, []),
        ("SetPriorityClass", B, [H, D]),
        ("GetProcessTimes", B, [H, P, P, P, P]),
        ("K32GetProcessMemoryInfo", B, [H, P, D]),
        ("GetSystemTimes", B, [P, P, P]),
        ("GlobalMemoryStatusEx", B, [P]),
        ("CreateToolhelp32Snapshot", H, [D, D]),
        ("Process32FirstW", B, [H, P]),
        ("Process32NextW", B, [H, P]),
    ):
        f = getattr(k, name)
        f.restype, f.argtypes = res, args
    _api["k"] = k
    return k
