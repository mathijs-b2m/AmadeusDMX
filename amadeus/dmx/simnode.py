"""A simulated Showtec Net-2/5 with virtual fixtures behind it.

Answers ArtPoll, ArtTodRequest and ArtRdm like a real node with RDM-capable
fixtures, and decodes incoming ArtDmx through the fixture library so you can
see what each fixture would physically do. Listens on 127.0.0.1:6455 by
default so it can run next to the discovery client on one machine.
"""

from __future__ import annotations

import socket
import struct
import time
import zlib
from dataclasses import dataclass, field

from amadeus.dmx import rdm
from amadeus.library import fixtures as fxlib

SHORT_NAME = "NET-2/5 SIM"
LONG_NAME = "Showtec NET-2/5 Pocket (simulated by Amadeus DMX)"


@dataclass
class VirtualFixture:
    uid: bytes
    key: str
    mode: str
    universe: int
    address: int = 1  # factory default: everything at 1, which is exactly the problem discovery solves
    rdm: bool = True
    defn: dict = field(init=False)

    def __post_init__(self):
        self.defn = fxlib.get(self.key)

    @property
    def modes(self) -> list[str]:
        return list(self.defn["modes"])

    def info(self) -> rdm.DeviceInfo:
        return rdm.DeviceInfo(
            model_id=zlib.crc32(self.key.encode()) & 0xFFFF,
            category=0x0101 if "head" in self.defn["kind"] else 0x0509,
            software=1,
            footprint=len(self.defn["modes"][self.mode]),
            personality=self.modes.index(self.mode) + 1,
            personality_count=len(self.modes),
            start_address=self.address,
        )


def build(spec: str, universe: int, rdm_capable: bool) -> list[VirtualFixture]:
    """'beamz/fuze75s-spot:2,ayra/compar-kit-2' → virtual fixtures, all at address 1."""
    out = []
    for part in filter(None, spec.split(",")):
        key, _, n = part.partition(":")
        defn = fxlib.get(key)
        for _ in range(int(n or 1)):
            uid = struct.pack(">HI", 0x7FF0, 0x1000 + len(out))
            out.append(VirtualFixture(uid, key, fxlib.default_mode(defn), universe, rdm=rdm_capable))
    return out


def preaddress(fixtures: list[VirtualFixture], show) -> bool:
    """Give virtual fixtures the addresses/modes the set expects, matched by model in patch order."""
    patched = show.load().get("fixtures", [])
    if not patched:
        return False
    queues: dict[str, list[dict]] = {}
    for fx in sorted((f for f in patched if fxlib.patched(f)), key=lambda f: (f["universe"], f["address"])):
        queues.setdefault(fx["fixture"], []).append(fx)
    for f in fixtures:
        if queues.get(f.key):
            fx = queues[f.key].pop(0)
            f.address, f.universe, f.mode = fx["address"], fx["universe"], fx.get("mode", f.mode)
    return True


def run(
    spec: str,
    host: str = "127.0.0.1",
    port: int = 6455,
    universe: int = 0,
    rdm_capable: bool = True,
    monitor: bool = True,
    show=None,
):
    fixtures = build(spec, universe, rdm_capable)
    if show is not None and preaddress(fixtures, show):
        print(f"Addresses taken from {show.label} (use --factory to start everything at address 1)")
    by_uid = {f.uid: f for f in fixtures}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    sock.settimeout(0.5)
    dmx: dict[int, bytes] = {}
    print(f"Simulated {SHORT_NAME} listening on {host}:{port}, output universes [{universe}, {universe + 1}]")
    for f in fixtures:
        print(
            f"  {rdm.uid_str(f.uid)}  {f.defn['manufacturer']} {f.defn['model']:<14} {f.mode:>4} @ {f.address}"
            + ("" if f.rdm else "   (no RDM: invisible to discovery)")
        )
    last_print, last_rx, shown, idle_noted = 0.0, 0.0, None, False

    while True:
        try:
            pkt, addr = sock.recvfrom(1024)
        except TimeoutError:
            pkt = None
        if pkt:
            op = rdm.opcode(pkt)
            if op == rdm.OP_POLL:
                sock.sendto(
                    rdm.art_poll_reply(
                        host if host != "0.0.0.0" else "127.0.0.1",
                        SHORT_NAME,
                        LONG_NAME,
                        net=(universe >> 8) & 0x7F,
                        sub=(universe >> 4) & 0x0F,
                        sw_out=[universe & 0x0F, (universe + 1) & 0x0F],
                    ),
                    addr,
                )
            elif op == rdm.OP_TOD_REQUEST:
                for pa in rdm.parse_tod_request(pkt):
                    uids = [f.uid for f in fixtures if f.rdm and f.universe == pa]
                    sock.sendto(rdm.art_tod_data(pa, uids), addr)
            elif op == rdm.OP_RDM:
                pa, msg = rdm.parse_art_rdm(pkt)
                f = by_uid.get(msg.dest)
                if f and f.rdm:
                    reply = _handle_rdm(f, msg)
                    if reply is not None:
                        sock.sendto(rdm.art_rdm(pa, rdm.rdm_encode(reply)), addr)
            elif op == 0x5000:  # ArtDmx
                uni = pkt[14] | (pkt[15] << 8)
                length = struct.unpack_from(">H", pkt, 16)[0]
                dmx[uni] = pkt[18 : 18 + length]
                last_rx, idle_noted = time.monotonic(), False
        if monitor and dmx and not idle_noted and time.monotonic() - last_rx > 2.0:
            all_zero = not any(any(d) for d in dmx.values())
            print(
                "── no DMX for 2 s"
                + (" (last frame was a blackout: player stopped)" if all_zero else "")
                + ", waiting …",
                flush=True,
            )
            idle_noted = True
        if monitor and dmx and not idle_noted and time.monotonic() - last_print > 1.0:
            if dict(dmx) == shown:  # unchanged: don't repeat the same block
                continue
            shown = dict(dmx)
            last_print = time.monotonic()
            lines = []
            for f in fixtures:
                data = dmx.get(f.universe, b"")
                n = len(f.defn["modes"][f.mode])
                chunk = data[f.address - 1 : f.address - 1 + n]
                lines.append(f"  {f.defn['model']:<14}@{f.address:<3} {fxlib.decode(f.defn, f.mode, chunk)}")
            print(f"── DMX in, universe {universe} ──\n" + "\n".join(lines), flush=True)


def _handle_rdm(f: VirtualFixture, msg: rdm.RdmMessage) -> rdm.RdmMessage | None:
    def respond(cc, data=b""):
        return rdm.RdmMessage(
            dest=msg.src, src=f.uid, tn=msg.tn, port_or_response=rdm.RESPONSE_ACK, cc=cc, pid=msg.pid, data=data
        )

    if msg.cc == rdm.GET:
        if msg.pid == rdm.DEVICE_INFO:
            return respond(rdm.GET_RESPONSE, f.info().pack())
        if msg.pid == rdm.MANUFACTURER_LABEL:
            return respond(rdm.GET_RESPONSE, f.defn["manufacturer"].encode())
        if msg.pid == rdm.DEVICE_MODEL_DESCRIPTION:
            return respond(rdm.GET_RESPONSE, f.defn["model"].encode())
        if msg.pid == rdm.DMX_START_ADDRESS:
            return respond(rdm.GET_RESPONSE, struct.pack(">H", f.address))
    if msg.cc == rdm.SET:
        if msg.pid == rdm.DMX_START_ADDRESS and len(msg.data) == 2:
            f.address = struct.unpack(">H", msg.data)[0]
            print(f"  RDM: {f.defn['model']} {rdm.uid_str(f.uid)} start address → {f.address}")
            return respond(rdm.SET_RESPONSE)
        if msg.pid == rdm.DMX_PERSONALITY and len(msg.data) == 1:
            f.mode = f.modes[msg.data[0] - 1]
            print(f"  RDM: {f.defn['model']} {rdm.uid_str(f.uid)} personality → {f.mode}")
            return respond(rdm.SET_RESPONSE)
    return None
