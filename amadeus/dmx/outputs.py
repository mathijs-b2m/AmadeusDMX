"""DMX outputs: where the engine's universes go.

    Art-Net      network nodes (Showtec NET-2/3 and NET-2/5 Pocket, most nodes)          UDP 6454
    sACN         E1.31 / streaming ACN: network nodes and Ethernet fixtures              UDP 5568, multicast
    ENTTEC Pro   USB widgets speaking the DMX USB Pro protocol (ENTTEC Pro / Pro Mk2,
                 DMXking ultraDMX, Eurolite USB-DMX512-PRO, …)                           serial over USB

A set chooses its output with an optional "output" block (without one it uses its "artnet" settings, as
before):

    "output": {"type": "artnet"}                                          the "artnet" block's node
    "output": {"type": "artnet", "ip": "2.0.0.10", "universe_offset": -1} universe 1 → Art-Net universe 0
    "output": {"type": "sacn"}                                            multicast, universe = rig universe
    "output": {"type": "sacn", "ip": "2.0.0.10", "priority": 100}         unicast to one node
    "output": {"type": "enttec_pro", "port": "auto", "universe": 1}       first USB widget found
    "output": [{"type": "sacn", "universes": [1, 2]},                     several outputs, each with
               {"type": "enttec_pro", "universes": [3]}]                  its own universes

Every output shares the Art-Net sender's manners: it pauses while the setup page holds the lights
(Identify, setup photo), and `blackout` sends zeros.
"""

from __future__ import annotations

import socket
import struct
import time
import uuid

from amadeus.dmx.artnet import ArtNetSender, held

TYPES = ("artnet", "sacn", "enttec_pro")


class Output:
    """One DMX output. `send({universe: 512 bytes})` every frame; `blackout(universes)`; `close()`."""

    def __init__(self, owner: bool = False, universes: list[int] | None = None):
        self.owner = owner  # True: the setup page itself (ignores the hold)
        self.universes = set(universes) if universes else None  # None: every universe
        self._held, self._checked = False, 0.0

    def _paused(self) -> bool:
        if self.owner:
            return False
        now = time.monotonic()
        if now - self._checked > 0.2:
            self._held, self._checked = held(), now
        return self._held

    def _mine(self, universes: dict[int, bytes]) -> dict[int, bytes]:
        return universes if self.universes is None else {u: d for u, d in universes.items() if u in self.universes}

    def send(self, universes: dict[int, bytes]):
        if not self._paused():
            self._send(self._mine(universes))

    def blackout(self, universes):
        self._send(self._mine({u: bytes(512) for u in universes}))

    def close(self):
        pass

    def _send(self, universes: dict[int, bytes]):
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError


class ArtNetOutput(Output):
    """`universe_offset`: the set's universe 1 goes out as Art-Net universe 1 + offset (-1: as universe 0, the
    first output of most nodes)."""

    def __init__(self, ip: str, port: int = 6454, universe_offset: int = 0, universe_map: dict | None = None, **kw):
        super().__init__(**kw)
        self.sender = ArtNetSender(ip, port, owner=True)  # the hold is checked here, in Output
        self.ip, self.port, self.offset = ip, port, universe_offset
        self.map = {int(k): int(v) for k, v in (universe_map or {}).items()}  # set universe → Art-Net universe

    def _send(self, universes):
        out = {self.map.get(u, u + self.offset): d for u, d in universes.items()}
        out = {u: d for u, d in out.items() if u >= 0}
        if out:
            self.sender.send(out)

    def describe(self):
        return f"Art-Net → {self.ip}:{self.port}"


class SacnOutput(Output):
    """E1.31 (ANSI E1.31-2018) data packets: multicast to 239.255.<hi>.<lo> per universe, or unicast."""

    PORT = 5568

    def __init__(
        self,
        ip: str | None = None,
        priority: int = 100,
        name: str = "Amadeus DMX",
        universe_offset: int = 0,
        universe_map: dict | None = None,
        **kw,
    ):
        super().__init__(**kw)
        self.ip, self.priority, self.offset = ip, max(0, min(200, priority)), universe_offset
        self.map = {int(k): int(v) for k, v in (universe_map or {}).items()}  # set universe → sACN universe
        self.cid = uuid.uuid5(uuid.NAMESPACE_DNS, f"amadeus-dmx.{socket.gethostname()}").bytes
        self.name = name.encode()[:63].ljust(64, b"\x00")
        self.seq: dict[int, int] = {}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 8)
        self.sent: set[int] = set()

    def packet(self, universe: int, data: bytes, terminated: bool = False) -> bytes:
        data = bytes(data[:512]).ljust(512, b"\x00")
        seq = self.seq.get(universe, 0)
        self.seq[universe] = (seq + 1) % 256
        dmp = struct.pack(">HBBHHH", 0x7000 | (10 + 513), 0x02, 0xA1, 0, 1, 513) + b"\x00" + data
        framing = (
            struct.pack(">HI", 0x7000 | (77 + len(dmp)), 0x00000002)
            + self.name
            + struct.pack(">BHBBH", self.priority, 0, seq, 0x40 if terminated else 0, universe)
        )
        root = (
            struct.pack(">HH", 0x0010, 0)
            + b"ASC-E1.17\x00\x00\x00"
            + struct.pack(">HI", 0x7000 | (22 + len(framing) + len(dmp)), 0x00000004)
            + self.cid
        )
        return root + framing + dmp

    def _addr(self, universe: int):
        if self.ip:
            return (self.ip, self.PORT)
        return (f"239.255.{(universe >> 8) & 0xFF}.{universe & 0xFF}", self.PORT)

    def _send(self, universes, terminated=False):
        for uni, data in universes.items():
            u = self.map.get(uni, uni + self.offset)
            if 1 <= u <= 63999:
                self.sock.sendto(self.packet(u, data, terminated), self._addr(u))
                self.sent.add(uni)

    def close(self):
        # tell receivers the stream ends (they release the universe at once instead of after 2.5 s)
        self._send({u: bytes(512) for u in self.sent}, terminated=True)

    def describe(self):
        return f"sACN → {self.ip or 'multicast'} (priority {self.priority})"


class EnttecProOutput(Output):
    """DMX USB Pro protocol: 0x7E, label 6 (Output Only Send DMX), length, start code + 512 slots, 0xE7.
    One universe per widget (`universe`, default 1)."""

    def __init__(self, port: str = "auto", universe: int = 1, **kw):
        kw.setdefault("universes", [universe])
        super().__init__(**kw)
        import serial  # pyserial: only needed for USB interfaces

        self.universe = universe
        self.port = find_enttec() if port in (None, "", "auto") else port
        if not self.port:
            raise SystemExit(
                "No ENTTEC DMX USB Pro-compatible interface found. Plug it in, or give its port "
                "(ls /dev/cu.usbserial-*)."
            )
        self.serial = serial.Serial(self.port, 57600, timeout=0, write_timeout=0.05)
        self._last = 0.0

    @staticmethod
    def message(label: int, payload: bytes) -> bytes:
        return bytes([0x7E, label]) + struct.pack("<H", len(payload)) + payload + b"\xe7"

    def _send(self, universes):
        data = universes.get(self.universe)
        if data is None:
            return
        # the widget outputs ~40 frames/s at full 512 slots; more only fills its buffer
        now = time.monotonic()
        if now - self._last < 0.022:
            return
        self._last = now
        try:
            self.serial.write(self.message(6, b"\x00" + bytes(data[:512]).ljust(512, b"\x00")))
        except Exception:  # noqa: BLE001 - unplugged or busy: skip this frame, keep the show running
            pass

    def blackout(self, universes):
        self._last = 0.0
        super().blackout(universes)

    def close(self):
        try:
            self.serial.close()
        except Exception:  # noqa: BLE001
            pass

    def describe(self):
        return f"ENTTEC Pro → {self.port} (universe {self.universe})"


class MultiOutput(Output):
    def __init__(self, outputs: list[Output]):
        super().__init__(owner=True)
        self.outputs = outputs

    def send(self, universes):
        for o in self.outputs:
            o.send(universes)

    def blackout(self, universes):
        for o in self.outputs:
            o.blackout(universes)

    def close(self):
        for o in self.outputs:
            o.close()

    def describe(self):
        return " + ".join(o.describe() for o in self.outputs)


def drives_real_lights(sender: Output | None, rig: dict) -> bool:
    """Does this output reach real fixtures? Art-Net to this computer only feeds the visualiser (a set can
    insist with `safety.laser_zones_required`). With real lights the laser guard requires laser zones."""
    if sender is None:
        return False
    local = isinstance(sender, ArtNetOutput) and sender.ip.startswith("127.")
    return not local or bool(rig.get("safety", {}).get("laser_zones_required"))


def open_output(rig: dict, ip: str | None = None, owner: bool = False) -> Output:
    """The output a set asks for. `ip`: a node address given on the command line (`--artnet IP`), which
    replaces the network output's address."""
    specs = _specs(rig)
    outs = [_one(s, rig, ip, owner) for s in specs]
    return outs[0] if len(outs) == 1 else MultiOutput(outs)


def _one(s: dict, rig: dict, ip: str | None, owner: bool) -> Output:
    kind = s.get("type", "artnet")
    common = {"owner": owner, "universes": s.get("universes")}
    if kind == "artnet":
        art = rig.get("artnet", {})
        return ArtNetOutput(
            ip or s.get("ip") or art.get("ip", "127.0.0.1"),
            int(s.get("port") or art.get("port", 6454)),
            universe_offset=int(s.get("universe_offset", 0)),
            universe_map=s.get("universe_map"),
            **common,
        )
    if kind == "sacn":
        return SacnOutput(
            ip or s.get("ip"),
            int(s.get("priority", 100)),
            universe_offset=int(s.get("universe_offset", 0)),
            universe_map=s.get("universe_map"),
            **common,
        )
    if kind == "enttec_pro":
        return EnttecProOutput(s.get("port", "auto"), int(s.get("universe", 1)), **common)
    raise SystemExit(f"Unknown output type '{kind}' (use one of: {', '.join(TYPES)})")


def _specs(rig: dict) -> list[dict]:
    """The outputs a set uses: from its universes mapped onto your DMX devices (amadeus/dmx/devices.py), else
    its own "output" / "artnet" blocks (as sets always did)."""
    if "dmx" in rig:
        from amadeus.dmx import devices

        return devices.resolve(rig) or [{"type": "artnet", "ip": "127.0.0.1"}]  # nothing mapped: the visualiser
    spec = rig.get("output") or {"type": "artnet"}
    return spec if isinstance(spec, list) else [spec]


def describe(rig: dict) -> str:
    """How a set's DMX goes out, in words (without opening anything)."""
    if "dmx" in rig:
        from amadeus.dmx import devices

        return devices.describe(rig)
    spec = rig.get("output") or {"type": "artnet"}
    parts = []
    for s in spec if isinstance(spec, list) else [spec]:
        kind = s.get("type", "artnet")
        if kind == "artnet":
            parts.append(f"Art-Net → {s.get('ip') or rig.get('artnet', {}).get('ip', '127.0.0.1')}")
        elif kind == "sacn":
            parts.append(f"sACN → {s.get('ip') or 'multicast'}")
        else:
            parts.append(f"ENTTEC Pro → {s.get('port', 'auto')}")
    return " + ".join(parts)


# ---------------------------------------------------------------- USB interfaces


def usb_ports() -> list[dict]:
    """Serial ports that look like DMX interfaces, each probed for the DMX USB Pro protocol."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        if not p.device.startswith("/dev/cu.") or "Bluetooth" in p.device or "debug-console" in p.device:
            continue
        info = {
            "port": p.device,
            "description": p.description or "",
            "manufacturer": p.manufacturer or "",
            "serial": p.serial_number or "",
            "vid": p.vid,
            "pid": p.pid,
            "pro": False,
        }
        if p.vid == 0x0403 or "usbserial" in p.device or "usbmodem" in p.device:
            info.update(probe(p.device))
        out.append(info)
    return out


def probe(port: str, timeout: float = 0.4) -> dict:
    """Ask a widget for its parameters (label 3) and serial number (label 10): answers = DMX USB Pro protocol."""
    try:
        import serial

        with serial.Serial(port, 57600, timeout=timeout) as s:
            s.reset_input_buffer()
            s.write(EnttecProOutput.message(3, b"\x00\x00") + EnttecProOutput.message(10, b""))
            deadline, buf = time.monotonic() + timeout, b""
            while time.monotonic() < deadline and buf.count(b"\xe7") < 2:
                buf += s.read(64)
        found: dict = {}
        i = 0
        while (i := buf.find(b"\x7e", i)) >= 0 and i + 4 <= len(buf):
            label, n = buf[i + 1], struct.unpack("<H", buf[i + 2 : i + 4])[0]
            body = buf[i + 4 : i + 4 + n]
            if label == 3 and len(body) >= 2:
                found["pro"], found["firmware"] = True, f"{body[1]}.{body[0]}"
            elif label == 10 and len(body) == 4:
                found["pro"], found["widget_serial"] = True, "".join(f"{b:02X}" for b in reversed(body))
            i += 4 + n + 1
        return found
    except Exception:  # noqa: BLE001 - busy, not a widget, no permission
        return {}


def find_enttec() -> str | None:
    ports = usb_ports()
    pro = [p for p in ports if p.get("pro")]
    if pro:
        return pro[0]["port"]
    ftdi = [p for p in ports if p.get("vid") == 0x0403]  # unprobed FTDI: most likely the widget
    return ftdi[0]["port"] if ftdi else None


def validate(rig: dict) -> list[str]:
    """Problems with a set's "output" block, or its "dmx" mapping onto your devices (empty: fine)."""
    if "dmx" in rig:
        from amadeus.dmx import devices

        return devices.check_mapping(rig)
    spec = rig.get("output")
    if spec is None:
        return []
    problems = []
    for s in spec if isinstance(spec, list) else [spec]:
        if not isinstance(s, dict) or s.get("type") not in TYPES:
            problems.append(f"output: type must be one of {', '.join(TYPES)}")
        elif s["type"] == "sacn" and not 0 <= int(s.get("priority", 100)) <= 200:
            problems.append("output: sACN priority must be 0–200")
        elif s["type"] == "enttec_pro" and not 1 <= int(s.get("universe", 1)) <= 32767:
            problems.append("output: the USB interface's universe must be 1 or more")
    return problems
