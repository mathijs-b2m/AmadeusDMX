"""MIDI in on Windows, through WinMM (ctypes): what the Mixxx integration needs, SysEx included.

Windows can't create a MIDI port from a program the way macOS can (python-rtmidi's virtual ports don't exist
there), so the engine opens one that is already there, by its name: a Windows MIDI Services loopback (Windows 11
24H2 and later, in the box; the Windows app makes "Amadeus DMX") or a loopMIDI port. Both are visible to WinMM
programs like Mixxx and this one, and both let two programs open the same port.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

CALLBACK_FUNCTION = 0x00030000
MIM_DATA, MIM_LONGDATA = 0x3C3, 0x3C4
BUFFERS, BUFFER_SIZE = 8, 1024  # SysEx buffers WinMM fills; a longer message continues in the next one


def matching(names: list[str], wanted: str, loose: bool = True) -> int | None:
    """The port called `wanted`: exactly; else one the system names with something added: at the front on macOS
    ('IAC Driver Bus 1' for 'Bus 1'), at the end on Windows ('Amadeus DMX 1', 'Amadeus DMX group 1') (`loose`)."""
    tests = [lambda n: n == wanted, lambda n: n.endswith(" " + wanted)]
    if loose:
        tests.append(lambda n: n.startswith(wanted + " "))
    for test in tests:
        hit = next((i for i, n in enumerate(names) if test(n)), None)
        if hit is not None:
            return hit
    return None


class SysEx:
    """Bytes of WinMM's SysEx buffers → whole messages (F0 … F7), also when one spans two buffers."""

    def __init__(self):
        self.part = bytearray()

    def feed(self, data: bytes) -> list[list[int]]:
        out = []
        for b in data:
            if b == 0xF0:
                self.part = bytearray([b])
            elif self.part:
                self.part.append(b)
                if b == 0xF7:
                    out.append(list(self.part))
                    self.part = bytearray()
        return out


class MIDIHDR(ctypes.Structure):
    pass


MIDIHDR._fields_ = [
    ("lpData", ctypes.c_void_p),
    ("dwBufferLength", wintypes.DWORD),
    ("dwBytesRecorded", wintypes.DWORD),
    ("dwUser", ctypes.c_size_t),
    ("dwFlags", wintypes.DWORD),
    ("lpNext", ctypes.POINTER(MIDIHDR)),
    ("reserved", ctypes.c_size_t),
    ("dwOffset", wintypes.DWORD),
    ("dwReserved", ctypes.c_size_t * 8),
]


class MIDIINCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", wintypes.WCHAR * 32),
        ("dwSupport", wintypes.DWORD),
    ]


def _winmm():
    w = ctypes.WinDLL("winmm")
    H, U, P = wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p
    for name, args in (
        ("midiInGetNumDevs", []),
        ("midiInGetDevCapsW", [ctypes.c_size_t, P, U]),
        ("midiInOpen", [ctypes.POINTER(H), U, P, ctypes.c_size_t, wintypes.DWORD]),
        ("midiInPrepareHeader", [H, P, U]),
        ("midiInUnprepareHeader", [H, P, U]),
        ("midiInAddBuffer", [H, P, U]),
        ("midiInStart", [H]),
        ("midiInStop", [H]),
        ("midiInReset", [H]),
        ("midiInClose", [H]),
    ):
        f = getattr(w, name)
        f.argtypes, f.restype = args, U
    return w


def input_names() -> list[str]:
    """The MIDI inputs WinMM sees, in its order."""
    w = _winmm()
    names = []
    for i in range(w.midiInGetNumDevs()):
        caps = MIDIINCAPSW()
        names.append(caps.szPname if w.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0 else "")
    return names


class MidiIn:
    """One WinMM input, like python-rtmidi's MidiIn as far as Mixxx uses it: `callback(([bytes…], 0.0), None)`
    for every SysEx message (other messages are ignored)."""

    def __init__(self, index: int, callback):
        self.w = _winmm()
        self.callback = callback
        self.sysex = SysEx()
        self.closing = False
        self.lock = threading.Lock()
        proc = ctypes.WINFUNCTYPE(
            None, wintypes.HANDLE, wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t
        )
        self._proc = proc(self._event)  # kept: WinMM calls it as long as the port is open
        self.handle = wintypes.HANDLE()
        err = self.w.midiInOpen(ctypes.byref(self.handle), index, ctypes.cast(self._proc, ctypes.c_void_p), 0,
                                CALLBACK_FUNCTION)  # fmt: skip
        if err:
            raise OSError(f"MIDI input {index} can't be opened (WinMM error {err}: in use by a program that "
                          "doesn't share it?)")  # fmt: skip
        self.buffers = []
        for _ in range(BUFFERS):
            data = ctypes.create_string_buffer(BUFFER_SIZE)
            hdr = MIDIHDR(lpData=ctypes.cast(data, ctypes.c_void_p), dwBufferLength=BUFFER_SIZE)
            self.buffers.append((data, hdr))
            self.w.midiInPrepareHeader(self.handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
            self.w.midiInAddBuffer(self.handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
        self.w.midiInStart(self.handle)

    def _event(self, handle, msg, instance, param1, param2):
        if msg != MIM_LONGDATA or self.closing:
            return
        hdr = ctypes.cast(param1, ctypes.POINTER(MIDIHDR)).contents
        data = ctypes.string_at(hdr.lpData, hdr.dwBytesRecorded) if hdr.dwBytesRecorded else b""
        # back to WinMM at once (as RtMidi does, from this callback): the next message needs a buffer
        self.w.midiInAddBuffer(self.handle, ctypes.addressof(hdr), ctypes.sizeof(hdr))
        with self.lock:
            messages = self.sysex.feed(data)
        for m in messages:
            try:
                self.callback((m, 0.0), None)
            except Exception as e:  # noqa: BLE001 - never let an exception unwind into WinMM
                print(f"  ⚠ MIDI: {e}", flush=True)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.w.midiInStop(self.handle)
        self.w.midiInReset(self.handle)  # hands the buffers back
        for _, hdr in self.buffers:
            self.w.midiInUnprepareHeader(self.handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
        self.w.midiInClose(self.handle)
