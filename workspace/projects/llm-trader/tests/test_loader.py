import hashlib
import importlib.util
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from conftest import ROOT

from llm_trader.data.loader import load_dataset, load_mt5_csv
from llm_trader.data.symbols import DEMO_SPECS, MissingCostsError, resolve_spec

EXPORTER_HEADER = "time,open,high,low,close,tick_volume,spread,real_volume\n"


def load_exporter_tool():
    spec = importlib.util.spec_from_file_location("export_mt5_data", ROOT / "tools" / "export_mt5_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exporter_format_with_epoch_seconds(tmp_path):
    path = tmp_path / "XAUUSD_M15.csv"
    path.write_text(EXPORTER_HEADER + "1767600000,2650.10,2651.00,2649.50,2650.80,123,20,0\n1767600900,2650.80,2652.00,2650.20,2651.40,98,21,0\n")
    df, prov = load_mt5_csv(path)
    assert list(df.columns) == ["open", "high", "low", "close", "spread", "volume"]
    assert df.index.name == "time" and str(df.index.tz) == "UTC" and df.index.unit == "ns"
    assert df.index[0] == pd.Timestamp("2026-01-05 08:00", tz="UTC")
    assert df.iloc[0].to_dict() == {"open": 2650.10, "high": 2651.0, "low": 2649.5, "close": 2650.8, "spread": 20.0, "volume": 123.0}
    assert prov["source"] == "other"
    assert (prov["symbol"], prov["timeframe"], prov["format"], prov["rows"]) == ("XAUUSD", "M15", "exporter", 2)
    assert prov["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (prov["first"], prov["last"]) == ("2026-01-05T08:00:00Z", "2026-01-05T08:15:00Z")


def test_exporter_format_with_iso_times(tmp_path):
    path = tmp_path / "EURUSD_M15.csv"
    path.write_text(EXPORTER_HEADER + "2026-01-05T08:00:00Z,1.1,1.2,1.0,1.15,5,6,0\n2026-01-05 08:15:00,1.15,1.2,1.1,1.12,5,7,0\n")
    df, _ = load_mt5_csv(path)
    assert list(df.index) == [pd.Timestamp("2026-01-05 08:00", tz="UTC"), pd.Timestamp("2026-01-05 08:15", tz="UTC")]


TERMINAL_ROWS = [
    ["2026.01.05", "10:15:00", "2651.00", "2652.0", "2650.0", "2651.5", "90", "0", "22"],
    ["2026.01.05", "10:00:00", "2650.00", "2651.5", "2649.0", "2651.0", "80", "0", "20"],
    ["2026.01.05", "10:15:00", "2651.00", "2652.5", "2650.0", "2652.0", "95", "0", "23"],
]
TERMINAL_HEADER = ["<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>", "<TICKVOL>", "<VOL>", "<SPREAD>"]


@pytest.mark.parametrize("sep", ["\t", ","])
def test_mt5_terminal_export_sorts_dedupes_and_reports(tmp_path, sep):
    path = tmp_path / "XAUUSD_M15_202601050000_202601060000.csv"
    path.write_text("\n".join(sep.join(r) for r in [TERMINAL_HEADER, *TERMINAL_ROWS]) + "\n")
    df, prov = load_mt5_csv(path)
    assert list(df.index) == [pd.Timestamp("2026-01-05 10:00", tz="UTC"), pd.Timestamp("2026-01-05 10:15", tz="UTC")]
    assert df.loc["2026-01-05 10:15", "close"].item() == 2652.0
    assert df["spread"].tolist() == [20.0, 23.0] and df["volume"].tolist() == [80.0, 95.0]
    assert (prov["source"], prov["format"], prov["duplicates"]) == ("mt5_export", "mt5_terminal", 1)
    assert (prov["symbol"], prov["timeframe"]) == ("XAUUSD", "M15")
    assert prov["time_basis"].startswith("assumed UTC")


def test_mt5_terminal_daily_export_without_time_column_in_utf16(tmp_path):
    header = ["<DATE>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>", "<TICKVOL>", "<VOL>", "<SPREAD>"]
    rows = [["2026.01.05", "1.10", "1.12", "1.09", "1.11", "500", "0", "8"], ["2026.01.06", "1.11", "1.13", "1.10", "1.12", "450", "0", "7"]]
    path = tmp_path / "EURUSD_D1.csv"
    path.write_bytes("\n".join("\t".join(r) for r in [header, *rows]).encode("utf-16"))
    df, prov = load_mt5_csv(path)
    assert df.index[1] == pd.Timestamp("2026-01-06", tz="UTC")
    assert prov["timeframe"] == "D1"


@pytest.mark.parametrize(
    ("server_tz", "server_time", "utc_time"),
    [
        ("nyclose", "2026.01.05 10:00:00", "2026-01-05 08:00"),
        ("nyclose", "2026.07.06 10:00:00", "2026-07-06 07:00"),
        (2, "2026.07.06 10:00:00", "2026-07-06 08:00"),
        (None, "2026.07.06 10:00:00", "2026-07-06 10:00"),
    ],
)
def test_server_time_is_converted_to_utc(tmp_path, server_tz, server_time, utc_time):
    date, clock = server_time.split()
    path = tmp_path / "XAUUSD_M15.csv"
    path.write_text("\t".join(TERMINAL_HEADER) + "\n" + "\t".join([date, clock, "1", "2", "0.5", "1.5", "1", "0", "1"]) + "\n")
    df, _ = load_mt5_csv(path, server_tz=server_tz)
    assert df.index[0] == pd.Timestamp(utc_time, tz="UTC")


def test_rows_with_broken_prices_are_dropped_and_counted(tmp_path):
    path = tmp_path / "XAUUSD_M15.csv"
    path.write_text(EXPORTER_HEADER + "1767600000,1,2,0.5,1.5,1,1,0\n1767600900,,2,0.5,1.5,1,1,0\n")
    df, prov = load_mt5_csv(path)
    assert len(df) == 1 and prov["dropped_rows"] == 1


def test_file_without_symbol_in_name_is_rejected(tmp_path):
    path = tmp_path / "prices.csv"
    path.write_text(EXPORTER_HEADER + "1767600000,1,2,0.5,1.5,1,1,0\n")
    with pytest.raises(ValueError, match="cannot tell which symbol"):
        load_mt5_csv(path)


def test_non_mt5_file_is_rejected(tmp_path):
    path = tmp_path / "XAUUSD_M15.csv"
    path.write_text("date,price\n2026-01-05,1\n")
    with pytest.raises(ValueError, match="not an MT5 bar export"):
        load_mt5_csv(path)


def test_directory_with_meta_json_is_broker_data(tmp_path):
    (tmp_path / "XAUUSD_M15.csv").write_text(EXPORTER_HEADER + "1767600000,1,2,0.5,1.5,1,1,0\n")
    (tmp_path / "EURUSD_M15.csv").write_text(EXPORTER_HEADER + "1767600000,1,2,0.5,1.5,1,1,0\n")
    meta = {
        "source": "mt5_export", "server": "Example-Server", "timeframe": "M15", "server_tz": "nyclose",
        "symbols": {"XAUUSD": {"file": "XAUUSD_M15.csv", "point": 0.01, "digits": 2, "contract_size": 100, "tick_size": 0.01,
                               "tick_value": 1.0, "min_lot": 0.01, "lot_step": 0.01, "margin_per_min_lot": 25.0}},
    }
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    data = load_dataset(tmp_path)
    assert set(data) == {"XAUUSD", "EURUSD"}
    gold = data["XAUUSD"][1]
    assert (gold["source"], gold["server"]) == ("mt5_export", "Example-Server")
    assert gold["symbol_info"]["margin_per_min_lot"] == 25.0
    assert data["EURUSD"][1]["source"] == "other"
    assert data["XAUUSD"][0].index[0] == pd.Timestamp("2026-01-05 08:00", tz="UTC")


def test_empty_or_missing_directory_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_dataset(tmp_path)
    with pytest.raises(FileNotFoundError):
        load_dataset(tmp_path / "nope")


def test_demo_keyword_returns_synthetic_set(demo):
    assert len(demo) == 7 and all(p["source"] == "synthetic" for _, p in demo.values())


def test_symbol_spec_uses_broker_contract_and_settings_costs(settings):
    info = {"point": 0.001, "digits": 3, "contract_size": 100, "tick_size": 0.001, "tick_value": 0.1, "min_lot": 0.01,
            "lot_step": 0.01, "margin_per_min_lot": 30.0}
    spec = resolve_spec("XAUUSD", {"source": "mt5_export", "symbol_info": info}, settings["costs"])
    assert (spec.point, spec.tick_value, spec.margin_per_min_lot, spec.demo) == (0.001, 0.1, 30.0, False)
    assert spec.commission_per_lot == settings["costs"]["symbols"]["XAUUSD"]["commission_per_lot"]
    demo_spec = resolve_spec("XAUUSD", {"source": "synthetic"}, settings["costs"])
    assert demo_spec.demo and demo_spec.point == DEMO_SPECS["XAUUSD"].point
    assert resolve_spec("XAUUSD.a", {"source": "other"}, {}).point == 0.01


def test_risk_at_min_lot_matches_broker_arithmetic():
    assert DEMO_SPECS["XAUUSD"].risk_money(450) == pytest.approx(4.5)
    assert DEMO_SPECS["EURUSD"].risk_money(100) == pytest.approx(1.0)


def test_unknown_symbol_without_costs_is_a_hard_error():
    with pytest.raises(MissingCostsError, match="Costs missing for NZDCAD"):
        resolve_spec("NZDCAD", {"source": "mt5_export", "symbol_info": {}}, {})


def test_exporter_output_loads_as_utc_broker_data(tmp_path):
    tool = load_exporter_tool()
    dtype = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"), ("tick_volume", "u8"), ("spread", "i4"), ("real_volume", "u8")]
    winter = int(pd.Timestamp("2026-01-05 10:00").timestamp())
    summer = int(pd.Timestamp("2026-07-06 10:00").timestamp())
    rates = np.array([(winter, 1.1, 1.2, 1.0, 1.15, 10, 6, 0), (summer, 1.15, 1.25, 1.1, 1.2, 12, 7, 0)], dtype=dtype)
    tool.write_csv(tmp_path / "EURUSD_M15.csv", tool.rates_to_rows(rates, "nyclose"))
    (tmp_path / "meta.json").write_text(json.dumps({"source": "mt5_export", "timeframe": "M15", "symbols": {"EURUSD": {"file": "EURUSD_M15.csv"}}}))
    df, prov = load_dataset(tmp_path)["EURUSD"]
    assert list(df.index) == [pd.Timestamp("2026-01-05 08:00", tz="UTC"), pd.Timestamp("2026-07-06 07:00", tz="UTC")]
    assert prov["source"] == "mt5_export"
    assert df["spread"].tolist() == [6.0, 7.0]


def test_exporter_detects_the_broker_clock():
    tool = load_exporter_tool()
    summer_now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    winter_now = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    assert tool.detect_server_tz(summer_now.timestamp() + 3 * 3600 + 5, summer_now) == "nyclose"
    assert tool.detect_server_tz(winter_now.timestamp() + 2 * 3600, winter_now) == "nyclose"
    assert tool.detect_server_tz(winter_now.timestamp(), winter_now) == 0
    assert tool.detect_server_tz(winter_now.timestamp() - 2 * 86400, winter_now) is None
    assert tool.us_summer_time(datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc))
    assert not tool.us_summer_time(datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc))
    assert not tool.us_summer_time(datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc))


def test_exporter_writes_only_where_git_ignores_it(tmp_path, monkeypatch):
    tool = load_exporter_tool()
    monkeypatch.chdir(ROOT / "tools")
    assert tool.parse_args(["--symbols", "XAUUSD"]).out == str(ROOT / "data" / "mt5")
    assert tool.unsafe_out(ROOT / "data" / "mt5") is None and tool.unsafe_out(ROOT / "local" / "x") is None
    assert tool.unsafe_out(tmp_path) is None
    assert "not in a git-ignored folder" in tool.unsafe_out(ROOT / "tools" / "data" / "mt5")
    assert tool.main(["--symbols", "XAUUSD", "--out", str(ROOT / "llm_trader" / "data" / "mt5")]) == 2


def test_exporter_is_strictly_read_only():
    source = (ROOT / "tools" / "export_mt5_data.py").read_text()
    for forbidden in ("order_send", "order_check", "positions_", "symbol_select", "Close("):
        assert forbidden not in source
    assert "import MetaTrader5" in source and "except ImportError" in source
