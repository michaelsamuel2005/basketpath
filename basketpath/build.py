"""Build everything from the extracted data: audit, analyses, marts, charts, readout, weekly reports and docs.

    python -m basketpath.build             # real data in data/raw -> marts/, reports/, docs/okrs.md, README results
    python -m basketpath.build --fixture   # generated test data -> build/fixture/ (never touches committed outputs)
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import re

from . import analysis, audit, db, fixture, plan, readout, report

README_MARKERS = ("<!-- results:start -->", "<!-- results:end -->")


def _plain(v):
    """JSON-safe: numpy and pandas scalars to Python, NaN to null."""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def run(raw: pathlib.Path, out: pathlib.Path, real: bool) -> dict:
    con = db.connect(raw)
    # 1. When was the journey fully tracked, and which weeks does the gate hold?
    timeline, tracking = analysis.tracking_timeline(con)
    daily = analysis.daily_kpis(con, tracking["start"])
    held = report.held_weeks(daily)
    window = analysis.create_analysis_sessions(con, tracking["start"], held) | dict(detected=tracking["detected"])
    # 2. Audit, then the journey analyses on the analysis window only.
    card, cov = audit.run(con)
    A = "analysis_sessions"
    fun = analysis.funnel(con, A)
    search, strata = analysis.search_vs_intent(con, A)
    chk, chk_cmp = analysis.checkout_by_device(con, A)
    segs = analysis.segments(con, A)
    wins = analysis.windows(con, daily, held)

    marts = out / "marts"
    marts.mkdir(parents=True, exist_ok=True)
    for name, df in {"audit_scorecard": card, "tracking_coverage": cov, "tracking_timeline": timeline, "funnel": fun,
                     "search_strata": strata, "checkout_by_device": chk, "segments": segs, "daily_kpis": daily,
                     "trading_windows": wins}.items():
        df.to_csv(marts / f"{name}.csv", index=False, float_format="%.6g")

    results = _plain(dict(
        source="the real GA4 export" if real else "generated test data",
        overview=analysis.overview(con), window=window, window_overview=analysis.overview(con, A),
        orders=analysis.order_summary(con, A), revenue_gap=audit.revenue_gap(con), held_weeks=held,
        audit=card.to_dict("records"),
        funnel_overall=fun[fun["breakdown"] == "overall"].to_dict("records"),
        biggest_drop=analysis.biggest_drop(fun), search=search, follow_up=analysis.follow_up_test(con, A),
        checkout=chk_cmp, windows=wins.to_dict("records"), segments=segs.to_dict("records")))
    (marts / "results.json").write_text(json.dumps(results, indent=2))
    results = _restore_nan(json.loads(json.dumps(results)))

    reports = out / "reports"
    readout.figures(fun, daily, chk, timeline, window["start"], reports / "figures")
    (reports / "findings.md").write_text(readout.findings_markdown(results, real))
    report.write_weeks(daily, reports / "weekly", report.weeks(daily))
    docs = out / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "tracking_plan.md").write_text(plan.render_markdown())
    (docs / "okrs.md").write_text(readout.okrs_markdown(results, real))
    readme = out / "README.md"
    if real and readme.exists():
        text = readme.read_text()
        start, end = README_MARKERS
        block = f"{start}\n{readout.readme_block(results)}\n\nFull readout: [reports/findings.md](reports/findings.md).\n{end}"
        readme.write_text(re.sub(re.escape(start) + r".*?" + re.escape(end), lambda _: block, text, flags=re.S))
    return results


def _restore_nan(v):
    if isinstance(v, dict):
        return {k: _restore_nan(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_restore_nan(x) for x in v]
    return float("nan") if v is None else v


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=pathlib.Path, default=pathlib.Path("data/raw"))
    ap.add_argument("--out", type=pathlib.Path, default=None)
    ap.add_argument("--fixture", action="store_true", help="build on generated test data instead")
    a = ap.parse_args(argv)
    if a.fixture:
        out = a.out or pathlib.Path("build/fixture")
        fixture.generate(out)
        raw, real = out / "raw", False
    else:
        out, raw, real = a.out or pathlib.Path("."), a.raw, True
    r = run(raw, out, real)
    fails = [x["check"] for x in r["audit"] if x["status"] == "fail"]
    print(f"built from {r['source']}: {r['overview']['sessions']:,} sessions; audit failures: {fails or 'none'}")
    print(f"outputs in {out.resolve()}")


if __name__ == "__main__":
    main()
