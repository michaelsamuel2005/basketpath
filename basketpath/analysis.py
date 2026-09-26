"""The questions a product team asks of the shopping journey, answered from the session table.

Journey analyses take `src`, the session table to read. The build passes `analysis_sessions`: the days on
which every journey event was tracked, minus any week the data-quality gate held.
"""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from . import stats

JOURNEY_EVENTS = ["view_item", "add_to_cart", "begin_checkout", "add_shipping_info", "add_payment_info",
                  "purchase", "view_search_results"]
# A journey event counts as tracked on a day when its rate per session over the three days to that day is at
# least this share of its typical rate. Three days tolerate a quiet day; a quarter tolerates real seasonality
# while still catching an event that is missing or barely firing.
TRACKED_SHARE = 0.25
STEPS = [("Started a visit", None), ("Viewed products", "f_view_item"), ("Added to basket", "f_add_to_cart"),
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
    ("Viewed products, added nothing", "has_view_item AND NOT has_add_to_cart"),
    ("Abandoned basket", "has_add_to_cart AND NOT has_purchase"),
    ("Abandoned checkout", "has_begin_checkout AND NOT has_purchase"),
    ("New visitors on mobile", "user_type = 'new' AND device_category = 'mobile'"),
    ("Returning previous buyers", "prior_purchaser"),
    ("Paid search visitors", "medium_group = 'paid search'"),
]


def _i(v) -> int:
    return int(v or 0)


def week_range(label: str) -> tuple[dt.date, dt.date]:
    """Monday and Sunday of an ISO week label such as 2021-W04."""
    year, week = label.split("-W")
    monday = dt.date.fromisocalendar(int(year), int(week), 1)
    return monday, monday + dt.timedelta(days=6)


def tracking_timeline(con) -> tuple[pd.DataFrame, dict]:
    """Daily journey-event rates, and the first day from which every journey event was tracked."""
    counts = ", ".join(f"COUNT(*) FILTER (WHERE event_name = '{e}') AS {e}" for e in JOURNEY_EVENTS)
    ev = con.execute(f"""SELECT event_date AS date, {counts},
            COUNT(*) FILTER (WHERE event_name = 'purchase' AND transaction_id IS NOT NULL
                             AND transaction_id NOT IN ('', '(not set)')) AS purchases_with_id,
            COUNT(*) FILTER (WHERE event_name = 'begin_checkout' AND COALESCE(n_items, 0) > 0) AS checkouts_with_items
        FROM events GROUP BY 1""").df()
    sess = con.execute("SELECT session_date AS date, COUNT(*) AS sessions FROM sessions GROUP BY 1").df()
    for d in (ev, sess):
        d["date"] = pd.to_datetime(d["date"])
    df = sess.merge(ev, on="date", how="left").fillna(0).sort_values("date").reset_index(drop=True)
    rate = df[JOURNEY_EVENTS].rolling(3, min_periods=1).sum().div(
        df["sessions"].rolling(3, min_periods=1).sum(), axis=0)
    typical = rate.median()
    ok = rate.ge(TRACKED_SHARE * typical).all(axis=1) & bool((typical > 0).all())
    start = None
    for i in range(len(df) - 1, -1, -1):
        if not ok.iloc[i]:
            break
        start = df["date"].iloc[i]
    detected = start is not None
    if not detected:
        start = df["date"].iloc[0]
    out = df[["date", "sessions"] + JOURNEY_EVENTS + ["purchases_with_id", "checkouts_with_items"]].copy()
    for col in out.columns[1:]:
        out[col] = out[col].astype("int64")
    for e in JOURNEY_EVENTS:
        out[f"{e}_per_100_sessions"] = 100 * out[e] / out["sessions"]
    out["all_journey_events_tracked"] = ok.values
    out["in_journey_window"] = out["date"] >= start
    return out, dict(start=start.date().isoformat(), detected=detected)


def create_analysis_sessions(con, start: str, excluded_weeks=()) -> dict:
    """The sessions journey analyses read: from `start`, without the excluded (held) weeks."""
    conds = [f"session_date >= DATE '{start}'"] + [
        f"NOT (session_date BETWEEN DATE '{a}' AND DATE '{b}')" for a, b in map(week_range, excluded_weeks)]
    con.execute(f"CREATE OR REPLACE TABLE analysis_sessions AS SELECT * FROM sessions WHERE {' AND '.join(conds)}")
    n, first, last = con.execute("SELECT COUNT(*), MIN(session_date), MAX(session_date) FROM analysis_sessions").fetchone()
    return dict(start=str(start), first_day=str(first), last_day=str(last), sessions=_i(n),
                excluded_weeks=list(excluded_weeks))


def overview(con, src: str = "sessions") -> dict:
    first, last, n, users, buyers, revenue, orders, searches, engaged = con.execute(f"""
        SELECT MIN(session_date), MAX(session_date), COUNT(*), COUNT(DISTINCT user_pseudo_id),
               SUM(CAST(has_purchase AS INT)), SUM(revenue_usd), SUM(orders), SUM(CAST(has_search AS INT)),
               SUM(CAST(is_engaged AS INT)) FROM {src}""").fetchone()
    p, lo, hi = stats.wilson(_i(buyers), _i(n))
    mix = lambda col: {str(k): float(v) for k, v in con.execute(
        f"SELECT {col}, COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS s FROM {src} GROUP BY 1 ORDER BY 2 DESC LIMIT 5").fetchall()}
    return dict(first_day=str(first), last_day=str(last),
                events=_i(con.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
                sessions=_i(n), users=_i(users), purchasing_sessions=_i(buyers), orders=_i(orders),
                revenue_usd=float(revenue or 0), conversion=p, conversion_lo=lo, conversion_hi=hi,
                revenue_per_order=float(revenue or 0) / _i(orders) if orders else math.nan,
                search_share=_i(searches) / _i(n) if n else math.nan,
                engaged_share=_i(engaged) / _i(n) if n else math.nan,
                device_mix=mix("device_category"), country_mix=mix("country"), channel_mix=mix("medium_group"))


def order_summary(con, src: str = "sessions") -> dict:
    """How purchase events became orders, and what conversion would be if raw events were counted instead."""
    events, repeats, empty, orders, no_id = con.execute("""SELECT COUNT(*), SUM(CAST(is_repeat AS INT)),
        SUM(CAST(is_empty AS INT)), SUM(CAST(counts_as_order AS INT)),
        SUM(CAST(counts_as_order AND NOT has_valid_id AS INT)) FROM purchases""").fetchone()
    n, raw, ordered = con.execute(f"""SELECT COUNT(*), SUM(CAST(has_purchase_event AS INT)),
        SUM(CAST(has_purchase AS INT)) FROM {src}""").fetchone()
    return dict(purchase_events=_i(events), repeats=_i(repeats), empty=_i(empty), orders=_i(orders),
                orders_without_id=_i(no_id),
                conversion_orders=_i(ordered) / _i(n) if n else math.nan,
                conversion_raw_events=_i(raw) / _i(n) if n else math.nan)


def funnel(con, src: str = "sessions") -> pd.DataFrame:
    """Nested funnel per breakdown, long format for Tableau: one row per group and step."""
    sums = ", ".join(f"SUM(CAST({col} AS INT)) AS s{i}" for i, (_, col) in enumerate(STEPS) if col)
    rows = []
    for breakdown, expr in BREAKDOWNS.items():
        df = con.execute(f"SELECT {expr} AS grp, COUNT(*) AS s0, {sums} FROM {src} GROUP BY 1 ORDER BY 2 DESC").df()
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


def search_vs_intent(con, src: str = "sessions", min_search_sessions: int = 100) -> tuple[dict, pd.DataFrame]:
    """Do searchers convert more because search helps, or because people who search were likelier to buy anyway?"""
    df = con.execute(f"""SELECT {', '.join(STRATA)}, has_search, COUNT(*) AS n,
                         SUM(CAST(has_purchase AS INT)) AS x FROM {src} GROUP BY ALL""").df()
    s1 = df[df["has_search"]].groupby(STRATA)[["n", "x"]].sum().rename(columns={"n": "n_search", "x": "x_search"})
    s0 = df[~df["has_search"]].groupby(STRATA)[["n", "x"]].sum().rename(columns={"n": "n_other", "x": "x_other"})
    strata = s1.join(s0, how="outer").fillna(0).astype("int64").reset_index()
    n1, x1 = int(strata["n_search"].sum()), int(strata["x_search"].sum())
    n0, x0 = int(strata["n_other"].sum()), int(strata["x_other"].sum())
    naive = stats.two_proportions(x1, n1, x0, n0)
    adjusted = stats.standardised_difference(
        strata[["n_search", "x_search", "n_other", "x_other"]].itertuples(index=False, name=None))
    view = con.execute(f"""SELECT
        SUM(CAST(has_search AND has_view_item AS INT)) * 1.0 / NULLIF(SUM(CAST(has_search AS INT)), 0),
        SUM(CAST(NOT has_search AND has_view_item AS INT)) * 1.0 / NULLIF(SUM(CAST(NOT has_search AS INT)), 0)
        FROM {src}""").fetchone()
    explained = (1 - adjusted["diff"] / naive["diff"]
                 if naive["diff"] and not math.isnan(naive["diff"]) else math.nan)
    summary = dict(enough=n1 >= min_search_sessions, search_sessions=n1, other_sessions=n0,
                   search_share=n1 / (n1 + n0) if n1 + n0 else math.nan,
                   naive=naive, adjusted=adjusted, share_explained=explained,
                   product_view_rate_search=float(view[0]) if view[0] is not None else math.nan,
                   product_view_rate_other=float(view[1]) if view[1] is not None else math.nan,
                   controlled_for=STRATA)
    return summary, strata


def follow_up_test(con, src: str = "sessions", lifts=(0.05, 0.10, 0.20)) -> dict:
    """Size the experiment that would settle the search question, from the 'sizing' weeks in trading_windows.

    The unit is the user, so repeat visits by one person need no clustering correction."""
    df = con.execute(f"""
        WITH w AS (
          SELECT date_trunc('week', s.session_date) AS wk, s.user_pseudo_id,
                 bool_or(s.has_search) AS searched, bool_or(s.has_purchase) AS bought
          FROM {src} AS s JOIN trading_windows AS t
            ON t.role = 'sizing' AND s.session_date BETWEEN t.start_date AND t.end_date
          GROUP BY ALL)
        SELECT wk, SUM(CAST(searched AS INT)) AS searchers, SUM(CAST(searched AND bought AS INT)) AS buyers
        FROM w GROUP BY wk ORDER BY wk""").df()
    searchers, buyers = int(df["searchers"].sum()), int(df["buyers"].sum())
    if not searchers or not buyers:
        return dict(enough=False)
    p0, weekly = buyers / searchers, searchers / len(df)
    plans = [dict(relative_lift=lift, users_per_arm=stats.n_per_arm(p0, lift),
                  weeks=math.ceil(2 * stats.n_per_arm(p0, lift) / weekly)) for lift in lifts]
    return dict(enough=True, sizing_weeks=len(df), weekly_searching_users=weekly,
                baseline_weekly_conversion=p0, plans=plans)


def checkout_by_device(con, src: str = "sessions") -> tuple[pd.DataFrame, dict]:
    df = con.execute(f"""SELECT device_category, COUNT(*) AS began_checkout,
            SUM(CAST(has_shipping AS INT)) AS added_delivery, SUM(CAST(has_payment AS INT)) AS added_payment,
            SUM(CAST(has_purchase AS INT)) AS purchased
        FROM {src} WHERE has_begin_checkout GROUP BY 1 ORDER BY 2 DESC""").df()
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


def segments(con, src: str = "sessions") -> pd.DataFrame:
    total = con.execute(f"SELECT COUNT(*) FROM {src}").fetchone()[0]
    rows = []
    for name, rule in SEGMENTS:
        n, x, rev = con.execute(f"""SELECT COUNT(*), SUM(CAST(has_purchase AS INT)), SUM(revenue_usd)
                                    FROM {src} WHERE {rule}""").fetchone()
        p, lo, hi = stats.wilson(_i(x), _i(n))
        rows.append(dict(segment=name, definition=rule, sessions=_i(n), share_of_sessions=_i(n) / total if total else math.nan,
                         purchasing_sessions=_i(x), conversion=p, conversion_lo=lo, conversion_hi=hi,
                         revenue_usd=float(rev or 0), revenue_per_session=float(rev or 0) / _i(n) if n else math.nan))
    return pd.DataFrame(rows)


def daily_kpis(con, journey_start: str | None = None) -> pd.DataFrame:
    df = con.execute("""
        WITH s AS (
          SELECT session_date AS date, COUNT(*) AS sessions, COUNT(DISTINCT user_pseudo_id) AS users,
                 SUM(CAST(has_purchase AS INT)) AS purchasing_sessions, SUM(orders) AS orders,
                 SUM(revenue_usd) AS revenue_usd,
                 SUM(CAST(has_search AS INT)) AS search_sessions,
                 SUM(CAST(has_view_item AS INT)) AS product_view_sessions,
                 SUM(CAST(has_add_to_cart AS INT)) AS basket_sessions,
                 SUM(CAST(has_begin_checkout AS INT)) AS checkout_sessions,
                 SUM(CAST(has_begin_checkout AND has_purchase AS INT)) AS checkout_completed,
                 SUM(CAST(n_session_start = 0 AS INT)) AS sessions_missing_start
          FROM sessions GROUP BY 1),
        p AS (
          SELECT event_date AS date, COUNT(*) AS purchase_events,
                 SUM(CAST(NOT has_valid_id AS INT)) AS purchases_missing_id,
                 SUM(CAST(is_empty AS INT)) AS empty_purchase_events,
                 SUM(CAST(is_repeat AS INT)) AS repeat_purchase_events,
                 SUM(CAST(counts_as_order AND NOT has_valid_id AS INT)) AS orders_without_id
          FROM purchases GROUP BY 1)
        SELECT s.*, COALESCE(p.purchase_events, 0) AS purchase_events,
               COALESCE(p.purchases_missing_id, 0) AS purchases_missing_id,
               COALESCE(p.empty_purchase_events, 0) AS empty_purchase_events,
               COALESCE(p.repeat_purchase_events, 0) AS repeat_purchase_events,
               COALESCE(p.orders_without_id, 0) AS orders_without_id, c.label AS calendar_label
        FROM s LEFT JOIN p USING (date) LEFT JOIN calendar AS c USING (date)
        ORDER BY date""").df()
    df["date"] = pd.to_datetime(df["date"])
    df["conversion"] = df["purchasing_sessions"] / df["sessions"]
    df["checkout_completion"] = df["checkout_completed"] / df["checkout_sessions"].where(df["checkout_sessions"] > 0)
    df["search_share"] = df["search_sessions"] / df["sessions"]
    df["journey_tracked"] = df["date"] >= pd.Timestamp(journey_start) if journey_start else True
    return df


def windows(con, daily: pd.DataFrame, excluded_weeks=()) -> pd.DataFrame:
    """Peak-trading windows against a quiet baseline, leaving out any week the gate held."""
    held = set()
    for a, b in map(week_range, excluded_weeks):
        held |= set(pd.date_range(a, b))
    tw = con.execute("SELECT * FROM trading_windows WHERE role IN ('baseline', 'event') ORDER BY start_date").df()

    def agg(start, end):
        span = daily[(daily["date"] >= pd.Timestamp(start)) & (daily["date"] <= pd.Timestamp(end))]
        g = span[~span["date"].isin(held)]
        return {k: int(g[k].sum()) for k in ("sessions", "purchasing_sessions", "orders", "checkout_sessions",
                                            "checkout_completed", "search_sessions")} \
            | dict(days=len(g), days_excluded=len(span) - len(g), revenue=float(g["revenue_usd"].sum()))

    base = tw[tw["role"] == "baseline"].iloc[0]
    b = agg(base["start_date"], base["end_date"])
    rows = []
    for _, w in tw.iterrows():
        a = agg(w["start_date"], w["end_date"])
        conv = stats.two_proportions(a["purchasing_sessions"], a["sessions"], b["purchasing_sessions"], b["sessions"])
        comp = stats.two_proportions(a["checkout_completed"], a["checkout_sessions"], b["checkout_completed"], b["checkout_sessions"])
        rows.append(dict(window=w["window_name"], role=w["role"], start=str(pd.Timestamp(w["start_date"]).date()),
                         end=str(pd.Timestamp(w["end_date"]).date()), days=a["days"], days_excluded=a["days_excluded"],
                         sessions_per_day=a["sessions"] / a["days"] if a["days"] else math.nan,
                         conversion=conv["p1"], conversion_change_pp=conv["diff"], conversion_change_rel=conv["rel"],
                         conversion_p_value=conv["p_value"],
                         revenue_per_order=a["revenue"] / a["orders"] if a["orders"] else math.nan,
                         checkout_completion=comp["p1"], checkout_completion_change_pp=comp["diff"],
                         checkout_completion_p_value=comp["p_value"],
                         search_share=a["search_sessions"] / a["sessions"] if a["sessions"] else math.nan))
    return pd.DataFrame(rows)
