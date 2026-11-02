import json

import pandas as pd
import pytest

from llm_trader import bridge
from llm_trader.bridge import AdvisoryError

T = pd.Timestamp("2026-11-02 10:00", tz="UTC")
HOUR = pd.Timedelta(hours=1)
FORBIDDEN = ("lot", "lots", "volume", "side", "direction", "entry", "price", "stop", "target", "order")


def pause(symbol="XAUUSD", expires=T + HOUR) -> dict:
    return bridge.advisory(symbol, "US CPI in 30 minutes", T, expires)


def test_payload_has_exactly_the_documented_shape():
    data = bridge.payload(T, kill=False, advisories=[pause()])
    assert data == {
        "heartbeat": "2026-11-02T10:00:00Z",
        "kill": False,
        "advisories": [{
            "id": "pause-XAUUSD-20261102T1000Z", "symbol": "XAUUSD", "action": "pause", "reason": "US CPI in 30 minutes",
            "issued_at": "2026-11-02T10:00:00Z", "expires_at": "2026-11-02T11:00:00Z",
        }],
    }


@pytest.mark.parametrize("key", FORBIDDEN)
def test_never_a_lot_direction_or_entry_field(key):
    with pytest.raises(AdvisoryError, match="exactly id, symbol, action, reason, issued_at, expires_at"):
        bridge.payload(T, False, [{**pause(), key: 1}])


@pytest.mark.parametrize("expires, ok", [(T + 4 * HOUR, True), (T + 4 * HOUR + pd.Timedelta(minutes=1), False), (T, False), (T - HOUR, False)])
def test_a_pause_expires_within_four_hours(expires, ok):
    if ok:
        assert pause(expires=expires)["expires_at"] == "2026-11-02T14:00:00Z"
    else:
        with pytest.raises(AdvisoryError, match="within 4 hours"):
            pause(expires=expires)


def test_hand_written_advisories_are_checked_too():
    with pytest.raises(AdvisoryError, match="only advisory action is 'pause'"):
        bridge.payload(T, False, [{**pause(), "action": "close"}])
    with pytest.raises(AdvisoryError, match="within 4 hours"):
        bridge.payload(T, False, [{**pause(), "expires_at": "2026-11-02T15:00:00Z"}])
    with pytest.raises(AdvisoryError, match="unique"):
        bridge.payload(T, False, [pause(), pause()])


def test_kill_empties_the_list():
    assert bridge.payload(T, kill=True, advisories=[pause()]) == {"heartbeat": "2026-11-02T10:00:00Z", "kill": True, "advisories": []}


def test_write_replaces_the_file_and_removes_the_old_signals_file(tmp_path):
    folder = tmp_path / "bridge"
    folder.mkdir()
    (folder / "signals.json").write_text(json.dumps({"signals": [{"id": "old", "lots": 0.01}]}))
    path = bridge.write(folder, bridge.payload(T, False, [pause()]))
    assert path == folder / "advisories.json"
    assert json.loads(path.read_text())["advisories"][0]["action"] == "pause"
    assert not (folder / "signals.json").exists()
    assert sorted(p.name for p in folder.iterdir()) == ["advisories.json"]


def test_state_and_notes():
    quiet = bridge.payload(T, False)
    assert bridge.state(quiet, "out/bridge/advisories.json", False, "demo") == {
        "file": "out/bridge/advisories.json", "heartbeat": "2026-11-02T10:00:00Z", "kill_flag": False, "advisories": [],
        "note": bridge.DEMO_NOTE,
    }
    assert bridge.state(quiet, "f", False, "mt5")["note"] == bridge.SHADOW_NOTE
    killed = bridge.state(bridge.payload(T, True), "f", True, "mt5")
    assert killed["kill_flag"] is True and killed["note"] == bridge.KILL_NOTE
    written = bridge.state(bridge.payload(T, False, [pause()]), "f", False, "mt5")
    assert written["note"].startswith("1 pause advisory(ies) written") and "nothing here sizes or opens a trade" in written["note"]
