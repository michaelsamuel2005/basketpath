import filecmp

from basketpath import analysis, build, report
from basketpath.schema import EVENT_COLUMNS
import pandas as pd


def test_gate_holds_only_the_week_with_an_incident(fx):
    # The planted incident: 25 empty purchase events (no ID, no revenue) in one week.
    con, key, _ = fx
    daily = analysis.daily_kpis(con)
    assert report.held_weeks(daily) == [key["gate_week"]]
    assert "Held: do not circulate" in report.weekly_markdown(daily, key["gate_week"])


def test_a_chronic_problem_is_a_note_not_a_hold(fx):
    # Every week missing IDs at the same rate is a known issue, not an incident.
    con, _, _ = fx
    daily = analysis.daily_kpis(con)
    daily = daily.assign(orders_without_id=(daily["orders"] * 0.15).round(),
                         empty_purchase_events=(daily["purchase_events"] * 0.05).round())
    held = report.held_weeks(daily)
    assert held == [], held
    assert "cannot be checked for duplicates" in report.weekly_markdown(daily, "2020-W51")


def test_weekly_report_compares_with_the_previous_week(fx):
    con, _, _ = fx
    daily = analysis.daily_kpis(con)
    md = report.weekly_markdown(daily, "2020-W51")
    assert "2020-W50" in md and "Session conversion" in md and "gate: **passed**" in md


def test_generated_data_has_exactly_the_extract_contract(fx):
    _, _, out = fx
    first = sorted((out / "raw" / "events").glob("*.parquet"))[0]
    assert list(pd.read_parquet(first).columns) == list(EVENT_COLUMNS)


def test_build_is_idempotent_and_labels_generated_output(fx, tmp_path):
    _, _, out = fx
    a, b = tmp_path / "a", tmp_path / "b"
    build.run(out / "raw", a, real=False)
    build.run(out / "raw", b, real=False)
    names = sorted(p.name for p in (a / "marts").glob("*.csv"))
    assert len(names) == 9
    match, mismatch, errors = filecmp.cmpfiles(a / "marts", b / "marts", names, shallow=False)
    assert not mismatch and not errors
    assert "not findings" in (a / "reports" / "findings.md").read_text()
    assert "not findings" in (a / "docs" / "okrs.md").read_text()
