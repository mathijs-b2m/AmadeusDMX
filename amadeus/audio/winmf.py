"""Windows' own audio decoders (Media Foundation), for what libsndfile can't read when there is no ffmpeg: M4A/AAC,
ALAC, WMA, … (and whatever codecs the computer has from the Microsoft Store: Opus/WebM with the Web Media
Extensions). The Windows counterpart of macOS's afconvert: no download, nothing to install.

Through ctypes only: the Source Reader decodes to 16-bit PCM at the file's own rate and channels.
"""

from __future__ import annotations

import ctypes
import struct
import uuid
import wave
from ctypes import wintypes
from pathlib import Path

MF_VERSION = 0x00020070
FIRST_AUDIO_STREAM = 0xFFFFFFFD
MEDIA_SOURCE = 0xFFFFFFFF
END_OF_STREAM = 0x2
READ_ERROR = 0x1

# IMFSourceReader, IMFAttributes / IMFMediaType, IMFSample, IMFMediaBuffer: their methods' places in the vtable
SET_STREAM_SELECTION, GET_CURRENT_TYPE, SET_CURRENT_TYPE, READ_SAMPLE, GET_PRESENTATION_ATTR = 4, 6, 7, 9, 12
GET_UINT32, SET_GUID = 7, 24
CONVERT_TO_CONTIGUOUS = 41
LOCK, UNLOCK = 3, 4
RELEASE = 2


class GUID(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text: str) -> GUID:
        u = uuid.UUID(text)
        return cls(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("value", ctypes.c_ulonglong), ("pad", ctypes.c_ulonglong)]  # fmt: skip


MAJOR_TYPE = GUID.of("48eba18e-f8c9-4687-bf11-0a74c9f96a8f")  # MF_MT_MAJOR_TYPE
SUBTYPE = GUID.of("f7e34c9a-42e8-4714-b74b-cb29d72c35e5")  # MF_MT_SUBTYPE
AUDIO = GUID.of("73647561-0000-0010-8000-00aa00389b71")  # MFMediaType_Audio
PCM = GUID.of("00000001-0000-0010-8000-00aa00389b71")  # MFAudioFormat_PCM
CHANNELS = GUID.of("37e48bf5-645e-4c5b-89de-ada9e29b696a")  # MF_MT_AUDIO_NUM_CHANNELS
RATE = GUID.of("5faeeae7-0290-4c31-9e8a-c534f68d9dba")  # MF_MT_AUDIO_SAMPLES_PER_SECOND
BITS = GUID.of("f2deb57f-40fa-4764-aa33-ed4f2d1ff669")  # MF_MT_AUDIO_BITS_PER_SAMPLE
DURATION = GUID.of("6c990d33-bb8e-477a-8598-0d5d96fcd88a")  # MF_PD_DURATION (100 ns)


def _call(obj: ctypes.c_void_p, index: int, *args, types=()):
    """A COM method by its vtable index; raises on a failed HRESULT."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(vtable[index])
    hr = fn(obj, *args)
    if hr < 0:
        raise OSError(f"Media Foundation error 0x{hr & 0xFFFFFFFF:08X}")
    return hr


def _release(obj: ctypes.c_void_p):
    if obj:
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[RELEASE])(obj)


class _Reader:
    """A Source Reader on one file, decoding its first audio stream to PCM."""

    def __init__(self, path: Path):
        self.mf = ctypes.WinDLL("mfplat")
        self.rd = ctypes.WinDLL("mfreadwrite")
        ctypes.WinDLL("ole32").CoInitializeEx(None, 0)  # COINIT_MULTITHREADED (fine if already initialised)
        self._check(self.mf.MFStartup(wintypes.ULONG(MF_VERSION), wintypes.DWORD(1)))  # MFSTARTUP_LITE
        self.reader = ctypes.c_void_p()
        create = self.rd.MFCreateSourceReaderFromURL
        create.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        try:
            self._check(create(str(Path(path).resolve()), None, ctypes.byref(self.reader)))
        except OSError:
            self.mf.MFShutdown()
            raise

    @staticmethod
    def _check(hr: int):
        if hr < 0:
            raise OSError(f"Media Foundation error 0x{hr & 0xFFFFFFFF:08X}")

    def duration(self) -> float:
        v = PROPVARIANT()
        _call(self.reader, GET_PRESENTATION_ATTR, MEDIA_SOURCE, ctypes.byref(DURATION), ctypes.byref(v),
              types=(wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p))  # fmt: skip
        return v.value / 1e7

    def to_pcm(self) -> tuple[int, int]:
        """Decode to 16-bit PCM from here on: → (channels, sample rate)."""
        r = self.reader
        _call(r, SET_STREAM_SELECTION, 0xFFFFFFFE, False, types=(wintypes.DWORD, wintypes.BOOL))  # all off
        _call(r, SET_STREAM_SELECTION, FIRST_AUDIO_STREAM, True, types=(wintypes.DWORD, wintypes.BOOL))
        mt = ctypes.c_void_p()
        self._check(self.mf.MFCreateMediaType(ctypes.byref(mt)))
        try:
            _call(mt, SET_GUID, ctypes.byref(MAJOR_TYPE), ctypes.byref(AUDIO), types=(ctypes.c_void_p, ctypes.c_void_p))
            _call(mt, SET_GUID, ctypes.byref(SUBTYPE), ctypes.byref(PCM), types=(ctypes.c_void_p, ctypes.c_void_p))
            _call(r, SET_CURRENT_TYPE, FIRST_AUDIO_STREAM, None, mt,
                  types=(wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p))  # fmt: skip
        finally:
            _release(mt)
        cur = ctypes.c_void_p()
        _call(r, GET_CURRENT_TYPE, FIRST_AUDIO_STREAM, ctypes.byref(cur), types=(wintypes.DWORD, ctypes.c_void_p))
        try:
            got = {}
            for name, key in (("channels", CHANNELS), ("rate", RATE), ("bits", BITS)):
                v = ctypes.c_uint32()
                _call(cur, GET_UINT32, ctypes.byref(key), ctypes.byref(v), types=(ctypes.c_void_p, ctypes.c_void_p))
                got[name] = v.value
        finally:
            _release(cur)
        if got["bits"] != 16:
            raise OSError(f"Media Foundation gave {got['bits']}-bit audio")
        return got["channels"], got["rate"]

    def chunks(self):
        """The decoded PCM, one sample (a few thousand frames) at a time."""
        while True:
            index, flags, stamp, sample = wintypes.DWORD(), wintypes.DWORD(), ctypes.c_longlong(), ctypes.c_void_p()
            _call(self.reader, READ_SAMPLE, FIRST_AUDIO_STREAM, 0, ctypes.byref(index), ctypes.byref(flags),
                  ctypes.byref(stamp), ctypes.byref(sample),
                  types=(wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p))  # fmt: skip
            if sample:
                buf = ctypes.c_void_p()
                try:
                    _call(sample, CONVERT_TO_CONTIGUOUS, ctypes.byref(buf), types=(ctypes.c_void_p,))
                    data, size = ctypes.c_void_p(), wintypes.DWORD()
                    _call(buf, LOCK, ctypes.byref(data), None, ctypes.byref(size),
                          types=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p))  # fmt: skip
                    try:
                        yield ctypes.string_at(data, size.value)
                    finally:
                        _call(buf, UNLOCK)
                finally:
                    _release(buf)
                    _release(sample)
            if flags.value & END_OF_STREAM:
                return
            if flags.value & READ_ERROR:  # no sample will ever come: don't wait for the end
                raise OSError("Media Foundation couldn't read the stream")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        _release(self.reader)
        self.mf.MFShutdown()


def decode(path: str | Path, out: str | Path):
    """`path` decoded into a 16-bit WAV at `out`. Raises OSError when Windows can't decode it.

    A fragmented MP4 with an edit list (YouTube's DASH M4A often has one: skip the encoder's first 1600 samples)
    comes out of Media Foundation empty: then a copy without the edit list is decoded and its lead-in skipped
    here, so the audio starts on the very sample it does everywhere else."""
    path, out = Path(path), Path(out)
    if _decode(path, out):
        return
    fixed = without_edit_list(path.read_bytes())
    if fixed is not None:
        data, skip = fixed
        copy = out.with_name(out.stem + ".noedit" + path.suffix)
        try:
            copy.write_bytes(data)
            if _decode(copy, out, skip):
                return
        finally:
            copy.unlink(missing_ok=True)
    raise OSError("Media Foundation decoded no audio")


def _decode(path: Path, out: Path, skip: float = 0.0) -> int:
    """Decode into `out`, leaving out the first `skip` seconds; → the frames written."""
    frames = 0
    with _Reader(path) as r:
        channels, rate = r.to_pcm()
        drop = round(skip * rate) * channels * 2  # bytes of the lead-in still to leave out
        with wave.open(str(out), "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(rate)
            for chunk in r.chunks():
                if drop:
                    cut = min(drop, len(chunk))
                    chunk, drop = chunk[cut:], drop - cut
                w.writeframes(chunk)
                frames += len(chunk) // (channels * 2)
    return frames


def _boxes(d: bytes, start: int, end: int):
    """The MP4 boxes in d[start:end]: (offset, size, type)."""
    i = start
    while i + 8 <= end:
        size, typ = struct.unpack(">I4s", d[i : i + 8])
        if size == 1:
            size = struct.unpack(">Q", d[i + 8 : i + 16])[0]
        elif size == 0:
            size = end - i
        if size < 8:
            return
        yield i, size, typ
        i += size


def without_edit_list(data: bytes) -> tuple[bytes, float] | None:
    """The file with its audio track's edit list made a free box (same size: nothing else moves), and the
    seconds of lead-in that edit list skipped; None if it has none."""
    moov = next(((o, n) for o, n, t in _boxes(data, 0, len(data)) if t == b"moov"), None)
    if moov is None:
        return None
    out, skip = bytearray(data), None
    for o, n, t in _boxes(data, moov[0] + 8, moov[0] + moov[1]):
        if t != b"trak":
            continue
        inner = {typ: (off, size) for off, size, typ in _boxes(data, o + 8, o + n)}
        if b"edts" not in inner or b"mdia" not in inner:
            continue
        mo, mn = inner[b"mdia"]
        hdlr = next((off for off, _, typ in _boxes(data, mo + 8, mo + mn) if typ == b"hdlr"), None)
        if hdlr is None or data[hdlr + 16 : hdlr + 20] != b"soun":
            continue
        mdhd = next(off for off, _, typ in _boxes(data, mo + 8, mo + mn) if typ == b"mdhd")
        v = data[mdhd + 8]
        scale = struct.unpack(">I", data[mdhd + (28 if v == 1 else 20) : mdhd + (32 if v == 1 else 24)])[0]
        eo, en = inner[b"edts"]
        elst = next((off for off, _, typ in _boxes(data, eo + 8, eo + en) if typ == b"elst"), None)
        if elst is not None and struct.unpack(">I", data[elst + 12 : elst + 16])[0]:
            # the first entry: segment duration, then media time (where it starts in the track; -1: empty)
            at, fmt = (elst + 24, ">q") if data[elst + 8] == 1 else (elst + 20, ">i")
            media_time = struct.unpack_from(fmt, data, at)[0]
            skip = max(0, media_time) / scale if scale else 0.0
        out[eo + 4 : eo + 8] = b"free"
        break
    return None if skip is None else (bytes(out), skip)


def duration(path: str | Path) -> float | None:
    """A file's length (s) as Media Foundation reads it; None when it can't."""
    try:
        with _Reader(Path(path)) as r:
            return r.duration() or None
    except OSError:
        return None
