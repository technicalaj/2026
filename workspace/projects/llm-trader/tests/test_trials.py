import json
import os

import pandas as pd
import pytest
from conftest import TRIALS_AT_START, TRIALS_PATH

from llm_trader.eval.trials import (
    TRIALS_FORMAT, TrialEntry, count_trials, data_id, dataset_fingerprint, default_trials_path, first_test_before_lock,
    load_trials, record_trials, same_months, tally_trials,
)

HOLDOUT = (pd.Timestamp("2026-01-30 21:45", tz="UTC"), pd.Timestamp("2026-07-30 21:45", tz="UTC"))
NOW = "2026-11-01T22:00:00Z"
LOCKED = "2026-11-01T20:00:00Z"
ENTRIES = [TrialEntry("rule_a", "2", "a" * 64, LOCKED), TrialEntry("rule_b", "2", "b" * 64, LOCKED)]


def fake_dataset(*hashes, source="synthetic", server=None):
    return {f"SYM{i}": (None, {"sha256": h, "source": source, "server": server}) for i, h in enumerate(hashes)}


def shifted(days: float):
    return tuple(t + pd.Timedelta(days=days) for t in HOLDOUT)


def test_fingerprint_depends_on_the_data_not_on_dict_order():
    a = fake_dataset("1" * 64, "2" * 64)
    b = dict(reversed(list(a.items())))
    assert dataset_fingerprint(a) == dataset_fingerprint(b)
    assert dataset_fingerprint(a) != dataset_fingerprint(fake_dataset("1" * 64, "3" * 64))
    assert len(dataset_fingerprint(a)) == 64


def test_data_id_names_the_source_but_never_the_broker_server():
    assert data_id(fake_dataset("1" * 64)) == "synthetic"
    real = data_id(fake_dataset("1" * 64, source="mt5_export", server="Broker-Live3"))
    assert real.startswith("mt5:") and "Broker" not in real
    assert real == data_id(fake_dataset("9" * 64, source="mt5_export", server="Broker-Live3"))
    assert real != data_id(fake_dataset("1" * 64, source="mt5_export", server="Other-Demo"))
    assert data_id(fake_dataset("1" * 64, source="other")) == "other"


def test_demo_fingerprint_is_stable(demo):
    assert dataset_fingerprint(demo) == dataset_fingerprint(dict(demo))
    assert data_id(demo) == "synthetic"


def test_each_variant_is_recorded_once_with_its_lock_time(tmp_path):
    path = tmp_path / "trials.json"
    assert record_trials(path, "synthetic", "f1", ENTRIES, HOLDOUT, NOW) == 2
    assert record_trials(path, "synthetic", "f2", ENTRIES, HOLDOUT, "2026-11-02T08:00:00Z") == 2
    log = load_trials(path)
    assert log["format"] == TRIALS_FORMAT and len(log["records"]) == 2
    assert log["records"][0] == {
        "data_id": "synthetic", "test_sha256": "a" * 64, "rule_id": "rule_a", "version": "2",
        "holdout": ["2026-01-30T21:45:00Z", "2026-07-30T21:45:00Z"], "first_evaluated_at": NOW, "locked_at": LOCKED,
        "fingerprint": "f1",
    }


def test_a_fresh_export_of_the_same_months_keeps_counting(tmp_path):
    path = tmp_path / "trials.json"
    record_trials(path, "mt5:abc", "export-1", ENTRIES, HOLDOUT, NOW)
    variant = [TrialEntry("rule_a", "3", "c" * 64, LOCKED)]
    assert record_trials(path, "mt5:abc", "export-2", variant, shifted(0.01), NOW) == 3
    assert record_trials(path, "mt5:abc", "export-3", variant, shifted(20), NOW) == 3
    assert record_trials(path, "mt5:abc", "export-4", ENTRIES[:1], shifted(400), NOW) == 1
    assert record_trials(path, "synthetic", "demo", ENTRIES[:1], HOLDOUT, NOW) == 1
    log = load_trials(path)
    assert count_trials(log, "mt5:abc", HOLDOUT) == 3 and count_trials(log, "mt5:other", HOLDOUT) == 0


def test_months_count_as_the_same_when_they_overlap_by_a_month():
    assert same_months(HOLDOUT, shifted(150))
    assert not same_months(HOLDOUT, shifted(160))
    short = (HOLDOUT[0], HOLDOUT[0] + pd.Timedelta(days=20))
    assert same_months(short, (short[0] + pd.Timedelta(days=9), short[1] + pd.Timedelta(days=9)))


def test_records_from_the_first_log_format_count_everywhere(tmp_path):
    path = tmp_path / "trials.json"
    legacy = {"fingerprint": "f0", "rule_id": "old", "version": "1", "plan_sha256": "d" * 64,
              "holdout": ["2026-01-30T21:45:00Z", "2026-07-30T21:45:00Z"], "first_evaluated_at": NOW}
    path.write_text(json.dumps({"format": "superagentic-trials/1", "records": [legacy]}))
    assert record_trials(path, "mt5:abc", "f1", ENTRIES, HOLDOUT, NOW) == 3


def test_a_test_seen_before_its_lock_is_found(tmp_path):
    path = tmp_path / "trials.json"
    peeked = TrialEntry("rule_c", "1", "e" * 64, None)
    record_trials(path, "synthetic", "f1", [*ENTRIES, peeked], HOLDOUT, NOW)
    log = load_trials(path)
    assert first_test_before_lock(log, "synthetic", HOLDOUT, "a" * 64, "2026-11-03T00:00:00Z") is None
    assert first_test_before_lock(log, "synthetic", HOLDOUT, "e" * 64, "2026-11-03T00:00:00Z") == NOW
    assert first_test_before_lock(log, "synthetic", HOLDOUT, "e" * 64, None) == NOW
    assert first_test_before_lock(log, "synthetic", shifted(400), "e" * 64, "2026-11-03T00:00:00Z") is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_saving_keeps_the_log_readable_by_others(tmp_path):
    path = tmp_path / "trials.json"
    record_trials(path, "synthetic", "f1", ENTRIES[:1], HOLDOUT, NOW)
    assert path.stat().st_mode & 0o777 == 0o644
    path.chmod(0o664)
    record_trials(path, "synthetic", "f1", ENTRIES, HOLDOUT, NOW)
    assert path.stat().st_mode & 0o777 == 0o664


def test_missing_log_starts_empty_and_nothing_is_written_without_new_records(tmp_path):
    path = tmp_path / "trials.json"
    assert load_trials(path) == {"format": TRIALS_FORMAT, "records": []}
    assert record_trials(path, "synthetic", "f1", [], HOLDOUT, NOW) == 0
    assert not path.exists()


@pytest.mark.parametrize("content", ["{not json", "[]", '{"records": [{"rule_id": "x"}]}'])
def test_unreadable_log_is_reported(tmp_path, content):
    path = tmp_path / "trials.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        load_trials(path)
    with pytest.raises(ValueError):
        record_trials(path, "synthetic", "f1", ENTRIES, HOLDOUT, NOW)
    assert path.read_text() == content


def test_tally_still_counts_when_the_log_cannot_be_saved(tmp_path):
    blocker = tmp_path / "config"
    blocker.write_text("a file where the folder should be")
    count, note = tally_trials(blocker / "trials.json", "synthetic", "f1", ENTRIES, HOLDOUT)
    assert count == 2 and note.startswith("the trial log could not be saved")


def test_tally_reports_an_unreadable_log_without_touching_it(tmp_path):
    path = tmp_path / "trials.json"
    path.write_text("{bad")
    count, note = tally_trials(path, "synthetic", "f1", ENTRIES, HOLDOUT)
    assert count is None and "unreadable" in note and "number of tries is unknown" in note
    assert path.read_text() == "{bad"


def test_tally_without_recording_writes_nothing(tmp_path):
    assert tally_trials(tmp_path / "trials.json", "synthetic", "f1", ENTRIES, HOLDOUT, record=False) == (2, None)
    assert not (tmp_path / "trials.json").exists()


def test_log_lives_next_to_the_plans_folder(tmp_path):
    assert default_trials_path(tmp_path / "config" / "plans") == tmp_path / "config" / "trials.json"


def test_the_local_log_is_untouched_by_the_test_run(evaluations):
    if TRIALS_AT_START is None:
        assert not TRIALS_PATH.exists()
    else:
        assert TRIALS_PATH.read_bytes() == TRIALS_AT_START
