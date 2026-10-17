"""Offline audio analysis: band energies, onsets, beats, bars and phrases.

Everything is computed once per recording and cached, so the player and the
director only ever read precomputed arrays. Only numpy/scipy are used."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import soundfile as sf

from amadeus import paths
from amadeus.audio.beats import (
    attack_offset,
    beat_kicks,
    comb_score,
    constant_grid,
    downbeats,
    local_tempo,
    refine_beats,
    set_bpm,
    strongest_tempo,
    track_beats,
)
from amadeus.audio.features import (
    BANDS,
    HOP,
    lead_features,
    normalize,
    pick_peaks,
    spectral_features,
    stutter_features,
)
from amadeus.audio.model import DROP_THRESHOLD, Analysis, Phrase
from amadeus.audio.phrases import build_phrases
from amadeus.audio.rolls import fine_envelopes, snare_rolls

ANALYSIS_VERSION = 43


def cache_paths(path: Path, cache_dir: Path, tempo: str | None = None):
    st = path.stat()
    key = hashlib.sha1(
        f"{path.resolve()}|{st.st_size}|{st.st_mtime}|{ANALYSIS_VERSION}|{tempo or ''}".encode()
    ).hexdigest()[:12]
    base = cache_dir / f"{path.stem}.{key}"
    return Path(f"{base}.analysis.npz"), Path(f"{base}.analysis.json")


FFMPEG_PLACES = ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")  # Homebrew (Apple Silicon, Intel)
AFCONVERT = "/usr/bin/afconvert"  # macOS's own: MP4/AAC, ALAC, CAF, … (not WebM/Opus)


def ffmpeg() -> str | None:
    """ffmpeg: AMADEUS_FFMPEG, else the one the app ships next to the engine (bin/ffmpeg.exe on Windows), else on
    the PATH, else where Homebrew puts it (an engine the Mac app starts doesn't have Homebrew on its PATH)."""
    import os
    import shutil

    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    given = os.environ.get("AMADEUS_FFMPEG", "")
    places = (given, str(paths.ROOT / "bin" / exe), shutil.which("ffmpeg") or "", *FFMPEG_PLACES)
    return next((p for p in places if p and os.path.isfile(p) and os.access(p, os.X_OK)), None)


def readable_audio(path: str | Path, cache_dir: str | Path = paths.CACHE) -> Path:
    """The file itself if soundfile can read it (WAV, MP3, FLAC, OGG, AIFF); otherwise (e.g. M4A/AAC, WebM) a WAV
    copy decoded once into the cache: with ffmpeg, else with the system's own decoders (macOS's afconvert,
    Windows' Media Foundation: no ffmpeg needed for M4A)."""
    import os
    import subprocess

    path = Path(path)
    try:
        sf.info(str(path))
        return path
    except Exception:
        pass
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:8]
    out = Path(cache_dir) / f"{path.stem}.{key}.decoded.wav"
    if out.exists():
        return out
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    tool = ffmpeg()
    if tool:
        print(f"Decoding {path.name} with ffmpeg …")
        subprocess.run([tool, "-loglevel", "error", "-y", "-i", str(path), str(out)], check=True,
                       stdin=subprocess.DEVNULL, **_no_window())  # fmt: skip
        return out
    if sys.platform == "win32":
        from amadeus.audio import winmf

        print(f"Decoding {path.name} with Windows' decoders …")
        part = out.with_suffix(".part")
        try:
            winmf.decode(path, part)
            part.replace(out)
            return out
        except OSError as e:
            part.unlink(missing_ok=True)
            raise SystemExit(f"Can't read {path.name} ({e}): Windows can't decode it; ffmpeg can.") from None
    if os.access(AFCONVERT, os.X_OK):
        r = subprocess.run([AFCONVERT, "-f", "WAVE", "-d", "LEI16", str(path), str(out)], capture_output=True)
        if r.returncode == 0:
            return out
        out.unlink(missing_ok=True)
    raise SystemExit(f"Can't read {path.name}: it needs ffmpeg (brew install ffmpeg).")


def _no_window() -> dict:
    """Windows: a console program run from the engine opens no window of its own."""
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW


def analyze(
    path: str | Path, cache_dir: str | Path = paths.CACHE, verbose: bool = True, tempo: str | None = None
) -> Analysis:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(exist_ok=True)
    path = readable_audio(path, cache_dir)
    npz_path, json_path = cache_paths(path, cache_dir, tempo)
    if npz_path.exists() and json_path.exists():
        return _finish(_load(npz_path, json_path), path)

    log = print if verbose else (lambda *a, **k: None)
    log(f"Analysing {path.name} …")
    feats, sr, duration = spectral_features(path)
    fps = sr / HOP

    onsets = {
        "snare": pick_peaks(feats["flux_snare"], fps, delta=0.30, min_gap=0.11),
        "hat": pick_peaks(feats["flux_hat"], fps, delta=0.20, min_gap=0.08),
        "accent": pick_peaks(feats["flux_all"], fps, delta=0.50, min_gap=0.30),
        "lead": pick_peaks(feats["flux_lead"], fps, delta=0.15, min_gap=0.12),
    }
    lead_pitch, lead_pc, lead_tonal = lead_features(feats, fps)
    feats["lead_tonal"] = lead_tonal
    stutter_gate, stutter_strength = stutter_features(feats, fps)
    feats["stutter_strength"] = stutter_strength
    onset_env = normalize(feats["flux_all"]) + normalize(feats["flux_kick"])
    bpm_curve = local_tempo(onset_env, fps)
    log("  tracking beats …")
    beat_frames = track_beats(onset_env, bpm_curve, fps)
    low = 10 * np.log10(10 ** (feats["sub"] / 10) + 10 ** (feats["bass"] / 10))  # the low end, sub included
    low_rise = normalize(np.maximum(0, np.diff(low, prepend=low[0])))
    if not tempo:  # a tempo the whole track agrees on much more than the tracker's: track again from it
        tracked = 60 * fps / float(np.median(np.diff(beat_frames)))
        bpm, score = strongest_tempo(low_rise, fps)
        if abs(bpm / tracked - 1) > 0.03 and comb_score(low_rise, fps, tracked) < 0.8 * score:
            log(f"  tempo: {tracked:.1f} BPM tracked, {bpm:.2f} BPM fits the whole track better: tracking again")
            beat_frames = track_beats(onset_env, np.full_like(bpm_curve, bpm), fps)
    if tempo == "half":  # manual: the song is half as fast as counted (e.g. hip-hop counted double)
        strength = np.array([onset_env[max(b - 1, 0) : b + 2].max() for b in beat_frames])
        keep = 0 if strength[0::2].mean() >= strength[1::2].mean() else 1
        beat_frames = beat_frames[keep::2]
        log(f"  tempo halved on request: {60 * fps / np.median(np.diff(beat_frames)):.1f} BPM")
    elif tempo == "double":  # manual: twice as fast as counted (insert a beat between each pair)
        mids = (beat_frames[:-1] + beat_frames[1:]) // 2
        beat_frames = np.sort(np.concatenate([beat_frames, mids]))
        log(f"  tempo doubled on request: {60 * fps / np.median(np.diff(beat_frames)):.1f} BPM")
    beat_times = refine_beats(beat_frames, onset_env, fps)
    grid = constant_grid(beat_times, low_rise, fps)
    if grid is not None:  # a track at one tempo: one grid, on the kick
        beat_times = grid
        beat_frames = np.round(beat_times * fps).astype(int)
    log(f"  beat grid: {'one tempo' if grid is not None else 'following the tempo'}")
    audio, audio_sr = sf.read(str(path), dtype="float32", always_2d=True)
    heard = attack_offset(audio.mean(axis=1), audio_sr, beat_times)
    fine_snare, fine_db, fine_fps, fine_bands = fine_envelopes(audio.mean(axis=1), audio_sr)
    del audio
    beat_times = beat_times + heard  # onsets are noticed a little before they are loud: date them as heard
    onsets = {k: (t + heard, s) for k, (t, s) in onsets.items()}
    log(f"  beats on the attack: {heard * 1000:+.0f} ms")
    onsets["kick"] = beat_kicks(feats["flux_kick"], beat_frames, fps, beat_times)
    accent_env = normalize(feats["flux_all"]) + normalize(
        np.maximum(0, np.diff(feats["bass"], prepend=feats["bass"][0]))
    )
    downbeat_idx = downbeats(beat_frames, accent_env, low)
    phrases = build_phrases(feats, fps, beat_times, downbeat_idx, onsets)
    # the snare rolls into the drops (looked for from the drop before) and the pauses before them, on the
    # audio's own clock (not dated as heard)
    at = [i for i, p in enumerate(phrases) if i and p.drop_score >= DROP_THRESHOLD]
    starts = [phrases[i].start - heard for i in at]
    builds = [phrases[i - 1].start - heard for i in at]
    others = [(phrases[i - 1].start - heard, phrases[i].start - heard) for i in range(1, len(phrases)) if i not in at]
    roll, pauses, roll_hits = snare_rolls(
        fine_snare, fine_db, fine_fps, beat_times - heard, beat_times[downbeat_idx] - heard,
        list(zip([0.0, *starts[:-1]], builds, starts)), others, fine_bands,
    )  # fmt: skip
    del fine_bands
    pauses = pauses + heard
    roll_hits[:, 0] += heard
    bar_chroma = _bar_chroma(feats["chroma"], fps, beat_times[downbeat_idx])
    log(
        f"  {len(beat_times)} beats, {len(downbeat_idx)} bars, {len(phrases)} phrases, "
        + ", ".join(f"{len(v[0])} {k}" for k, v in onsets.items())
    )

    a = Analysis(
        path=str(path),
        duration=float(duration),
        sr=sr,
        fps=fps,
        bpm=set_bpm(beat_times),
        bands_db={k: feats[k] for k in BANDS},
        rms_db=feats["rms"],
        onsets=onsets,
        beats=beat_times.astype(np.float64),
        downbeats=downbeat_idx,
        phrases=phrases,
        lead_pitch=lead_pitch,
        lead_pc=lead_pc,
        lead_tonal=lead_tonal,
        stutter_gate=stutter_gate,
        stutter_strength=stutter_strength,
        roll=roll,
        roll_hits=roll_hits,
        pauses=pauses,
        bar_chroma=bar_chroma,
    )
    _save(a, npz_path, json_path)
    return _finish(a, path)


def _bar_chroma(chroma: np.ndarray, fps: float, db_times: np.ndarray) -> np.ndarray:
    """Per bar: its harmony, the pitch classes' strengths (amplitude, so a loud bass note doesn't drown the
    chord) scaled to unit length."""
    rows = []
    for t0, t1 in zip(db_times[:-1], db_times[1:]):
        s = int(t0 * fps)
        c = np.sqrt(chroma[s : max(int(t1 * fps), s + 1)]).mean(axis=0)
        rows.append(c / (np.linalg.norm(c) + 1e-9))
    return np.array(rows, dtype=np.float32).reshape(-1, 12)


def _finish(a: Analysis, path: Path) -> Analysis:
    """What isn't cached with the analysis itself: the separated notes, the song's form and the genre (your
    choice can change both), and, for a track with a program of its own (cinematic), its hits."""
    from amadeus.audio import form, genre, hits

    a = _with_notes(a, path)
    _with_vocal_pickups(a, path)
    song = form.facts(a, path)  # (what the audio says: verses and choruses, or drops)
    call = genre.detect(a, song=song)
    a.genre, a.genre_source, a.genre_facts = call.genre, call.source, call.facts
    form.apply(a, call, song)
    if call.program == "cinematic":
        a.hits = hits.load_or_detect(path)
    return a


def _with_vocal_pickups(a: Analysis, path: Path) -> None:
    """Vocal lead-ins into sections, once the track has been separated (amadeus/audio/phrases.py)."""
    from amadeus.audio import stems as stemlib
    from amadeus.audio.phrases import vocal_pickups

    got = stemlib.vocal_envelope(path)
    if got is not None:
        db = a.downbeats if a.downbeats.dtype.kind == "f" else a.beats[a.downbeats]
        vocal_pickups(a.phrases, a.beats, db, *got)


def _with_notes(a: Analysis, path: Path) -> Analysis:
    """Attach the synth/melody notes of the separated instruments, if the track has been separated
    (amadeus/stems.py, in the background). Without them the analysis works as before."""
    from amadeus.audio import stems as stemlib

    notes = stemlib.load_notes(path)
    if notes is not None:
        a.synth_notes = notes
        a.instruments = stemlib.load_instruments(path)
        if a.instruments is not None:
            _split_on_melody(a)
            t, probs, names = a.instruments["t"], a.instruments["probs"], a.instruments["names"]
            for ph in a.phrases:
                m = (t >= ph.start) & (t < ph.end)
                if m.any():
                    mean = probs[m].mean(0)
                    ph.instruments = ", ".join(
                        f"{names[j]} {mean[j]:.2f}" for j in np.argsort(-mean)[:3] if mean[j] >= 0.15
                    )
    return a


MELODY_SPLIT = 2.5  # a melodic change this clear (see _melody_changes) splits a phrase
MELODY_MIN_BARS = 4  # …into parts of at least this many bars, on 4-bar lines from the phrase's start


def _melody_changes(a: Analysis) -> tuple[np.ndarray, np.ndarray]:
    """Per bar line: how much the melodic part changes there, the four bars after against the four before. Its
    sound (the instrument model's description, cosine distance, relative to the track's usual change) plus three
    times the jump in register (the median pitch of its notes, 0..1). A new melody, a new instrument, a lead
    that moves an octave up: what a DJ hears as "here comes the next part" though the drums stay the same."""
    ins = a.instruments
    jt = np.asarray(ins["t"], float)
    snd = np.asarray(ins["sound"], np.float32)
    snd = snd / (np.linalg.norm(snd, axis=1, keepdims=True) + 1e-9)
    nt, _, pitch = (np.asarray(x, float) for x in a.synth_notes)
    bars = a.beats[a.downbeats] if len(a.downbeats) else a.beats[::4]
    w = 4 * float(np.median(np.diff(bars))) if len(bars) > 1 else 8.0
    sound, reg = np.zeros(len(bars)), np.zeros(len(bars))
    for k, d in enumerate(bars):
        b, f = snd[(jt >= d - w) & (jt < d)], snd[(jt >= d) & (jt < d + w)]
        if len(b) >= 2 and len(f) >= 2:
            mb, mf = b.mean(0), f.mean(0)
            sound[k] = 1 - float(mb @ mf / (np.linalg.norm(mb) * np.linalg.norm(mf) + 1e-9))
        pb, pf = pitch[(nt >= d - w) & (nt < d)], pitch[(nt >= d) & (nt < d + w)]
        if len(pb) > 2 and len(pf) > 2:
            reg[k] = abs(float(np.median(pf)) - float(np.median(pb)))
    usual = float(np.median(sound[sound > 0])) if (sound > 0).any() else 1.0
    return bars, sound / max(usual, 1e-6) + 3 * reg


def _split_on_melody(a: Analysis) -> None:
    """Split phrases where a new melody comes in on a 4-bar line inside them: the drums and energy (what the phrase
    grid listens to) can stay the same while the music clearly moves on. The new phrase is marked for the
    director; it keeps the old phrase's measurements (drops and pickups belong to the first part)."""
    from dataclasses import replace

    if a.synth_notes is None or not len(a.phrases):
        return
    bars, score = _melody_changes(a)
    if not len(bars):
        return
    bar = float(np.median(np.diff(bars))) if len(bars) > 1 else 2.0
    out = []
    todo = list(a.phrases)
    while todo:
        ph = todo.pop(0)
        best, best_score = None, MELODY_SPLIT
        for k, d in enumerate(bars):
            n = (d - ph.start) / bar
            if (
                MELODY_MIN_BARS - 0.1 <= n <= (ph.end - ph.start) / bar - MELODY_MIN_BARS + 0.1
                and abs(n - round(n / 4) * 4) < 0.1
            ) and score[k] > best_score:
                best, best_score = float(d), float(score[k])
        if best is None:
            out.append(ph)
            continue
        nb = int(round((best - ph.start) / bar))
        first = replace(ph, end=best, bars=nb)
        second = replace(ph, start=best, bars=max(1, ph.bars - nb), drop_score=0.0, pickup_beats=0, pickup_kind="",
                         pickup_start=best, melody_change=True)  # fmt: skip
        out.append(first)
        todo.insert(0, second)  # (it may split again)
    for i, ph in enumerate(out):
        ph.index = i
    a.phrases = out


def _save(a: Analysis, npz_path: Path, json_path: Path):
    arrays = {f"band_{k}": v for k, v in a.bands_db.items()}
    arrays |= {f"on_{k}_t": v[0] for k, v in a.onsets.items()} | {f"on_{k}_s": v[1] for k, v in a.onsets.items()}
    np.savez_compressed(
        npz_path,
        rms=a.rms_db,
        beats=a.beats,
        downbeats=a.downbeats,
        lead_pitch=a.lead_pitch,
        lead_pc=a.lead_pc,
        lead_tonal=a.lead_tonal,
        stutter_gate=a.stutter_gate,
        stutter_strength=a.stutter_strength,
        roll=a.roll,
        roll_hits=a.roll_hits if a.roll_hits is not None else np.zeros((0, 2)),
        pauses=a.pauses,
        bar_chroma=a.bar_chroma if a.bar_chroma is not None else np.zeros((0, 12), np.float32),
        **arrays,
        **(
            {"syn_t": a.synth_notes[0], "syn_s": a.synth_notes[1], "syn_p": a.synth_notes[2]}
            if a.synth_notes is not None
            else {}
        ),
    )
    meta = dict(path=a.path, duration=a.duration, sr=a.sr, fps=a.fps, bpm=a.bpm, phrases=[asdict(p) for p in a.phrases])
    json_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")


def _load(npz_path: Path, json_path: Path) -> Analysis:
    z = np.load(npz_path)
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    return Analysis(
        path=meta["path"],
        duration=meta["duration"],
        sr=meta["sr"],
        fps=meta["fps"],
        bpm=meta["bpm"],
        bands_db={k: z[f"band_{k}"] for k in BANDS},
        rms_db=z["rms"],
        onsets={k: (z[f"on_{k}_t"], z[f"on_{k}_s"]) for k in ["kick", "snare", "hat", "accent", "lead"]},
        beats=z["beats"],
        downbeats=z["downbeats"],
        phrases=[Phrase(**p) for p in meta["phrases"]],
        lead_pitch=z["lead_pitch"],
        lead_pc=z["lead_pc"],
        lead_tonal=z["lead_tonal"],
        stutter_gate=z["stutter_gate"],
        stutter_strength=z["stutter_strength"],
        roll=z["roll"],
        roll_hits=z["roll_hits"] if "roll_hits" in z.files else None,
        pauses=z["pauses"],
        bar_chroma=z["bar_chroma"] if "bar_chroma" in z.files else None,
        synth_notes=(z["syn_t"], z["syn_s"], z["syn_p"]) if "syn_t" in z.files else None,
    )
