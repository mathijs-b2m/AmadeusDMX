"""Art-Net discovery packets (ArtPoll/ArtPollReply, ArtTodRequest/ArtTodData, ArtRdm) and RDM (ANSI E1.20).

Only the parts needed for discovering a node, listing its RDM devices,
reading what they are and setting their DMX start address.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

ID = b"Art-Net\x00"
PROT = struct.pack(">H", 14)
OP_POLL, OP_POLL_REPLY = 0x2000, 0x2100
OP_TOD_REQUEST, OP_TOD_DATA = 0x8000, 0x8100
OP_RDM = 0x8300

# RDM command classes and parameter IDs
GET, GET_RESPONSE, SET, SET_RESPONSE = 0x20, 0x21, 0x30, 0x31
DEVICE_INFO = 0x0060
DEVICE_MODEL_DESCRIPTION = 0x0080
MANUFACTURER_LABEL = 0x0081
DMX_PERSONALITY = 0x00E0
DMX_START_ADDRESS = 0x00F0
RESPONSE_ACK = 0x00
CONTROLLER_UID = bytes.fromhex("7ff000000001")  # 0x7FF0–0x7FFF is the ESTA prototyping range


def opcode(pkt: bytes) -> int | None:
    if len(pkt) < 10 or not pkt.startswith(ID):
        return None
    return struct.unpack_from("<H", pkt, 8)[0]


def _hdr(op: int) -> bytes:
    return ID + struct.pack("<H", op) + PROT


# ---------------------------------------------------------------- ArtPoll / ArtPollReply


def art_poll() -> bytes:
    return _hdr(OP_POLL) + bytes([0x02, 0x00])  # flags: send ArtPollReply on change; diag priority


@dataclass
class Node:
    ip: str
    port: int
    short_name: str
    long_name: str
    net: int
    sub: int
    outputs: list[int]  # full 15-bit port addresses of the DMX outputs

    def __str__(self):
        return f"{self.short_name} ({self.long_name}) at {self.ip}, outputs → universes {self.outputs}"


def art_poll_reply(
    ip: str, short: str, long: str, net: int, sub: int, sw_out: list[int], mac: bytes = bytes(6)
) -> bytes:
    pkt = bytearray(239)
    pkt[0:8] = ID
    struct.pack_into("<H", pkt, 8, OP_POLL_REPLY)
    pkt[10:14] = bytes(int(x) for x in ip.split("."))
    struct.pack_into("<H", pkt, 14, 0x1936)
    pkt[18], pkt[19] = net & 0x7F, sub & 0x0F
    # fixed-width, NUL-padded fields (a shorter slice assignment would shrink the bytearray)
    pkt[26:44] = short.encode()[:17].ljust(18, b"\x00")
    pkt[44:108] = long.encode()[:63].ljust(64, b"\x00")
    pkt[108:172] = b"#0001 [0000] OK".ljust(64, b"\x00")
    struct.pack_into(">H", pkt, 172, len(sw_out))
    for i, u in enumerate(sw_out[:4]):
        pkt[174 + i] = 0x80  # port type: can output DMX512
        pkt[182 + i] = 0x80  # good output: data being transmitted
        pkt[190 + i] = u & 0x0F  # SwOut: low nibble of the port address
    pkt[201:207] = mac
    pkt[212] = 0x08  # Status2: supports 15-bit port addresses
    assert len(pkt) == 239
    return bytes(pkt)


def parse_poll_reply(pkt: bytes) -> Node:
    ip = ".".join(str(b) for b in pkt[10:14])
    net, sub = pkt[18], pkt[19]
    n = struct.unpack_from(">H", pkt, 172)[0]
    outputs = [(net << 8) | (sub << 4) | (pkt[190 + i] & 0x0F) for i in range(min(n, 4)) if pkt[174 + i] & 0x80]
    name = lambda a, b: pkt[a:b].split(b"\x00")[0].decode(errors="replace")  # noqa: E731
    return Node(ip, struct.unpack_from("<H", pkt, 14)[0], name(26, 44), name(44, 108), net, sub, outputs)


# ---------------------------------------------------------------- RDM device lists (TOD)


def art_tod_request(port_address: int) -> bytes:
    return _hdr(OP_TOD_REQUEST) + bytes(9) + bytes([(port_address >> 8) & 0x7F, 0x00, 1, port_address & 0xFF])


def parse_tod_request(pkt: bytes) -> list[int]:
    net, count = pkt[21], pkt[23]
    return [(net << 8) | pkt[24 + i] for i in range(count)]


def art_tod_data(port_address: int, uids: list[bytes]) -> bytes:
    return (
        _hdr(OP_TOD_DATA)
        + bytes([1, 1])
        + bytes(6)
        + bytes([0, (port_address >> 8) & 0x7F, 0x00, port_address & 0xFF])
        + struct.pack(">H", len(uids))
        + bytes([0, len(uids)])
        + b"".join(uids)
    )


def parse_tod_data(pkt: bytes) -> tuple[int, list[bytes]]:
    port_address = (pkt[21] << 8) | pkt[23]
    count = pkt[27]
    return port_address, [pkt[28 + 6 * i : 34 + 6 * i] for i in range(count)]


# ---------------------------------------------------------------- RDM messages inside ArtRdm


def _checksum(data: bytes) -> bytes:
    return struct.pack(">H", (0xCC + sum(data)) & 0xFFFF)  # the 0xCC start code is not sent in ArtRdm


@dataclass
class RdmMessage:
    dest: bytes
    src: bytes
    tn: int
    port_or_response: int
    cc: int
    pid: int
    data: bytes = b""
    sub_device: int = 0
    message_count: int = 0


def rdm_encode(m: RdmMessage) -> bytes:
    body = (
        bytes([0x01, 24 + len(m.data)])
        + m.dest
        + m.src
        + bytes([m.tn & 0xFF, m.port_or_response, m.message_count])
        + struct.pack(">HBHB", m.sub_device, m.cc, m.pid, len(m.data))
        + m.data
    )
    return body + _checksum(body)


def rdm_decode(raw: bytes) -> RdmMessage:
    length = raw[1]
    body, chk = raw[: length - 1], raw[length - 1 : length + 1]
    if _checksum(body) != chk:
        raise ValueError("RDM checksum mismatch")
    sub_device, cc, pid, pdl = struct.unpack_from(">HBHB", raw, 17)
    return RdmMessage(
        dest=raw[2:8],
        src=raw[8:14],
        tn=raw[14],
        port_or_response=raw[15],
        message_count=raw[16],
        sub_device=sub_device,
        cc=cc,
        pid=pid,
        data=raw[23 : 23 + pdl],
    )


def art_rdm(port_address: int, rdm: bytes) -> bytes:
    return (
        _hdr(OP_RDM) + bytes([1, 0]) + bytes(7) + bytes([(port_address >> 8) & 0x7F, 0x00, port_address & 0xFF]) + rdm
    )


def parse_art_rdm(pkt: bytes) -> tuple[int, RdmMessage]:
    return (pkt[21] << 8) | pkt[23], rdm_decode(pkt[24:])


# ---------------------------------------------------------------- parameter payloads


@dataclass
class DeviceInfo:
    model_id: int
    category: int
    software: int
    footprint: int
    personality: int
    personality_count: int
    start_address: int

    def pack(self) -> bytes:
        return struct.pack(
            ">HHHIHBBHHB",
            0x0100,
            self.model_id,
            self.category,
            self.software,
            self.footprint,
            self.personality,
            self.personality_count,
            self.start_address,
            0,
            0,
        )

    @classmethod
    def unpack(cls, d: bytes) -> DeviceInfo:
        _, model, cat, sw, fp, pers, pcount, addr, _, _ = struct.unpack(">HHHIHBBHHB", d[:19])
        return cls(model, cat, sw, fp, pers, pcount, addr)


def uid_str(uid: bytes) -> str:
    return f"{uid[:2].hex().upper()}:{uid[2:].hex().upper()}"
