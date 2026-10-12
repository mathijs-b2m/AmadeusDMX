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
