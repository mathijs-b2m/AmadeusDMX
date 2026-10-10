"""Find Art-Net nodes, list their RDM fixtures, match them to the library and auto-patch.

Fixtures without RDM can't be discovered (plain DMX is one-way); add those
with `python -m decisive patch MODEL:COUNT ...` instead. Both paths end in
`write_rig`, which lays out the stage and assigns non-overlapping addresses.
"""

from __future__ import annotations

import re
import socket
import struct
import time

from decisive.dmx import rdm
from decisive.library import fixtures as fxlib

# ---------------------------------------------------------------- rig building (shared with `patch`)


def assign_addresses(items: list[dict], start: int = 1) -> None:
    """Pack fixtures back-to-back per universe, moving heads first."""
    nxt: dict[int, int] = {}
    for it in sorted(items, key=lambda i: not fxlib.is_moving(fxlib.get(i["fixture"]))):
        u = it["universe"]
        n = fxlib.footprint(it)
        while nxt.get(u, start) + n - 1 > 512:  # universe full: continue in the next one
            u += 1
            if u > 32767:
                raise SystemExit(f"No room for {it['id']}")
        it["universe"] = u
        it["address"] = nxt.get(u, start)
        nxt[u] = it["address"] + n


def layout(items: list[dict]) -> None:
    """Heads spread across the truss, pars/bars across the front."""

    def spread(group, lo, hi):
        for i, it in enumerate(group):
            it["x"] = round((lo + hi) / 2 if len(group) == 1 else lo + (hi - lo) * i / (len(group) - 1), 3)

    heads = [i for i in items if fxlib.is_moving(fxlib.get(i["fixture"]))]
    pars = [i for i in items if i not in heads]
    spread(heads, 0.2, 0.8)
    spread(pars, 0.3, 0.7)
    for it in pars:
        n = len(fxlib.heads(fxlib.get(it["fixture"]), it["mode"]))
        if n > 1:
            it["width"] = round(min(0.6, 0.6 / len(pars)), 3)
    for it in heads:
        it.setdefault("mount", "stand")  # stand | hang | floor: see decisive/geometry.py


def new_ids(items: list[dict]) -> None:
    counts: dict[str, int] = {}
    for it in items:
        m = re.match(r"[a-z]+", it["fixture"].split("/")[1])  # "fuze75s-spot" → "fuze"
        base = m.group(0) if m else "fx"
        counts[base] = counts.get(base, 0) + 1
        it.setdefault("id", f"{base}{counts[base]}")


def write_rig(items: list[dict], show, artnet: dict | None = None) -> dict:
    """The fixtures (and the node) into the show's set; the rig keeps its trusses and stage."""
    rig = show.load()
    rig["artnet"] = artnet or rig.get("artnet", {"ip": "192.168.1.50", "port": 6454, "fps": 40})
    rig.setdefault("safety", {"max_flash_hz": 3.0, "master": 1.0})
    from decisive.rig.store import PLACEMENT_KEYS

    for it in items:  # the gear only: where they hang is up to the rig (auto-mount or the rig editor)
        for k in PLACEMENT_KEYS:
            it.pop(k, None)
    rig["fixtures"] = items
    rig["artnet"].setdefault("fps", 40)
    show.save(rig)
    return rig


def print_patch(items: list[dict]) -> None:
    print(f"\n  {'id':<10} {'fixture':<24} {'mode':>5}  {'universe':>8}  {'address':>7}  channels")
    for it in sorted(items, key=lambda i: (i["universe"], i["address"])):
        d = fxlib.get(it["fixture"])
        n = fxlib.footprint(it)
        print(
            f"  {it['id']:<10} {d['manufacturer'] + ' ' + d['model']:<24} {it['mode']:>5}  {it['universe']:>8}"
            f"  {it['address']:>7}  {it['address']}–{it['address'] + n - 1}"
        )


def manual_patch(specs: list[str], universe: int, modes: dict[str, str], show) -> dict:
    """`patch beamz/fuze75s-spot:2 ayra/compar-kit-2` → rig.json."""
    items = []
    for spec in specs:
        key, _, n = spec.partition(":")
        defn = fxlib.get(key)
        mode = modes.get(key, fxlib.default_mode(defn))
        fxlib.channels(defn, mode)  # validates the mode
        items += [{"fixture": key, "mode": mode, "universe": universe} for _ in range(int(n or 1))]
    new_ids(items)
    assign_addresses(items)
    layout(items)
    rig = write_rig(items, show)
    print_patch(items)
    print(
        f"\nWrote the set '{show.set or show.label}'. Set each fixture to the DMX mode and start address above "
        "on its display."
    )
    return rig


# ---------------------------------------------------------------- network discovery


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def match_library(manufacturer: str, model: str) -> dict | None:
    m, n = _norm(manufacturer), _norm(model)
    for d in fxlib.library().values():
        if _norm(d["manufacturer"]) == m and (
            _norm(d["model"]) == n or _norm(d["model"]) in n or n in _norm(d["model"])
        ):
            return d
    return None


class Client:
    def __init__(self, target: tuple[str, int] | None):
        """target=None → real network (broadcast on 6454); otherwise a specific node, e.g. the simulator."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if target is None:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                self.sock.bind(("0.0.0.0", 6454))  # nodes reply to port 6454
            except OSError as e:
                raise SystemExit("Port 6454 is in use (another Art-Net app?). Close it and retry.") from e
            self.targets = [("255.255.255.255", 6454), ("2.255.255.255", 6454), ("10.255.255.255", 6454)]
        else:
            self.sock.bind(("0.0.0.0", 0))
            self.targets = [target]
        self.tn = 0

    def _collect(self, seconds: float, want_op: int):
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            self.sock.settimeout(left)
            try:
                pkt, addr = self.sock.recvfrom(2048)
            except TimeoutError:
                return
            if rdm.opcode(pkt) == want_op:
                yield pkt, addr

    def poll(self, seconds: float = 2.5) -> list[tuple[rdm.Node, tuple]]:
        for attempt in range(2):  # UDP over Wi-Fi drops packets: ask twice
            for t in self.targets:
                try:
                    self.sock.sendto(rdm.art_poll(), t)
                except OSError:
                    pass  # e.g. no route for 2.x/10.x broadcast on this machine
            if attempt == 0:
                time.sleep(0.3)
        nodes: dict[str, tuple[rdm.Node, tuple]] = {}
        for pkt, addr in self._collect(seconds, rdm.OP_POLL_REPLY):
            node = rdm.parse_poll_reply(pkt)
            if node.ip in nodes:  # Art-Net 4 nodes send one reply per port ("bind index"): merge them
                known = nodes[node.ip][0]
                known.outputs = sorted(set(known.outputs) | set(node.outputs))
                if known.short_name != node.short_name:
                    known.short_name = known.long_name.split("(")[0].strip() or known.short_name
            else:
                nodes[node.ip] = (node, addr)
        return list(nodes.values())

    def tod(self, addr, port_address: int) -> list[bytes]:
        self.sock.sendto(rdm.art_tod_request(port_address), addr)
        uids = []
        for pkt, _ in self._collect(1.0, rdm.OP_TOD_DATA):
            pa, block = rdm.parse_tod_data(pkt)
            if pa == port_address:
                uids += block
        return list(dict.fromkeys(uids))

    def request(self, addr, port_address: int, uid: bytes, cc: int, pid: int, data: bytes = b"") -> bytes | None:
        for _ in range(3):
            self.tn = (self.tn + 1) & 0xFF
            msg = rdm.RdmMessage(
                dest=uid, src=rdm.CONTROLLER_UID, tn=self.tn, port_or_response=1, cc=cc, pid=pid, data=data
            )
            self.sock.sendto(rdm.art_rdm(port_address, rdm.rdm_encode(msg)), addr)
            for pkt, _ in self._collect(0.5, rdm.OP_RDM):
                _, reply = rdm.parse_art_rdm(pkt)
                if reply.src == uid and reply.tn == self.tn and reply.pid == pid:
                    return reply.data if reply.port_or_response == rdm.RESPONSE_ACK else None
        return None


def discover(target: tuple[str, int] | None, show, readdress: bool, write: bool) -> None:
    c = Client(target)
    print("Polling for Art-Net nodes …")
    nodes = c.poll()
    if not nodes:
        print("No Art-Net nodes answered. Is the node powered, on this subnet, and not blocked by a firewall?")
        return
    for node, _ in nodes:
        print(f"  ✓ {node}")
    node, addr = nodes[0]
    if len(nodes) > 1:
        print(f"Using the first node ({node.ip}).")

    items, unknown = [], []
    for pa in node.outputs:
        uids = c.tod(addr, pa)
        print(f"\nUniverse {pa}: {len(uids)} RDM device(s)")
        for uid in uids:
            raw = c.request(addr, pa, uid, rdm.GET, rdm.DEVICE_INFO)
            if raw is None:
                print(f"  {rdm.uid_str(uid)}  no answer to DEVICE_INFO")
                continue
            info = rdm.DeviceInfo.unpack(raw)
            man = (c.request(addr, pa, uid, rdm.GET, rdm.MANUFACTURER_LABEL) or b"?").decode(errors="replace")
            model = (c.request(addr, pa, uid, rdm.GET, rdm.DEVICE_MODEL_DESCRIPTION) or b"?").decode(errors="replace")
            defn = match_library(man, model)
            mode = fxlib.mode_for_footprint(defn, info.footprint) if defn else None
            status = (
                f"→ {defn['key']} ({mode})"
                if defn and mode
                else "→ not in library"
                if not defn
                else f"→ {defn['key']} but no {info.footprint}ch mode"
            )
            print(f"  {rdm.uid_str(uid)}  {man} {model}, {info.footprint} ch @ {info.start_address}  {status}")
            if defn and mode:
                items.append(
                    {
                        "fixture": defn["key"],
                        "mode": mode,
                        "universe": pa,
                        "address": info.start_address,
                        "_uid": uid,
                        "_pa": pa,
                    }
                )
            else:
                unknown.append(f"{man} {model}")

    if not items:
        print("\nNo known RDM fixtures found. Non-RDM fixtures (like most budget fixtures) can't be discovered:")
        print("  python -m decisive patch beamz/fuze75s-spot:2 ayra/compar-kit-2")
        if write:  # still worth saving where the node is
            rig = show.load()
            rig["artnet"] = {**rig.get("artnet", {}), "ip": node.ip, "port": addr[1]}
            rig["artnet"].setdefault("fps", 40)
            show.save(rig)
            print(f"\nSaved node {node.ip}:{addr[1]} in {show.label} (fixtures unchanged).")
        return

    new_ids(items)
    problems = fxlib.validate({"fixtures": items})
    if problems:
        print("\nAddress conflicts:")
        for p in problems:
            print(f"  ⚠ {p}")
    if problems or readdress:
        if not readdress:
            print("Re-run with --readdress to fix them over RDM.")
        else:
            assign_addresses(items)
            print("\nRe-addressing over RDM …")
            for it in items:
                ok = c.request(
                    addr, it["_pa"], it["_uid"], rdm.SET, rdm.DMX_START_ADDRESS, struct.pack(">H", it["address"])
                )
                back = c.request(addr, it["_pa"], it["_uid"], rdm.GET, rdm.DMX_START_ADDRESS)
                now = struct.unpack(">H", back)[0] if back else None
                done = ok is not None and now == it["address"]
                print(f"  {it['id']:<10} → {it['address']:<4} {'✓' if done else '✗ failed'}")
            problems = fxlib.validate({"fixtures": items})

    for it in items:
        it.pop("_uid"), it.pop("_pa")
    layout(items)
    print_patch(items)
    if unknown:
        print(f"\nNot in the library (add a JSON file in fixtures/): {', '.join(unknown)}")
    if write and not problems:
        write_rig(items, show, artnet={"ip": node.ip, "port": addr[1], "fps": 40})
        print(f"\nWrote {show.label} (node {node.ip}:{addr[1]}).")
    elif write:
        print("\nNot writing the rig while addresses conflict.")
