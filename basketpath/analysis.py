"""The questions a product team asks of the shopping journey, answered from the session table."""
from __future__ import annotations

import math

import pandas as pd

from . import stats

STEPS = [("Started a visit", None), ("Viewed a product", "f_view_item"), ("Added to basket", "f_add_to_cart"),
         ("Began checkout", "f_checkout"), ("Added delivery details", "f_shipping"),
         ("Added payment details", "f_payment"), ("Purchased", "f_purchase")]
BREAKDOWNS = {"overall": "'all sessions'", "device": "device_category",
              "visitor type": "user_type", "channel": "medium_group"}
# Things known before a visit's first search, so they can confound search without being caused by it.
STRATA = ["device_category", "user_type", "medium_group", "prior_purchaser"]
SEGMENTS = [
    ("All sessions", "TRUE"),
    ("Searched", "has_search"),
    ("Did not search", "NOT has_search"),
    ("Viewed a product, added nothing", "has_view_item AND NOT has_add_to_cart"),
    ("Abandoned basket", "has_add_to_cart AND NOT has_purchase"),
    ("Abandoned checkout", "has_begin_checkout AND NOT has_purchase"),
    ("New visitors on mobile", "user_type = 'new' AND device_category = 'mobile'"),
    ("Returning previous buyers", "prior_purchaser"),
    ("Paid search visitors", "medium_group = 'paid search'"),
]


def _i(v) -> int:
    return int(v or 0)


def overview(con) -> dict:
    first, last, n, users, buyers, revenue, searches, engaged = con.execute("""
        SELECT MIN(session_date), MAX(session_date), COUNT(*), COUNT(DISTINCT user_pseudo_id),
               SUM(CAST(has_purchase AS INT)), SUM(revenue_usd), SUM(CAST(has_search AS INT)),
               SUM(CAST(is_engaged AS INT)) FROM sessions""").fetchone()
    p, lo, hi = stats.wilson(_i(buyers), _i(n))
    mix = lambda col: {str(k): float(v) for k, v in con.execute(
        f"SELECT {col}, COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS s FROM sessions GROUP BY 1 ORDER BY 2 DESC LIMIT 5").fetchall()}
    return dict(first_day=str(first), last_day=str(last),
                events=_i(con.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
                sessions=_i(n), users=_i(users), purchasing_sessions=_i(buyers), revenue_usd=float(revenue or 0),
                conversion=p, conversion_lo=lo, conversion_hi=hi,
                revenue_per_purchasing_session=float(revenue or 0) / _i(buyers) if buyers else float("nan"),
                search_share=_i(searches) / _i(n) if n else float("nan"),
                engaged_share=_i(engaged) / _i(n) if n else float("nan"),
                device_mix=mix("device_category"), country_mix=mix("country"), channel_mix=mix("medium_group"))


def funnel(con) -> pd.DataFrame:
    """Nested funnel per breakdown, long format for Tableau: one row per group and step."""
    sums = ", ".join(f"SUM(CAST({col} AS INT)) AS s{i}" for i, (_, col) in enumerate(STEPS) if col)
    rows = []
    for breakdown, expr in BREAKDOWNS.items():
        df = con.execute(f"SELECT {expr} AS grp, COUNT(*) AS s0, {sums} FROM sessions GROUP BY 1 ORDER BY 2 DESC").df()
        for _, r in df.iterrows():
            start = prev = int(r["s0"])
            for i, (label, _) in enumerate(STEPS):
                n = int(r[f"s{i}"])
                rows.append(dict(breakdown=breakdown, group=str(r["grp"]), step_order=i, step=label, sessions=n,
                                 rate_from_start=n / start if start else math.nan,
                                 rate_from_previous=n / prev if prev else math.nan))
                prev = n
    return pd.DataFrame(rows)


def biggest_drop(funnel_df: pd.DataFrame) -> dict:
    steps = funnel_df[(funnel_df["breakdown"] == "overall") & (funnel_df["step_order"] > 0)]
    worst = steps.loc[steps["rate_from_previous"].idxmin()]
    before = funnel_df[(funnel_df["breakdown"] == "overall") & (funnel_df["step_order"] == worst["step_order"] - 1)].iloc[0]
    return dict(from_step=before["step"], to_step=worst["step"], kept=float(worst["rate_from_previous"]),
                sessions_before=int(before["sessions"]), sessions_after=int(worst["sessions"]))


def search_vs_intent(con, min_search_sessions: int = 100) -> tuple[dict, pd.DataFrame]:
    """Do searchers convert more because search helps, or because people who search were likelier to buy anyway?"""
    df = con.execute(f"""SELECT {', '.join(STRATA)}, has_search, COUNT(*) AS n,
                         SUM(CAST(has_purchase AS INT)) AS x FROM sessions GROUP BY ALL""").df()
    s1 = df[df["has_search"]].groupby(STRATA)[["n", "x"]].sum().rename(columns={"n": "n_search", "x": "x_search"})
    s0 = df[~df["has_search"]].groupby(STRATA)[["n", "x"]].sum().rename(columns={"n": "n_other", "x": "x_other"})
    strata = s1.join(s0, how="outer").fillna(0).astype("int64").reset_index()
    n1, x1 = int(strata["n_search"].sum()), int(strata["x_search"].sum())
    n0, x0 = int(strata["n_other"].sum()), int(strata["x_other"].sum())
    naive = stats.two_proportions(x1, n1, x0, n0)
    adjusted = stats.standardised_difference(
        strata[["n_search", "x_search", "n_other", "x_other"]].itertuples(index=False, name=None))
    view = con.execute("""SELECT
        SUM(CAST(has_search AND has_view_item AS INT)) * 1.0 / NULLIF(SUM(CAST(has_search AS INT)), 0),
        SUM(CAST(NOT has_search AND has_view_item AS INT)) * 1.0 / NULLIF(SUM(CAST(NOT has_search AS INT)), 0)
        FROM sessions""").fetchone()
    explained = 1 - adjusted["diff"] / naive["diff"] if naive["diff"] not in (0, None) and not math.isnan(naive["diff"]) else math.nan
    summary = dict(enough=n1 >= min_search_sessions, search_sessions=n1, other_sessions=n0,
                   search_share=n1 / (n1 + n0) if n1 + n0 else math.nan,
                   naive=naive, adjusted=adjusted, share_explained=explained,
                   product_view_rate_search=float(view[0]) if view[0] is not None else math.nan,
                   product_view_rate_other=float(view[1]) if view[1] is not None else math.nan,
                   controlled_for=STRATA)
    return summary, strata


def follow_up_test(con, lifts=(0.05, 0.10, 0.20)) -> dict:
    """Size the experiment that would settle the search question. Unit: user, so sessions need no clustering fix."""
    df = con.execute("""
        WITH w AS (
          SELECT date_trunc('week', s.session_date) AS wk, s.user_pseudo_id,
                 bool_or(s.has_search) AS searched, bool_or(s.has_purchase) AS bought
          FROM sessions AS s JOIN trading_windows AS t
            ON t.role = 'baseline' AND s.session_date BETWEEN t.start_date AND t.end_date
          GROUP BY ALL)
        SELECT wk, SUM(CAST(searched AS INT)) AS searchers, SUM(CAST(searched AND bought AS INT)) AS buyers
        FROM w GROUP BY wk ORDER BY wk""").df()
    searchers, buyers = int(df["searchers"].sum()), int(df["buyers"].sum())
    if not searchers or not buyers:
        return dict(enough=False)
    p0, weekly = buyers / searchers, searchers / len(df)
    plans = [dict(relative_lift=lift, users_per_arm=stats.n_per_arm(p0, lift),
                  weeks=math.ceil(2 * stats.n_per_arm(p0, lift) / weekly)) for lift in lifts]
    return dict(enough=True, baseline_weeks=len(df), weekly_searching_users=weekly,
                baseline_weekly_conversion=p0, plans=plans)


def checkout_by_device(con) -> tuple[pd.DataFrame, dict]:
    df = con.execute("""SELECT device_category, COUNT(*) AS began_checkout,
            SUM(CAST(has_shipping AS INT)) AS added_delivery, SUM(CAST(has_payment AS INT)) AS added_payment,
            SUM(CAST(has_purchase AS INT)) AS purchased
        FROM sessions WHERE has_begin_checkout GROUP BY 1 ORDER BY 2 DESC""").df()
    for col in ("added_delivery", "added_payment", "purchased"):
        df[f"{col}_rate"] = df[col] / df["began_checkout"]
    ci = [stats.wilson(int(x), int(n)) for x, n in zip(df["purchased"], df["began_checkout"])]
    df["completion_lo"], df["completion_hi"] = [c[1] for c in ci], [c[2] for c in ci]
    by = df.set_index("device_category")
    cmp = {}
    if {"mobile", "desktop"} <= set(by.index):
        cmp = stats.two_proportions(int(by.loc["mobile", "purchased"]), int(by.loc["mobile", "began_checkout"]),
                                    int(by.loc["desktop", "purchased"]), int(by.loc["desktop", "began_checkout"]))
        cmp.update(mobile=float(by.loc["mobile", "purchased_rate"]), desktop=float(by.loc["desktop", "purchased_rate"]),
                   mobile_n=int(by.loc["mobile", "began_checkout"]), desktop_n=int(by.loc["desktop", "began_checkout"]))
    return df, cmp


def segments(con) -> pd.DataFrame:
    total = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    rows = []
    for name, rule in SEGMENTS:
        n, x, rev = con.execute(f"""SELECT COUNT(*), SUM(CAST(has_purchase AS INT)), SUM(revenue_usd)
                                    FROM sessions WHERE {rule}""").fetchone()
        p, lo, hi = stats.wilson(_i(x), _i(n))
        rows.append(dict(segment=name, definition=rule, sessions=_i(n), share_of_sessions=_i(n) / total if total else math.nan,
                         purchasing_sessions=_i(x), conversion=p, conversion_lo=lo, conversion_hi=hi,
                         revenue_usd=float(rev or 0), revenue_per_session=float(rev or 0) / _i(n) if n else math.nan))
    return pd.DataFrame(rows)


def daily_kpis(con) -> pd.DataFrame:
    df = con.execute("""
        WITH s AS (
          SELECT session_date AS date, COUNT(*) AS sessions, COUNT(DISTINCT user_pseudo_id) AS users,
                 SUM(CAST(has_purchase AS INT)) AS purchasing_sessions, SUM(revenue_usd) AS revenue_usd,
                 SUM(CAST(has_search AS INT)) AS search_sessions,
                 SUM(CAST(has_view_item AS INT)) AS product_view_sessions,
                 SUM(CAST(has_add_to_cart AS INT)) AS basket_sessions,
                 SUM(CAST(has_begin_checkout AS INT)) AS checkout_sessions,
                 SUM(CAST(has_begin_checkout AND has_purchase AS INT)) AS checkout_completed,
                 SUM(CAST(n_session_start = 0 AS INT)) AS sessions_missing_start
          FROM sessions GROUP BY 1),
        p AS (
          SELECT event_date AS date, COUNT(*) AS purchase_events,
                 SUM(CASE WHEN transaction_id IS NULL OR transaction_id IN ('', '(not set)') THEN 1 ELSE 0 END) AS purchases_missing_txn
          FROM events WHERE event_name = 'purchase' GROUP BY 1)
        SELECT s.*, COALESCE(p.purchase_events, 0) AS purchase_events,
               COALESCE(p.purchases_missing_txn, 0) AS purchases_missing_txn, c.label AS calendar_label
        FROM s LEFT JOIN p USING (date) LEFT JOIN calendar AS c USING (date)
        ORDER BY date""").df()
    df["date"] = pd.to_datetime(df["date"])
    df["conversion"] = df["purchasing_sessions"] / df["sessions"]
    df["checkout_completion"] = df["checkout_completed"] / df["checkout_sessions"].where(df["checkout_sessions"] > 0)
    df["search_share"] = df["search_sessions"] / df["sessions"]
    return df


def windows(con, daily: pd.DataFrame) -> pd.DataFrame:
    """Peak-trading windows against a quiet baseline: conversion, order value and checkout completion."""
    tw = con.execute("SELECT * FROM trading_windows ORDER BY start_date").df()
    d = daily.copy()

    def agg(start, end):
        g = d[(d["date"] >= pd.Timestamp(start)) & (d["date"] <= pd.Timestamp(end))]
        return {k: int(g[k].sum()) for k in ("sessions", "purchasing_sessions", "checkout_sessions", "checkout_completed", "search_sessions")} \
            | dict(days=len(g), revenue=float(g["revenue_usd"].sum()))

    base = tw[tw["role"] == "baseline"].iloc[0]
    b = agg(base["start_date"], base["end_date"])
    rows = []
    for _, w in tw.iterrows():
        a = agg(w["start_date"], w["end_date"])
        conv = stats.two_proportions(a["purchasing_sessions"], a["sessions"], b["purchasing_sessions"], b["sessions"])
        comp = stats.two_proportions(a["checkout_completed"], a["checkout_sessions"], b["checkout_completed"], b["checkout_sessions"])
        rows.append(dict(window=w["window_name"], role=w["role"], start=str(pd.Timestamp(w["start_date"]).date()),
                         end=str(pd.Timestamp(w["end_date"]).date()), days=a["days"],
                         sessions_per_day=a["sessions"] / a["days"] if a["days"] else math.nan,
                         conversion=conv["p1"], conversion_change_pp=conv["diff"], conversion_change_rel=conv["rel"],
                         conversion_p_value=conv["p_value"],
                         revenue_per_purchasing_session=a["revenue"] / a["purchasing_sessions"] if a["purchasing_sessions"] else math.nan,
                         checkout_completion=comp["p1"], checkout_completion_change_pp=comp["diff"],
                         checkout_completion_p_value=comp["p_value"],
                         search_share=a["search_sessions"] / a["sessions"] if a["sessions"] else math.nan))
    return pd.DataFrame(rows)
