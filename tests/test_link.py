from decisive.show import link


def test_pairing_proof_depends_on_the_code():
    assert link.proof("1234", "s", "c") == link.proof("1234", "s", "c")
    assert link.proof("1234", "s", "c") != link.proof("1235", "s", "c")


def test_session_key_and_signature():
    key = link.session_key("1234", "s", "c")
    assert len(key) == 32
    sig = link.sign(key, b'{"s":1}')
    assert len(sig) == 32 and sig == link.sign(key, b'{"s":1}')
    assert sig != link.sign(link.session_key("9999", "s", "c"), b'{"s":1}')
