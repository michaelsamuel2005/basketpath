"""What people read: charts, the findings readout, OKRs and the README summary.

Every number is read from the build's results. None is typed in by hand, so the prose cannot drift from the data.
"""
from __future__ import annotations

import math
import pathlib

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BLUE, GREY, RED, GREEN = "#1f5f8b", "#9aa5b1", "#c0392b", "#2e8b57"
FAKE = ("> **Generated test data: these are not findings.** This output proves the pipeline end to end. "
        "Run the build on the real export to produce the real readout.")


def _nan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def pct(v, d=1):
    return "n/a" if _nan(v) else f"{100 * v:.{d}f}%"


def pp(v):
    return "n/a" if _nan(v) else f"{100 * v:+.2f} pp"


def money(v):
    return "n/a" if _nan(v) else f"${v:,.2f}"


def figures(funnel_df, daily, checkout_df, timeline, journey_start, out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(journey_start)

    t = timeline.copy()
    # Weeks start on Monday, but never before the first day of data (1 November 2020 was a Sunday).
    t["week"] = (t["date"] - pd.to_timedelta(t["date"].dt.dayofweek, unit="D")).clip(lower=t["date"].min())
    g = t.groupby("week")[["sessions", "purchase", "purchases_with_id", "begin_checkout", "checkouts_with_items",
                           "add_to_cart", "view_search_results"]].sum()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.8))
    a1.plot(g.index, 100 * g["purchases_with_id"] / g["purchase"].where(g["purchase"] > 0), marker="o", color=BLUE,
            label="Purchases carrying a transaction ID")
    a1.plot(g.index, 100 * g["checkouts_with_items"] / g["begin_checkout"].where(g["begin_checkout"] > 0), marker="o",
            color=GREEN, label="Checkouts listing their items")
    a1.set_ylim(0, 105)
    a1.set_ylabel("% of events, by week")
    a1.set_title("Tracking completeness", loc="left")
    a2.plot(g.index, 100 * g["add_to_cart"] / g["sessions"], marker="o", color=BLUE, label="add_to_cart")
    a2.plot(g.index, 100 * g["view_search_results"] / g["sessions"], marker="o", color=GREY, label="view_search_results")
    a2.set_ylabel("Events per 100 sessions, by week")
    a2.set_ylim(bottom=0)
    a2.set_title("Journey events firing", loc="left")
    for a in (a1, a2):
        a.axvline(start, color=RED, ls="--", lw=0.9)
        a.annotate("journey fully tracked from here", xy=(start, 0.0), xycoords=("data", "axes fraction"),
                   xytext=(4, 6), textcoords="offset points", fontsize=7, color=RED)
        a.legend(fontsize=7, frameon=False, loc="lower right")
        a.tick_params(axis="x", labelrotation=30, labelsize=7)
    fig.tight_layout()
    fig.savefig(out / "tracking_timeline.png", dpi=150)
    plt.close(fig)

    f = funnel_df[funnel_df["breakdown"] == "overall"].sort_values("step_order")
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    steps, n, r = list(f["step"])[::-1], list(f["sessions"])[::-1], list(f["rate_from_previous"])[::-1]
    ax.barh(steps, n, color=BLUE)
    for y, (v, rate) in enumerate(zip(n, r)):
        ax.text(v, y, f"  {v:,}  ({pct(rate)} of previous step)", va="center", fontsize=8)
    ax.set_xlim(0, max(n) * 1.55)
    ax.set_xlabel("Sessions")
    ax.set_title("Where shoppers drop out: nested funnel, analysis window", loc="left")
    fig.tight_layout()
    fig.savefig(out / "funnel.png", dpi=150)
    plt.close(fig)

    d = daily.sort_values("date")
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.plot(d["date"], 100 * d["conversion"], color=GREY, lw=1, label="Daily")
    ax.plot(d["date"], 100 * d["conversion"].rolling(7, min_periods=4).mean(), color=BLUE, lw=2, label="7-day average")
    # Labels sit in a staggered strip above the plot, so dates a day apart never collide with each other or the data.
    for i, (_, row) in enumerate(d[d["calendar_label"].notna()].iterrows()):
        ax.axvline(row["date"], color=RED, ls="--", lw=0.8)
        ax.annotate(row["calendar_label"], xy=(row["date"], 1.0), xycoords=("data", "axes fraction"),
                    xytext=(0, 3 + 10 * (i % 3)), textcoords="offset points", ha="center", fontsize=7,
                    color=RED, annotation_clip=False)
    ax.set_ylabel("Session conversion (%)")
    ax.set_title("Conversion through peak trading", loc="left", pad=38)
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out / "daily_conversion.png", dpi=150)
    plt.close(fig)

    c = checkout_df.set_index("device_category")
    cols = [("added_delivery_rate", "Added delivery"), ("added_payment_rate", "Added payment"), ("purchased_rate", "Purchased")]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    width = 0.8 / max(len(c), 1)
    for j, (dev, row) in enumerate(c.iterrows()):
        xs = [i + j * width for i in range(len(cols))]
        ax.bar(xs, [100 * row[k] for k, _ in cols], width=width, label=f"{dev} ({int(row['began_checkout']):,} checkouts)")
    ax.set_xticks([i + width * (len(c) - 1) / 2 for i in range(len(cols))], [label for _, label in cols])
    ax.set_ylabel("% of sessions that began checkout")
    ax.set_title("Finishing the shop, by device", loc="left")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(out / "checkout_by_device.png", dpi=150)
    plt.close(fig)


def _info_note(x: dict, r: dict) -> str:
    if x["check"] == "search_terms_obfuscated":
        share = "every one" if x["numerator"] == x["denominator"] else pct(x["rate"])
        return (f"Google's obfuscation replaced {share} of the {x['denominator']:,} search terms, so the analysis uses "
                "whether people searched, not what they searched for.")
    if x["check"] == "purchase_revenue_mismatch":
        g = r["revenue_gap"]
        mism = g["above"] + g["below"]
        if not mism:
            return "Every comparable order matches the sum of its items."
        text = (f"Of {g['match'] + mism:,} purchase events that can be compared with their items, {mism:,} differ by more than 1%: "
                f"{g['above']:,} worth more than their items and {g['below']:,} less, by a median of {pct(g['median_gap'])}.")
        if 0.35 <= g["above"] / mism <= 0.65:
            return text + (" Small gaps in both directions look like rounding or obfuscation noise. Missing delivery "
                           "or tax charges would all push the same way, so this is not treated as a tracking fault.")
        return text + (" Gaps mostly in one direction suggest delivery, tax or discounts are included in order value: "
                       "confirm against the tracking plan.")
    return f"{x['numerator']:,} of {x['denominator']:,} ({pct(x['rate'])})."


def findings_markdown(r: dict, real: bool) -> str:
    o, w, wo, od = r["overview"], r["window"], r["window_overview"], r["orders"]
    s, f, c, bd = r["search"], r["follow_up"], r["checkout"], r["biggest_drop"]
    checks = r["audit"]
    L = ["# Findings", ""]
    if not real:
        L += [FAKE, ""]
    L += [f"_Generated by `python -m basketpath.build` from {r['source']}. Every number is read from `marts/`; "
          "none is typed by hand._", "", "## The data, and the part of it the journey analyses use", "",
          f"{o['sessions']:,} sessions from {o['users']:,} users between {o['first_day']} and {o['last_day']} "
          f"({o['events']:,} events).", ""]
    when = (f"from {w['start']}, the first day after which every journey event (product views, basket, checkout "
            "steps, purchase and search) fired at a normal rate every day"
            if w["detected"] else "across the whole period, because no day could be found after which every journey "
            "event fired at a normal rate")
    held = w["excluded_weeks"]
    L += [f"The journey analyses use **{w['sessions']:,} sessions** {when}"
          + (f", leaving out {', '.join(held)}, which the data-quality gate held" if held else "")
          + f". Session conversion in that window is {pct(wo['conversion'], 2)} "
          f"(95% CI {pct(wo['conversion_lo'], 2)} to {pct(wo['conversion_hi'], 2)}).", "",
          "![Tracking timeline](figures/tracking_timeline.png)", "",
          "## Counting orders", "",
          f"The export holds {od['purchase_events']:,} purchase events. {od['repeats']:,} repeat an order ID the same "
          f"user had already sent, which is the confirmation page firing twice, and are removed. {od['empty']:,} carry "
          f"neither an ID nor any revenue and are not counted as orders. That leaves **{od['orders']:,} orders**"
          + (f", of which {od['orders_without_id']:,} have no ID: they carry revenue, so they are counted, but they "
             "cannot be checked for duplicates." if od["orders_without_id"] else ", all with a transaction ID."), "",
          (f"Counting raw purchase events instead would put session conversion in the analysis window at "
           f"{pct(od['conversion_raw_events'], 2)} rather than {pct(od['conversion_orders'], 2)}."
           if round(od["conversion_raw_events"], 5) != round(od["conversion_orders"], 5) else
           "In the analysis window, counting raw purchase events instead would not change session conversion."), "",
          "## Whether the tracking can be trusted", ""]
    fails = sorted([x for x in checks if x["status"] == "fail"], key=lambda x: {"high": 0, "medium": 1}.get(x["severity"], 2))
    L.append(f"The tracking audit ran {len(checks)} checks before any analysis, and {len(fails)} failed"
             + (". In order of severity:" if fails else "."))
    for x in fails:
        L.append(f"- **{x['check'].replace('_', ' ')}** ({x['severity']}, owner: {x['owner']}): "
                 f"{x['numerator']:,} of {x['denominator']:,} ({pct(x['rate'], 3)}), above the limit of {pct(x['threshold'], 1)}.")
    for x in [x for x in checks if x["status"] == "info"]:
        L.append(f"- For information, **{x['check'].replace('_', ' ')}**: {_info_note(x, r)}")
    L += ["", "Scorecard: `marts/audit_scorecard.csv`. Field coverage against the tracking plan: "
          "`marts/tracking_coverage.csv`. Day-by-day tracking: `marts/tracking_timeline.csv`.", "",
          "## Where shoppers drop out", "",
          f"The largest proportional loss is from **{bd['from_step'].lower()}** to **{bd['to_step'].lower()}**: "
          f"{pct(bd['kept'])} of the {bd['sessions_before']:,} sessions at the first step reached the second.", "",
          "| Step | Sessions | Share of all sessions | Share of previous step |", "|---|---:|---:|---:|"]
    for st in r["funnel_overall"]:
        L.append(f"| {st['step']} | {st['sessions']:,} | {pct(st['rate_from_start'], 2)} | {pct(st['rate_from_previous'])} |")
    steps = r["funnel_overall"]
    for before, after in zip(steps[1:], steps[2:]):
        if before["sessions"] >= 100 and after["sessions"] == before["sessions"]:
            L += ["", f"Every one of the {before['sessions']:,} sessions that {before['step'].lower()} also "
                  f"{after['step'].lower()}. A real step always loses someone, so this event is probably sent "
                  "automatically with the previous one, and the step separates no one."]
    ordering = r["window_overview"]["purchasing_sessions"]
    if ordering > steps[-1]["sessions"]:
        gap = ordering - steps[-1]["sessions"]
        L += ["", f"The nested funnel ends at {steps[-1]['sessions']:,} sessions, but {ordering:,} sessions in the window "
              f"ordered. The other {gap:,} ({pct(gap / ordering)} of ordering sessions) are missing an earlier tracked "
              "step, such as an `add_to_cart` event, so they count towards conversion but not the funnel's last step."]
    L += ["", "![Funnel](figures/funnel.png)", "",
          "Steps are nested: a session counts at a step only if it reached every earlier step. \"Viewed products\" means "
          "a `view_item` event, which in this export also fires on listing pages, so it measures seeing products "
          "rather than opening one product's page. Breakdowns by device, visitor type and channel: `marts/funnel.csv`.", "",
          "## Search: does it help, or do people who search already intend to buy?", ""]
    if not s["enough"]:
        L.append(f"Only {s['search_sessions']:,} sessions used site search, too few to answer this.")
    else:
        n, ad = s["naive"], s["adjusted"]
        L += [f"{pct(s['search_share'])} of sessions used site search. They converted at {pct(n['p1'], 2)} against "
              f"{pct(n['p0'], 2)} for other sessions: a naive difference of {pp(n['diff'])} "
              f"(95% CI {pp(n['lo'])} to {pp(n['hi'])}).", "",
              "But searchers differ before they search. Compared like with like, within groups sharing the same device, "
              "new or returning status, channel and purchase history, the difference is "
              f"{pp(ad['diff'])} (95% CI {pp(ad['lo'])} to {pp(ad['hi'])}), covering {pct(ad['coverage'])} of search sessions."
              + ("" if _nan(s["share_explained"]) or s["naive"]["diff"] <= 0 else
                 " The difference in who searches accounts for the whole naive gap." if s["share_explained"] >= 1 else
                 (" Differences in device, visitor type, channel and purchase history explain none of it: like for "
                  "like, the gap is " + ("slightly larger." if ad["diff"] > n["diff"] else "about the same."))
                 if s["share_explained"] <= 0.05 else
                 f" The difference in who searches accounts for about {pct(s['share_explained'], 0)} of the naive gap."), ""]
        if ad["lo"] <= 0 <= ad["hi"]:
            L.append("What remains is not distinguishable from zero, so this data cannot show that search itself raises conversion.")
        elif ad["diff"] > 0:
            L.append("A difference remains, but it may still reflect intent these groups do not capture, such as what the "
                     "shopper came for. Observational data cannot separate the two; an experiment can.")
        else:
            L.append("Held like for like, searchers convert less than comparable shoppers who did not search. That is worth "
                     "investigating: it can mean search is failing the people who use it.")
        L += ["", f"Searching sessions saw products {pct(s['product_view_rate_search'])} of the time, against "
                  f"{pct(s['product_view_rate_other'])} for other sessions."]
    L += ["", "### The experiment that would settle it", ""]
    if f.get("enough"):
        L += [f"Randomise **users**, not sessions, who search, between current search and a changed version. In the "
              f"{f['sizing_weeks']} sizing weeks (normal January trading, inside the analysis window), "
              f"{f['weekly_searching_users']:,.0f} users searched each week: {pct(f['baseline_weekly_conversion'], 2)} "
              f"of them bought, and {pct(f['baseline_product_view'], 2)} saw products in a search session.", "",
              "| Primary metric | Baseline | Smallest relative lift worth detecting | Users per arm | Weeks of search traffic |",
              "|---|---:|---:|---:|---:|"]
        L += [f"| {p['metric']} | {pct(p['baseline'], 2)} | {pct(p['relative_lift'], 0)} | {p['users_per_arm']:,} | {p['weeks']} |"
              for p in f["plans"]]
        ten = {p["metric"]: p["weeks"] for p in f["plans"] if abs(p["relative_lift"] - 0.10) < 1e-9}
        buy, see = ten.get("Bought within the week"), ten.get("Saw products in a search session")
        if buy and see and see < buy:
            L += ["", f"At this traffic, detecting a 10% lift in buying would take {buy} weeks, while the same lift in "
                  f"searchers seeing products would take {see}. So the practical primary metric is seeing products after "
                  "searching, the effect search can change directly, with buying and revenue per user as guardrails "
                  "rather than the decision metric."]
        L += ["", "Two-sided tests at 5% with 80% power. Agree the smallest lift worth shipping before starting, and do "
              "not stop early on a promising result."]
    else:
        L.append("The sizing weeks hold too little search traffic to size a test.")
    L += ["", "## Finishing the shop: checkout by device", ""]
    if c:
        L.append(f"Of sessions that began checkout, {pct(c['mobile'])} completed on mobile against {pct(c['desktop'])} on desktop "
                 f"({c['mobile_n']:,} and {c['desktop_n']:,} checkouts): a difference of {pp(c['diff'])} "
                 f"(95% CI {pp(c['lo'])} to {pp(c['hi'])}; {'significant at 5%' if c['p_value'] < 0.05 else 'within noise'}).")
    L += ["", "![Checkout by device](figures/checkout_by_device.png)", "", "## Peak trading", "",
          "| Window | Days used | Sessions a day | Conversion | Change vs baseline | Checkout completion | Revenue per order |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for x in r["windows"]:
        change = "baseline" if x["role"] == "baseline" else \
            f"{pp(x['conversion_change_pp'])} ({'p < 0.05' if x['conversion_p_value'] < 0.05 else 'within noise'})"
        days = f"{x['days']}" + (f" ({x['days_excluded']} held)" if x["days_excluded"] else "")
        L.append(f"| {x['window']} | {days} | {x['sessions_per_day']:,.0f} | {pct(x['conversion'], 2)} | {change} | "
                 f"{pct(x['checkout_completion'])} | {money(x['revenue_per_order'])} |")
    L += ["", "Conversion counts orders, which were tracked throughout, so every window is compared with the "
          "pre-Thanksgiving baseline, leaving out days in held weeks. Checkout completion appears only for windows inside "
          "the analysis window: before then checkout was not tracked the way it was later, so a comparison would measure "
          "the tracking change, not shoppers." + next(
              (f" In the baseline, {pct(x['share_orders_without_id'])} of orders have no transaction ID and cannot be "
               "checked for duplicates, so its revenue per order is less certain than later windows'."
               for x in r["windows"] if x["role"] == "baseline" and not _nan(x["share_orders_without_id"])
               and x["share_orders_without_id"] > 0), ""),
          "", "![Conversion through peak trading](figures/daily_conversion.png)", "",
          "## Custom segments", "", "| Segment | Sessions | Share of sessions | Conversion | Revenue per session |",
          "|---|---:|---:|---:|---:|"]
    for g in r["segments"]:
        L.append(f"| {g['segment']} | {g['sessions']:,} | {pct(g['share_of_sessions'])} | {pct(g['conversion'], 2)} | {money(g['revenue_per_session'])} |")
    L += ["", "Each segment is a SQL rule on the session table, listed in `marts/segments.csv`, so it can be rebuilt in any analytics tool.",
          "", "## What this data cannot tell us", "",
          "- It is Google's obfuscated sample from its own merchandise store, not a grocer's site. Search terms and some other values are placeholders.",
          "- The product lists inside `view_item` and `add_to_cart` events are not reliable here (see the audit), so the analysis works at session level, not product level.",
          "- Everything here is observational: differences between groups describe who did what, not what caused it.",
          "- Orders without transaction IDs are counted but cannot be de-duplicated.", ""]
    return "\n".join(L)


def okrs_markdown(r: dict, real: bool) -> str:
    s, c, wo = r["search"], r["checkout"], r["window_overview"]
    steps = {st["step"]: st for st in r["funnel_overall"]}
    basket = steps["Added to basket"]["rate_from_previous"]
    txn = next(x for x in r["audit"] if x["check"] == "purchases_missing_transaction_id")
    valid = 1 - txn["rate"] if not _nan(txn["rate"]) else float("nan")
    up = lambda v: "n/a" if _nan(v) else pct(min(v * 1.1, 0.99))
    L = ["# OKRs for a search, browse and checkout product team", ""]
    if not real:
        L += [FAKE, ""]
    L += ["_Generated by `python -m basketpath.build` from baselines measured in the analysis window. Targets are "
          "proposals to agree with the product team, not commitments. Metric definitions: [metrics.md](metrics.md)._", "",
          "## Objective 1: Help shoppers find the right product quickly", "",
          f"- **KR1** Raise the share of search sessions that go on to see products from {pct(s['product_view_rate_search'])} "
          f"to {up(s['product_view_rate_search'])} (10% relative).",
          f"- **KR2** Raise the share of product-viewing sessions that add to basket from {pct(basket)} to {up(basket)} (10% relative).",
          "", "## Objective 2: Make finishing the shop effortless on every device", ""]
    if c and c["desktop"] > c["mobile"]:
        L.append(f"- **KR3** Raise mobile checkout completion from {pct(c['mobile'])} to "
                 f"{pct(c['mobile'] + (c['desktop'] - c['mobile']) / 2)}, closing half the gap to desktop ({pct(c['desktop'])}).")
    elif c:
        L.append(f"- **KR3** Hold mobile checkout completion at or above {pct(c['mobile'])} (desktop: {pct(c['desktop'])}).")
    L += [f"- **KR4** Raise purchase events carrying a valid transaction ID to at least 99.5% (currently {pct(valid, 2)}), "
          "so every order can be counted once.", "",
          "## Health metrics: must not get worse while the KRs move", "",
          f"- Session conversion: {pct(wo['conversion'], 2)}",
          f"- Engaged-session share: {pct(wo['engaged_share'])}",
          "- High-severity tracking-audit failures: zero", ""]
    return "\n".join(L)


def readme_block(r: dict) -> str:
    o, w, wo, od, s, c, bd = (r["overview"], r["window"], r["window_overview"], r["orders"], r["search"],
                             r["checkout"], r["biggest_drop"])
    fails = [x["check"].replace("_", " ") for x in r["audit"] if x["status"] == "fail"]
    held = w["excluded_weeks"]
    L = [f"- **Data:** {o['sessions']:,} sessions from {o['users']:,} users, {o['first_day']} to {o['last_day']}. "
         f"Journey analyses use {w['sessions']:,} sessions from {w['start']}, when every journey event was tracked"
         + (f", excluding held week{'s' if len(held) > 1 else ''} {', '.join(held)}" if held else "") + ".",
         f"- **Orders:** {od['purchase_events']:,} purchase events become {od['orders']:,} orders after removing "
         f"{od['repeats']:,} double-fired repeats and {od['empty']:,} empty events.",
         f"- **Tracking audit:** {len(fails)} of {len(r['audit'])} checks failed" + (f": {', '.join(fails)}." if fails else "."),
         f"- **Conversion:** {pct(wo['conversion'], 2)} of sessions (95% CI {pct(wo['conversion_lo'], 2)} to "
         f"{pct(wo['conversion_hi'], 2)}). Biggest drop: {bd['from_step'].lower()} to {bd['to_step'].lower()}, where {pct(bd['kept'])} continue."]
    if s["enough"]:
        L.append(f"- **Search:** used in {pct(s['search_share'])} of sessions. Naive conversion gap {pp(s['naive']['diff'])}; "
                 f"like for like {pp(s['adjusted']['diff'])} (95% CI {pp(s['adjusted']['lo'])} to {pp(s['adjusted']['hi'])}).")
    if c:
        L.append(f"- **Checkout completion:** mobile {pct(c['mobile'])}, desktop {pct(c['desktop'])} ({pp(c['diff'])}).")
    return "\n".join(L)
