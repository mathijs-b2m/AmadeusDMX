"""Watch VirtualDJ and Amadeus DMX while they run: CPU, memory, threads, GPU, crashes.

    python -m amadeus monitor            one line every 2 s, warnings at once, CSV in .cache/monitor/

Uses only macOS tools that need no admin rights (ps, sysctl, ioreg). Together with `live --health`
(packets from VirtualDJ, deck positions, light-loop timing) this tells apart a VirtualDJ stall, one of
ours, a crash and a machine that is simply out of breath.
"""

from __future__ import annotations

import csv
import os
import re
import subprocess
import time
from pathlib import Path

from amadeus import paths

WATCH = {"vdj": ["VirtualDJ"], "live": ["amadeus live", "amadeus play"]}
REPORT_DIRS = [Path.home() / "Library/Logs/DiagnosticReports", Path("/Library/Logs/DiagnosticReports")]


def _fmt(p: dict | None, name: str) -> str:
    if not p:
        return f"{name} {'— not running —':>28}"
    return f"{name} {p['cpu']:5.1f}% {p['mem_mb']:6.0f}MB {p['threads']:3d}thr {p['state']:<3}"


def _run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _pid(patterns: list[str]) -> int | None:
    for line in _run("ps", "-axo", "pid=,command=").splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if any(p in cmd for p in patterns) and "amadeus monitor" not in cmd and "grep" not in cmd:
            if patterns == WATCH["vdj"] and "/VirtualDJ.app/" not in cmd:
                continue
            return int(pid)
    return None


def _proc(pid: int | None) -> dict:
    if pid is None:
        return {}
    out = _run("ps", "-o", "pcpu=,rss=,state=", "-p", str(pid)).split()
    if len(out) < 3:
        return {}
    threads = max(0, len(_run("ps", "-M", "-p", str(pid)).splitlines()) - 1)
    return {"cpu": float(out[0]), "mem_mb": int(out[1]) / 1024, "state": out[2], "threads": threads}


def _system() -> dict:
    ncpu = os.cpu_count() or 1
    total = sum(float(x) for x in _run("ps", "-Ao", "pcpu=").split() if x.replace(".", "", 1).isdigit())
    load = _run("sysctl", "-n", "vm.loadavg").strip("{} \n").split()
    free = _run("sysctl", "-n", "kern.memorystatus_level").strip()
    m = re.search(r'"Device Utilization %"=(\d+)', _run("ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"))
    return {
        "cpu_total": total / ncpu,
        "load1": float(load[0]) if load else 0.0,
        "mem_free_pct": int(free) if free.isdigit() else -1,
        "gpu": int(m.group(1)) if m else -1,
    }


def _reports() -> set[Path]:
    out = set()
    for d in REPORT_DIRS:
        try:
            out |= {p for p in d.iterdir() if p.is_file()}
        except OSError:
            pass
    return out


def run(interval: float = 1.0, print_every: int = 2):
    out_dir = paths.CACHE / "monitor"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}.csv"
    seen_reports = _reports()
    prev_pids: dict[str, int | None] = {}
    waiting = {"vdj": 0, "live": 0}  # consecutive samples in state U/D (a short one is just a track loading)
    mem_hist: dict[str, list[float]] = {"vdj": [], "live": []}
    gpu_high = 0
    started: dict[str, float] = {k: time.monotonic() for k in WATCH}  # (re)start time per app
    fields = [
        "time",
        "vdj_pid",
        "vdj_cpu",
        "vdj_mem_mb",
        "vdj_threads",
        "vdj_state",
        "live_pid",
        "live_cpu",
        "live_mem_mb",
        "live_threads",
        "cpu_total",
        "load1",
        "mem_free_pct",
        "gpu",
    ]
    print(f"Monitoring VirtualDJ + Amadeus DMX every {interval:g} s → {path}   (Ctrl+C to stop)", flush=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        n = 0
        while True:
            t0 = time.monotonic()
            now = time.strftime("%H:%M:%S")
            pids = {k: _pid(v) for k, v in WATCH.items()}
            procs = {k: _proc(p) for k, p in pids.items()}
            sysi = _system()
            row = {"time": now, **sysi}
            for k in ("vdj", "live"):
                row[f"{k}_pid"] = pids[k]
                for m in ("cpu", "mem_mb", "threads", "state"):
                    if f"{k}_{m}" in fields:
                        row[f"{k}_{m}"] = procs[k].get(m, "")
            w.writerow(row)
            f.flush()

            warn = []
            for k, name in (("vdj", "VirtualDJ"), ("live", "Amadeus live")):
                if k in prev_pids and prev_pids[k] and not pids[k]:
                    warn.append(f"{name} (pid {prev_pids[k]}) is GONE")
                elif k in prev_pids and pids[k] and prev_pids[k] != pids[k]:
                    warn.append(f"{name} (re)started, pid {pids[k]}")
                    mem_hist[k] = []  # memory grows while an app starts: not a leak
                    started[k] = time.monotonic()
                if procs[k].get("cpu", 0) > 150:
                    warn.append(f"{name} CPU {procs[k]['cpu']:.0f}%")
                waiting[k] = waiting[k] + 1 if procs[k].get("state", "").startswith(("U", "D")) else 0
                if waiting[k] == 3 or (waiting[k] > 3 and waiting[k] % 10 == 0):
                    warn.append(f"{name} has been waiting on disk/kernel for {waiting[k] * interval:.0f} s (hang?)")
                if procs[k].get("mem_mb") and time.monotonic() - started.get(k, 0) > 180:
                    hist = (mem_hist[k] + [procs[k]["mem_mb"]])[-120:]
                    mem_hist[k] = hist
                    if (
                        len(hist) == 120
                        and hist[-1] - hist[0] > 1500
                        and all(b >= a - 50 for a, b in zip(hist, hist[1:]))
                    ):
                        warn.append(f"{name} memory grew {hist[-1] - hist[0]:.0f} MB in 2 minutes without stopping")
                        mem_hist[k] = []
            if 0 <= sysi["mem_free_pct"] < 15:
                warn.append(f"memory pressure: {sysi['mem_free_pct']}% free")
            gpu_high = gpu_high + 1 if sysi["gpu"] >= 90 else 0
            if gpu_high == 10:  # 10 s in a row, not a single busy frame
                warn.append(f"GPU above 90% for 10 s (now {sysi['gpu']}%): close extra visualiser windows?")
            new = _reports() - seen_reports
            for r in sorted(new):
                if re.search(r"virtual|python|amadeus", r.name, re.I):
                    warn.append(f"CRASH/HANG REPORT: {r}")
            seen_reports |= new
            prev_pids = pids

            if n % print_every == 0 or warn:
                print(
                    f"{now}  {_fmt(procs['vdj'], 'VDJ')}  |  {_fmt(procs['live'], 'live')}  |  "
                    f"system {sysi['cpu_total']:4.1f}% "
                    f"load {sysi['load1']:.1f}  mem free {sysi['mem_free_pct']}%  GPU {sysi['gpu']}%",
                    flush=True,
                )
            for msg in warn:
                print(f"{now}  ⚠ {msg}", flush=True)
            n += 1
            time.sleep(max(0.0, interval - (time.monotonic() - t0)))
