from amadeus.show import link


def test_pairing_proof_depends_on_the_code():
    assert link.proof("1234", "s", "c") == link.proof("1234", "s", "c")
    assert link.proof("1234", "s", "c") != link.proof("1235", "s", "c")


def test_session_key_and_signature():
    key = link.session_key("1234", "s", "c")
    assert len(key) == 32
    sig = link.sign(key, b'{"s":1}')
    assert len(sig) == 32 and sig == link.sign(key, b'{"s":1}')
    assert sig != link.sign(link.session_key("9999", "s", "c"), b'{"s":1}')


class FakeAbleton:
    peers, tempo = 1, 125.0

    def phase(self):
        return 0.5


def test_synced_deck_takes_its_phase_from_ableton_link_here():
    rl = link.RemoteListener.__new__(link.RemoteListener)  # no network: only the phase logic
    rl.ableton = FakeAbleton()
    deck = {"sync": 1, "play": 1, "bpm": 125.0}
    # the packet is 48 ms old (0.1 beat at 125 BPM): its phase was 0.1 beat before Link's phase now
    assert abs(rl._link_phase(deck, now=10.048, at=10.0) - 0.4) < 1e-9
    assert rl._link_phase({**deck, "sync": 0}, 10.0, 10.0) is None  # not synced
    assert rl._link_phase({**deck, "bpm": 128.0}, 10.0, 10.0) is None  # another tempo: not this session
    rl.ableton = False  # no aalink here
    assert rl._link_phase(deck, 10.0, 10.0) is None


def test_streamed_deck_stays_dark_unless_switched_on(monkeypatch):
    from amadeus.show.sources import streamed

    rl = link.RemoteListener.__new__(link.RemoteListener)
    rl.fetcher, rl.dark = None, set()
    s = streamed.Stream("spotify", "abc", "T", "A", "", 200.0)
    monkeypatch.setattr(streamed, "enabled", lambda: False)
    assert rl._stream_copy(s) is None and rl.fetcher is False and "abc" in rl.dark

    class FakeFetcher:
        def file(self, s):
            return "/cache/streamed/A - T [spotify-abc].opus"

    rl.fetcher = FakeFetcher()
    assert rl._stream_copy(s).endswith("[spotify-abc].opus")


def test_zeroconf_lookup_works_from_inside_the_event_loop(monkeypatch):
    # live mode looks for a DJ laptop by name from inside its event loop; zeroconf's blocking calls refuse to run
    # there (Windows, where there's no dns-sd)
    import asyncio
    import sys
    import types

    class Info:
        port = 7123

        def parsed_addresses(self, version=None):
            return ["10.0.0.7"]

    class Zeroconf:
        def get_service_info(self, kind, full, timeout):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return Info()
            raise RuntimeError("Use AsyncServiceInfo.async_request from the event loop")

        def close(self):
            pass

    fake = types.SimpleNamespace(Zeroconf=Zeroconf, ServiceBrowser=None, IPVersion=types.SimpleNamespace(V4Only=1))
    monkeypatch.setitem(sys.modules, "zeroconf", fake)
    monkeypatch.setattr(link.shutil, "which", lambda name: None)

    async def look():
        return link.resolve("DJ laptop")

    assert asyncio.run(look()) == ("10.0.0.7", 7123)


def test_an_unreachable_dj_laptop_says_what_to_check(tmp_path):
    import socket

    import pytest

    with socket.socket() as s:  # a port nobody listens on
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(SystemExit, match="Windows Firewall"):
        link.RemoteListener("127.0.0.1", port, "1234", tmp_path)
