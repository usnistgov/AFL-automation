import logging
import threading

from AFL.automation.loading.PiPlatesRelay import PiPlatesRelay


class _FakeRelayPlate:
    def __init__(self, readbacks):
        self.readbacks = iter(readbacks)
        self.writes = []

    def relayALL(self, board_id, value):
        self.writes.append((board_id, value))

    def relaySTATE(self, board_id):
        return next(self.readbacks)


def _relay(readbacks):
    relay = PiPlatesRelay.__new__(PiPlatesRelay)
    relay.threadlock = threading.Lock()
    relay.RELAYplate = _FakeRelayPlate(readbacks)
    relay.state = [False] * 7
    relay.board_id = 2
    relay.labels = {1: 'arm-up'}
    relay.ids = {'arm-up': 1}
    return relay


def test_set_channels_uses_debug_logging_instead_of_print(caplog, capsys):
    relay = _relay([1])
    caplog.set_level(logging.DEBUG, logger='AFL.automation.loading.PiPlatesRelay')

    relay.setChannels({'arm-up': True})

    assert relay.RELAYplate.writes == [(2, 1)]
    assert 'resolved channels={1: True}' in caplog.text
    assert capsys.readouterr().out == ''


def test_readback_retry_uses_warning_and_info_logging(monkeypatch, caplog, capsys):
    relay = _relay([0, 1])
    monkeypatch.setattr('AFL.automation.loading.PiPlatesRelay.time.sleep', lambda _: None)
    caplog.set_level(logging.INFO, logger='AFL.automation.loading.PiPlatesRelay')
    relay.state[0] = True

    relay._refresh_board_state()

    assert 'readback mismatch: requested=1, readback=0' in caplog.text
    assert 'readback verified after 0 retries' in caplog.text
    assert capsys.readouterr().out == ''
