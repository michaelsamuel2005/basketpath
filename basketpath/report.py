"""Automated weekly KPI report, with a data-quality gate that holds a week when tracking broke.

The gate looks for incidents, not chronic problems. A problem present every week becomes a standing note
on every report. A week is held when it is materially worse than the weeks before it:

- empty purchase events (no transaction ID and no revenue) more than 10 points above the median of the
  previous four weeks: enough that roughly one order in ten may have been lost;
- sessions without a session_start event more than 5 points above that median: enough to move session
  counts, and so conversion, by more than normal week-to-week noise.

With no earlier weeks to compare against, the median is taken as zero.

    python -m basketpath.report --marts marts --out reports/weekly          # latest full week
    python -m basketpath.report --marts marts --out reports/weekly --all    # every week
"""
from __future__ import annotations

import argparse
import pathlib
import statistics

import pandas as pd

from . import stats

GATE_EMPTY_PURCHASES = 0.10
GATE_MISSING_START = 0.05
TRAILING_WEEKS = 4
SUM_COLS = ["sessions", "purchasing_sessions", "orders", "revenue_usd", "search_sessions", "product_view_sessions",
            "basket_sessions", "checkout_sessions", "checkout_completed", "purchase_events", "purchases_missing_id",
            "empty_purchase_events", "repeat_purchase_events", "orders_without_id", "sessions_missing_start"]


def iso_week(d) -> str:
    y, w, _ = pd.Timestamp(d).isocalendar()
    return f"{y}-W{w:02d}"


def weeks(daily: pd.DataFrame) -> list[str]:
    return list(dict.fromkeys(daily["date"].map(iso_week)))


def _rate(num, den, default=float("nan")):
    return num / den if den else default


def _sum(g: pd.DataFrame) -> dict:
    out = {k: float(g[k].sum()) for k in SUM_COLS}
    out.update(days=int(len(g)), first=str(g["date"].min().date()), last=str(g["date"].max().date()),
               journey_tracked=bool(g["journey_tracked"].all()) if "journey_tracked" in g else True)
    return out


def _problem_rates(c: dict) -> dict:
    return dict(empty=_rate(c["empty_purchase_events"], c["purchase_events"], 0.0),
                start=_rate(c["sessions_missing_start"], c["sessions"], 0.0))


def weekly(daily: pd.DataFrame, week: str) -> dict:
    d = daily.assign(week=daily["date"].map(iso_week))
    order = weeks(daily)
    i = order.index(week)
    cur = _sum(d[d["week"] == week])
    prev_label = order[i - 1] if i > 0 else None
    prev = _sum(d[d["week"] == prev_label]) if prev_label else None
    history = [_problem_rates(_sum(d[d["week"] == w])) for w in order[max(0, i - TRAILING_WEEKS):i]]
    base = {k: statistics.median(h[k] for h in history) if history else 0.0 for k in ("empty", "start")}
    now = _problem_rates(cur)
    pc = lambda v: f"{100 * v:.1f}%"
    reasons = []
    if now["empty"] > base["empty"] + GATE_EMPTY_PURCHASES:
        reasons.append(f"{int(cur['empty_purchase_events'])} of {int(cur['purchase_events'])} purchase events "
                       f"({pc(now['empty'])}) are empty, with no transaction ID and no revenue, against {pc(base['empty'])} "
                       "in recent weeks. Real orders may have been lost.")
    if now["start"] > base["start"] + GATE_MISSING_START:
        reasons.append(f"{int(cur['sessions_missing_start'])} of {int(cur['sessions'])} sessions ({pc(now['start'])}) "
                       f"have no session_start event, against {pc(base['start'])} in recent weeks, so visits may be miscounted.")
    notes = []
    if cur["orders_without_id"]:
        notes.append(f"{int(cur['orders_without_id'])} of {int(cur['orders'])} orders have no transaction ID. "
                     "They carry revenue, so they are counted, but they cannot be checked for duplicates.")
    if cur["repeat_purchase_events"]:
        notes.append(f"{int(cur['repeat_purchase_events'])} repeated purchase events (same order ID, same user) were removed.")
    if cur["empty_purchase_events"] and not reasons:
        notes.append(f"{int(cur['empty_purchase_events'])} empty purchase events (no ID, no revenue) were not counted as orders.")
    if not cur["journey_tracked"]:
        notes.append("Some journey events were not yet fully tracked this week, so basket and checkout rates "
                     "are not comparable with later weeks.")
    return dict(week=week, previous=prev_label, cur=cur, prev=prev, held=bool(reasons), reasons=reasons,
                notes=notes, baseline=base)


def held_weeks(daily: pd.DataFrame) -> list[str]:
    return [w for w in weeks(daily) if weekly(daily, w)["held"]]


def latest_full_week(daily: pd.DataFrame) -> str:
    full = [w for w in weeks(daily) if weekly(daily, w)["cur"]["days"] == 7]
    return full[-1] if full else weeks(daily)[-1]


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
        L += ["Data-quality gate: **passed** (no incident against recent weeks).", ""]
    if w["notes"]:
        L += ["Notes:"] + [f"- {n}" for n in w["notes"]] + [""]
    conv, lo, hi = stats.wilson(int(c["purchasing_sessions"]), int(c["sessions"]))
    L += [f"| Metric | {week} | {w['previous'] or 'previous'} | Change |", "|---|---:|---:|---:|"]
    pct = lambda v: "n/a" if v != v else f"{100 * v:.2f}%"
    num = lambda v: f"{v:,.0f}"
    money = lambda v: "n/a" if v != v else f"${v:,.2f}"
    rel = lambda a, b: "n/a" if not b or a != a or b != b else f"{100 * (a - b) / b:+.1f}%"
    pp = lambda a, b: "n/a" if a != a or b != b else f"{100 * (a - b):+.2f} pp"

    def row(name, cur_v, prev_v, fmt, change):
        L.append(f"| {name} | {fmt(cur_v)} | {fmt(prev_v) if prev_v is not None else 'n/a'} | {change} |")

    g = lambda d, k: d[k] if d else None
    row("Sessions", c["sessions"], g(p, "sessions"), num, rel(c["sessions"], g(p, "sessions")))
    change = "n/a"
    if p:
        t = stats.two_proportions(int(c["purchasing_sessions"]), int(c["sessions"]), int(p["purchasing_sessions"]), int(p["sessions"]))
        change = f"{100 * t['diff']:+.2f} pp ({'significant at 5%' if t['p_value'] < 0.05 else 'within noise'})"
    L.append(f"| Session conversion | {pct(conv)} (95% CI {pct(lo)} to {pct(hi)}) | "
             f"{pct(_rate(p['purchasing_sessions'], p['sessions'])) if p else 'n/a'} | {change} |")
    row("Orders", c["orders"], g(p, "orders"), num, rel(c["orders"], g(p, "orders")))
    row("Revenue (USD)", c["revenue_usd"], g(p, "revenue_usd"), money, rel(c["revenue_usd"], g(p, "revenue_usd")))
    aov = lambda d: _rate(d["revenue_usd"], d["orders"])
    row("Revenue per order", aov(c), aov(p) if p else None, money, rel(aov(c), aov(p)) if p else "n/a")
    for name, k, den in [("Sessions using search", "search_sessions", "sessions"),
                         ("Sessions viewing products", "product_view_sessions", "sessions"),
                         ("Sessions adding to basket", "basket_sessions", "sessions"),
                         ("Checkout completion", "checkout_completed", "checkout_sessions")]:
        a = _rate(c[k], c[den])
        b = _rate(p[k], p[den]) if p else None
        row(name, a, b, pct, pp(a, b) if p else "n/a")
    L += ["", "_Generated by `python -m basketpath.report` from `marts/daily_kpis.csv`. Conversion intervals are "
          "95% Wilson intervals; the week-on-week conversion change is a two-proportion z-test. Orders follow the "
          "rule in docs/metrics.md._", ""]
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
