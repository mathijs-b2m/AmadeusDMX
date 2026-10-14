"""A node that drops off the network (unplugged, powered off) never stops a show: the send is skipped, said once,
and the lights follow again when it is back."""

import errno

from amadeus.dmx.artnet import ArtNetSender
from amadeus.dmx.outputs import SacnOutput


class FlakySocket:
    """Fails like a node that is gone (EHOSTUNREACH, then EHOSTDOWN) until `back`."""

    def __init__(self):
        self.back, self.sent, self.calls = False, 0, 0

    def sendto(self, packet, addr):
        self.calls += 1
        if not self.back:
            code = errno.EHOSTUNREACH if self.calls == 1 else errno.EHOSTDOWN
            raise OSError(code, "No route to host" if self.calls == 1 else "Host is down")
        self.sent += 1

    def setsockopt(self, *a):
        pass


def test_artnet_goes_on_without_its_node_and_picks_it_up_again(capsys):
    s = ArtNetSender("192.168.2.18", owner=True)
    s.sock = FlakySocket()
    for _ in range(5):
        s.send({1: bytes(512)})
    s.blackout([1])  # the show's last word on the way out doesn't crash either
    assert s.unreachable and s.sock.sent == 0
    out = capsys.readouterr().out
    assert out.count("can't be reached") == 1  # said once, not every frame
    s.sock.back = True
    s.send({1: bytes(512)})
    assert not s.unreachable and s.sock.sent == 1
    assert "reachable again" in capsys.readouterr().out


def test_sacn_goes_on_without_its_node():
    s = SacnOutput("192.168.2.18", owner=True)
    s.sock = FlakySocket()
    s.send({1: bytes(512)})
    s.blackout([1])
    assert s.unreachable and s.sent == set()
    s.sock.back = True
    s.send({1: bytes(512)})
    assert s.sent == {1} and not s.unreachable
