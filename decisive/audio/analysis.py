"""Offline audio analysis: band energies, onsets, beats, bars and phrases.

Everything is computed once per recording and cached, so the player and the
director only ever read precomputed arrays. Only numpy/scipy are used."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import soundfile as sf

from decisive import paths
from decisive.audio.beats import (
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
from decisive.audio.features import (
    BANDS,
    HOP,
    lead_features,
    normalize,
    pick_peaks,
    spectral_features,
    stutter_features,
)
from decisive.audio.model import Analysis, Phrase
from decisive.audio.phrases import build_phrases

ANALYSIS_VERSION = 39


def cache_paths(path: Path, cache_dir: Path, tempo: str | None = None):
    st = path.stat()
    key = hashlib.sha1(
        f"{path.resolve()}|{st.st_size}|{st.st_mtime}|{ANALYSIS_VERSION}|{tempo or ''}".encode()
    ).hexdigest()[:12]
    base = cache_dir / f"{path.stem}.{key}"
    return Path(f"{base}.analysis.npz"), Path(f"{base}.analysis.json")


def readable_audio(path: str | Path, cache_dir: str | Path = paths.CACHE) -> Path:
    """The file itself if soundfile can read it (WAV, MP3, FLAC, OGG, AIFF); otherwise (e.g. M4A/AAC)
    a WAV copy decoded once with ffmpeg into the cache."""
    import shutil
    import subprocess

    path = Path(path)
    try:
        sf.info(str(path))
        return path
    except Exception:
        pass
    if not shutil.which("ffmpeg"):
        raise SystemExit(f"Can't read {path.name} directly and ffmpeg isn't installed (brew install ffmpeg).")
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:8]
    out = Path(cache_dir) / f"{path.stem}.{key}.decoded.wav"
    if not out.exists():
        print(f"Decoding {path.name} with ffmpeg …")
        Path(cache_dir).mkdir(exist_ok=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(path), str(out)], check=True)
    return out


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
    )
    _save(a, npz_path, json_path)
    return _finish(a, path)


def _finish(a: Analysis, path: Path) -> Analysis:
    """What isn't cached with the analysis itself: the separated notes, the genre (your choice can change it),
    and, for a track with a program of its own (cinematic), its hits."""
    from decisive.audio import genre, hits

    a = _with_notes(a, path)
    _with_vocal_pickups(a, path)
    call = genre.detect(a)
    a.genre, a.genre_source, a.genre_facts = call.genre, call.source, call.facts
    if call.program == "cinematic":
        a.hits = hits.load_or_detect(path)
    return a


def _with_vocal_pickups(a: Analysis, path: Path) -> None:
    """Vocal lead-ins into sections, once the track has been separated (decisive/audio/phrases.py)."""
    from decisive.audio import stems as stemlib
    from decisive.audio.phrases import vocal_pickups

    got = stemlib.vocal_envelope(path)
    if got is not None:
        db = a.downbeats if a.downbeats.dtype.kind == "f" else a.beats[a.downbeats]
        vocal_pickups(a.phrases, a.beats, db, *got)


def _with_notes(a: Analysis, path: Path) -> Analysis:
    """Attach the synth/melody notes of the separated instruments, if the track has been separated
    (decisive/stems.py, in the background). Without them the analysis works as before."""
    from decisive.audio import stems as stemlib

    notes = stemlib.load_notes(path)
    if notes is not None:
        a.synth_notes = notes
    return a


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
        **arrays,
        **(
            {"syn_t": a.synth_notes[0], "syn_s": a.synth_notes[1], "syn_p": a.synth_notes[2]}
            if a.synth_notes is not None
            else {}
        ),
    )
    meta = dict(path=a.path, duration=a.duration, sr=a.sr, fps=a.fps, bpm=a.bpm, phrases=[asdict(p) for p in a.phrases])
    json_path.write_text(json.dumps(meta, indent=1))


def _load(npz_path: Path, json_path: Path) -> Analysis:
    z = np.load(npz_path)
    meta = json.loads(json_path.read_text())
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
        synth_notes=(z["syn_t"], z["syn_s"], z["syn_p"]) if "syn_t" in z.files else None,
    )
