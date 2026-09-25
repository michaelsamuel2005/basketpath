"""Automated weekly KPI report, with a data-quality gate that holds a week's numbers when tracking broke.

    python -m basketpath.report --marts marts --out reports/weekly          # latest full week
    python -m basketpath.report --marts marts --out reports/weekly --all    # every week
"""
from __future__ import annotations

import argparse
import pathlib

import pandas as pd

from . import stats

GATE_MISSING_TXN = 0.05     # share of purchase events without a transaction ID
GATE_MISSING_START = 0.02   # share of sessions without a session_start event
SUM_COLS = ["sessions", "purchasing_sessions", "revenue_usd", "search_sessions", "product_view_sessions",
            "basket_sessions", "checkout_sessions", "checkout_completed", "purchase_events",
            "purchases_missing_txn", "sessions_missing_start"]


def iso_week(d) -> str:
    y, w, _ = pd.Timestamp(d).isocalendar()
    return f"{y}-W{w:02d}"


def weeks(daily: pd.DataFrame) -> list[str]:
    return list(dict.fromkeys(daily["date"].map(iso_week)))


def _sum(g: pd.DataFrame) -> dict:
    return {k: float(g[k].sum()) for k in SUM_COLS} | dict(days=int(len(g)),
            first=str(g["date"].min().date()), last=str(g["date"].max().date()))


def weekly(daily: pd.DataFrame, week: str) -> dict:
    d = daily.assign(week=daily["date"].map(iso_week))
    order = weeks(daily)
    i = order.index(week)
    cur = _sum(d[d["week"] == week])
    prev_label = order[i - 1] if i > 0 else None
    prev = _sum(d[d["week"] == prev_label]) if prev_label else None
    reasons = []
    if cur["purchase_events"] and cur["purchases_missing_txn"] / cur["purchase_events"] > GATE_MISSING_TXN:
        reasons.append(f"{int(cur['purchases_missing_txn'])} of {int(cur['purchase_events'])} purchase events have no "
                       f"transaction ID (limit {GATE_MISSING_TXN:.0%}), so orders cannot be de-duplicated")
    if cur["sessions"] and cur["sessions_missing_start"] / cur["sessions"] > GATE_MISSING_START:
        reasons.append(f"{int(cur['sessions_missing_start'])} of {int(cur['sessions'])} sessions have no session_start "
                       f"event (limit {GATE_MISSING_START:.0%}), so visits may be miscounted")
    return dict(week=week, previous=prev_label, cur=cur, prev=prev, held=bool(reasons), reasons=reasons)


def latest_full_week(daily: pd.DataFrame) -> str:
    full = [w for w in weeks(daily) if weekly(daily, w)["cur"]["days"] == 7]
    return full[-1] if full else weeks(daily)[-1]


def _rate(num, den):
    return num / den if den else float("nan")


def weekly_markdown(daily: pd.DataFrame, week: str) -> str:
    w = weekly(daily, week)
    c, p = w["cur"], w["prev"]
    L = [f"# Weekly journey report: {week} ({c['first']} to {c['last']})", ""]
    if c["days"] < 7:
        L += [f"_Partial week: {c['days']} days of data._", ""]
    if w["held"]:
        L += ["> **Held: do not circulate these numbers.**"] + [f"> - {r}" for r in w["reasons"]] + \
             ["> Fix or explain the tracking problem first. The figures below are for investigation only.", ""]
    else:
        L += ["Data-quality gate: **passed** (transaction IDs and session starts within limits).", ""]
    conv, lo, hi = stats.wilson(int(c["purchasing_sessions"]), int(c["sessions"]))
    L += [f"| Metric | {week} | {w['previous'] or 'previous'} | Change |", "|---|---:|---:|---:|"]

    def row(name, cur_v, prev_v, fmt, change):
        L.append(f"| {name} | {fmt(cur_v)} | {fmt(prev_v) if prev_v is not None else 'n/a'} | {change} |")

    pct = lambda v: "n/a" if v != v else f"{100 * v:.2f}%"
    num = lambda v: f"{v:,.0f}"
    money = lambda v: "n/a" if v != v else f"${v:,.2f}"
    rel = lambda a, b: "n/a" if not b else f"{100 * (a - b) / b:+.1f}%"
    pp = lambda a, b: "n/a" if a != a or b != b else f"{100 * (a - b):+.2f} pp"
    g = lambda d, k: d[k] if d else None
    row("Sessions", c["sessions"], g(p, "sessions"), num, rel(c["sessions"], g(p, "sessions")))
    change = "n/a"
    if p:
        t = stats.two_proportions(int(c["purchasing_sessions"]), int(c["sessions"]), int(p["purchasing_sessions"]), int(p["sessions"]))
        change = f"{100 * t['diff']:+.2f} pp ({'significant at 5%' if t['p_value'] < 0.05 else 'within noise'})"
    L.append(f"| Session conversion | {pct(conv)} (95% CI {pct(lo)} to {pct(hi)}) | "
             f"{pct(_rate(p['purchasing_sessions'], p['sessions'])) if p else 'n/a'} | {change} |")
    row("Revenue (USD)", c["revenue_usd"], g(p, "revenue_usd"), money, rel(c["revenue_usd"], g(p, "revenue_usd")))
    aov = lambda d: _rate(d["revenue_usd"], d["purchasing_sessions"])
    row("Revenue per purchasing session", aov(c), aov(p) if p else None, money, rel(aov(c), aov(p)) if p else "n/a")
    for name, k, den in [("Sessions using search", "search_sessions", "sessions"),
                         ("Sessions viewing a product", "product_view_sessions", "sessions"),
                         ("Sessions adding to basket", "basket_sessions", "sessions"),
                         ("Checkout completion", "checkout_completed", "checkout_sessions")]:
        a = _rate(c[k], c[den])
        b = _rate(p[k], p[den]) if p else None
        row(name, a, b, pct, pp(a, b) if p else "n/a")
    L += ["", "_Generated by `python -m basketpath.report` from `marts/daily_kpis.csv`. Conversion intervals are "
          "95% Wilson intervals; the week-on-week conversion change is a two-proportion z-test._", ""]
    return "\n".join(L)


def write_weeks(daily: pd.DataFrame, out: pathlib.Path, which) -> list[pathlib.Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for week in which:
        path = out / f"{week}.md"
        path.write_text(weekly_markdown(daily, week))
        paths.append(path)
    return paths


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--marts", type=pathlib.Path, default=pathlib.Path("marts"))
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("reports/weekly"))
    ap.add_argument("--week", help="ISO week such as 2020-W50 (default: latest full week)")
    ap.add_argument("--all", action="store_true", help="write every week")
    a = ap.parse_args(argv)
    daily = pd.read_csv(a.marts / "daily_kpis.csv", parse_dates=["date"])
    which = weeks(daily) if a.all else [a.week or latest_full_week(daily)]
    for path in write_weeks(daily, a.out, which):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
