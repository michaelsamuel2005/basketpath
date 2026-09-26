import datetime as dt

import duckdb
import pandas as pd

from basketpath import analysis, db, fixture
from basketpath.schema import EVENT_COLUMNS


def _events(tmp_path, rows) -> duckdb.DuckDBPyConnection:
    """A tiny hand-made export, written and read exactly as the real one is."""
    base = dict.fromkeys(EVENT_COLUMNS)
    full = []
    for user, sid, secs, name, extra in rows:
        r = dict(base, event_date=dt.date(2020, 12, 1), event_name=name, user_pseudo_id=user, ga_session_id=sid,
                 ga_session_number=1, device_category="desktop", first_medium="organic",
                 event_ts=pd.Timestamp("2020-12-01", tz="UTC") + pd.Timedelta(seconds=secs))
        r.update(extra)
        full.append(r)
    path = tmp_path / "events.parquet"
    fixture.typed(pd.DataFrame(full, columns=list(EVENT_COLUMNS))).to_parquet(path, index=False)
    con = duckdb.connect()
    con.execute(f"CREATE VIEW events AS SELECT * FROM read_parquet('{path.as_posix()}')")
    db.build(con)
    return con


def test_order_rule_removes_double_fires_and_empty_events_but_keeps_real_orders(tmp_path):
    con = _events(tmp_path, [
        ("u1", 1, 0, "session_start", {}),
        ("u1", 1, 10, "purchase", dict(transaction_id="T1", purchase_revenue_usd=50.0)),
        ("u1", 1, 11, "purchase", dict(transaction_id="T1", purchase_revenue_usd=50.0)),   # double-fire: removed
        ("u2", 2, 0, "session_start", {}),
        ("u2", 2, 10, "purchase", dict(transaction_id=None, purchase_revenue_usd=30.0)),   # no ID, has revenue: counted
        ("u3", 3, 0, "session_start", {}),
        ("u3", 3, 10, "purchase", dict(transaction_id="(not set)", purchase_revenue_usd=0.0)),  # empty: not an order
        ("u4", 4, 0, "session_start", {}),
        ("u4", 4, 10, "purchase", dict(transaction_id="T1", purchase_revenue_usd=40.0)),   # same ID, other user: counted
    ])
    got = con.execute("SELECT user_pseudo_id, orders, revenue_usd, has_purchase, has_purchase_event "
                      "FROM sessions ORDER BY 1").fetchall()
    assert got == [("u1", 1, 50.0, True, True), ("u2", 1, 30.0, True, True),
                   ("u3", 0, 0.0, False, True), ("u4", 1, 40.0, True, True)]
    summary = analysis.order_summary(con)
    assert (summary["purchase_events"], summary["repeats"], summary["empty"], summary["orders"],
            summary["orders_without_id"]) == (5, 1, 1, 3, 1)


def test_journey_window_is_the_whole_period_when_everything_is_tracked(fx):
    con, _, _ = fx
    _, tracking = analysis.tracking_timeline(con)
    assert tracking == {"start": "2020-11-01", "detected": True}


def test_journey_window_starts_when_a_missing_step_starts_being_tracked(fx):
    # Remove add_to_cart before 20 November, as if basket tracking was only switched on that day.
    _, _, out = fx
    con = duckdb.connect()
    con.execute(f"""CREATE VIEW events AS SELECT * FROM read_parquet('{(out / "raw" / "events").as_posix()}/*.parquet')
                    WHERE NOT (event_name = 'add_to_cart' AND event_date < DATE '2020-11-20')""")
    db.build(con)
    timeline, tracking = analysis.tracking_timeline(con)
    assert tracking["detected"] and "2020-11-20" <= tracking["start"] <= "2020-11-22"
    assert not timeline.loc[timeline["date"] < "2020-11-20", "in_journey_window"].any()


def test_analysis_window_leaves_out_held_weeks(fx):
    con, _, _ = fx
    info = analysis.create_analysis_sessions(con, "2020-11-01", ["2020-W50"])
    in_w50 = con.execute("SELECT COUNT(*) FROM sessions WHERE session_date BETWEEN DATE '2020-12-07' AND DATE '2020-12-13'").fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert in_w50 > 0 and info["sessions"] == total - in_w50
    assert con.execute("SELECT COUNT(*) FROM analysis_sessions WHERE session_date BETWEEN DATE '2020-12-07' "
                       "AND DATE '2020-12-13'").fetchone()[0] == 0
