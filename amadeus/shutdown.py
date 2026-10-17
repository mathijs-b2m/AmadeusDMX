"""Stopping the engine cleanly: however it is asked to stop, it stops as on Ctrl+C, so a show blacks out the lights,
ends its sACN streams and closes its ports (the `finally` of its loop) before the process ends.

Ctrl+C (SIGINT) is how the Mac app stops an engine (Process.interrupt, then terminate after 4 s). An app on
Windows can't send Ctrl+C to an engine it started without a console, so there are two more ways in, both
ending in that same Ctrl+C path:

  stdin closes        on Windows when stdin is a pipe (anywhere with AMADEUS_STOP_ON_EOF=1; =0: never), the
                      engine reads its stdin until it closes. The Windows app starts every engine with stdin a
                      pipe it keeps open and closes it to stop the engine; if the app itself ends (crashed or
                      not), the pipe closes too: no engine is left behind driving the lights.
  CTRL_BREAK_EVENT    (Windows) to an engine started with CREATE_NEW_PROCESS_GROUP: GenerateConsoleCtrlEvent(
                      CTRL_BREAK_EVENT, pid). Only works from a process sharing the engine's console.

Only the first request is passed on: a second one while the show is stopping would cut its blackout short.

Then wait for the process to end (5 s is plenty; a show stops within a frame or two) and only then end it the
hard way (TerminateProcess, SIGKILL): that skips the blackout and an Art-Net node keeps the last frame lit.
"""

from __future__ import annotations

import _thread
import os
import signal
import stat
import sys
import threading

ENV = "AMADEUS_STOP_ON_EOF"


def install(env=None):
    """At start (main thread): Ctrl+Break as Ctrl+C on Windows, and the stdin watch when the app asks for it."""
    env = os.environ if env is None else env
    main = threading.current_thread() is threading.main_thread()
    if hasattr(signal, "SIGBREAK") and main:  # Windows; Python's default would end the process at once
        signal.signal(signal.SIGBREAK, _as_ctrl_c)
    if watches_stdin(env) and sys.stdin is not None:
        # Windows: a read waiting on the pipe blocks the main thread's imports (numpy's DLLs wait for it), so
        # the pipe is looked at instead, 10 times a second
        target, args = (watch_pipe, (0,)) if sys.platform == "win32" else (watch, (sys.stdin.buffer,))
        threading.Thread(target=target, args=args, name="stop-on-eof", daemon=True).start()


def watches_stdin(env, windows: bool = sys.platform == "win32") -> bool:
    """Whether to stop when stdin closes: asked for, or (Windows) stdin is a pipe, as the app gives it."""
    if env.get(ENV) in ("0", "1"):
        return env[ENV] == "1"
    try:
        return windows and stat.S_ISFIFO(os.fstat(0).st_mode)
    except (OSError, ValueError):
        return False


def watch(stream, stop=None):
    """Read `stream` until it closes, then stop (`stop`, default: as on Ctrl+C). Anything written to it is
    ignored."""
    try:
        while stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096):
            pass
    except (OSError, ValueError):  # closed under us: also the end
        pass
    (stop or stop_now)()


def watch_pipe(fd: int, stop=None, interval: float = 0.1):
    """Windows: wait for the pipe on `fd` to close without a read waiting on it (PeekNamedPipe), then stop. What
    the app writes to it is read and ignored, only when it is there (so the read never waits)."""
    import ctypes
    import msvcrt
    import time
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    try:
        handle = msvcrt.get_osfhandle(fd)
    except OSError:
        handle = None
    available = wintypes.DWORD()
    while handle is not None and k32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
        if available.value:
            os.read(fd, available.value)
        else:
            time.sleep(interval)
    (stop or stop_now)()  # broken pipe: the app closed it, or the app is gone


_stopping = threading.Event()


def stop_now():
    """Ctrl+C for the main thread, once: the handler there runs (asyncio's: the show's task is cancelled cleanly)."""
    if not _stopping.is_set():
        _stopping.set()
        _thread.interrupt_main(signal.SIGINT)


def _as_ctrl_c(*_):
    stop_now()
