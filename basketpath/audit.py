"""Tracking audit: can these numbers be trusted, and what should engineering fix first?

Each check states the question it answers, who owns the fix, how severe a failure is, and the
threshold it is judged against. The audit runs before any analysis is reported.
"""
from __future__ import annotations

import pandas as pd

from .plan import COVERAGE_TARGET, PLAN
from .schema import MISSING_TXN, PLACEHOLDERS

_MISSING = "(" + ", ".join(f"'{v}'" for v in MISSING_TXN) + ")"
_PLACE = "(" + ", ".join(f"'{v}'" for v in PLACEHOLDERS) + ")"
_ECOM = "('view_item', 'add_to_cart', 'begin_checkout', 'purchase')"
_PURCHASES = "SELECT COUNT(*) FROM events WHERE event_name = 'purchase'"
_REVENUE_JOIN = """
SELECT p.rev, i.item_rev
FROM (SELECT user_pseudo_id, ga_session_id, event_ts, purchase_revenue_usd AS rev
      FROM events WHERE event_name = 'purchase' AND purchase_revenue_usd IS NOT NULL) AS p
JOIN (SELECT user_pseudo_id, ga_session_id, event_ts,
             SUM(item_revenue_usd) AS item_rev, COUNT(item_revenue_usd) AS n_known
      FROM items WHERE event_name = 'purchase' GROUP BY ALL) AS i
USING (user_pseudo_id, ga_session_id, event_ts)
WHERE i.n_known > 0
"""

# (check, question, owner, severity, threshold or None for information only, numerator SQL, denominator SQL)
CHECKS = [
    ("events_missing_session_id", "Can every event be joined to a visit?", "engineering", "high", 0.005,
     "SELECT COUNT(*) FROM events WHERE ga_session_id IS NULL", "SELECT COUNT(*) FROM events"),
    ("sessions_without_session_start", "Does every visit record its start?", "engineering", "high", 0.02,
     "SELECT COUNT(*) FROM sessions WHERE n_session_start = 0", "SELECT COUNT(*) FROM sessions"),
    ("sessions_with_repeated_session_start", "Is any visit's start recorded twice?", "engineering", "medium", 0.01,
     "SELECT COUNT(*) FROM sessions WHERE n_session_start > 1", "SELECT COUNT(*) FROM sessions"),
    ("purchases_missing_transaction_id", "Can every order be counted once?", "engineering", "high", 0.005,
     f"{_PURCHASES} AND (transaction_id IS NULL OR transaction_id IN {_MISSING})", _PURCHASES),
    ("duplicate_purchase_events", "Is any order sent more than once by the same user?", "engineering", "high", 0.002,
     "SELECT COUNT(*) FROM purchases WHERE is_repeat", _PURCHASES),
    ("purchases_without_revenue", "Does every order carry its value?", "engineering", "high", 0.005,
     f"{_PURCHASES} AND (purchase_revenue_usd IS NULL OR purchase_revenue_usd <= 0)", _PURCHASES),
    ("ecommerce_events_without_items", "Do product, basket and order events say which products?", "engineering",
     "medium", 0.01, f"SELECT COUNT(*) FROM events WHERE event_name IN {_ECOM} AND COALESCE(n_items, 0) = 0",
     f"SELECT COUNT(*) FROM events WHERE event_name IN {_ECOM}"),
    ("add_to_cart_with_many_products", "Does an add-to-basket event list what was added, not a whole page of products?",
     "engineering", "medium", 0.05,
     "SELECT COUNT(*) FROM events WHERE event_name = 'add_to_cart' AND n_items > 5",
     "SELECT COUNT(*) FROM events WHERE event_name = 'add_to_cart'"),
    ("purchase_sessions_without_checkout", "Does every buyer pass through checkout as tracked?",
     "product and engineering", "medium", 0.02,
     "SELECT COUNT(*) FROM sessions WHERE has_purchase AND NOT has_begin_checkout",
     "SELECT COUNT(*) FROM sessions WHERE has_purchase"),
    ("searches_without_term", "Does every search record what was searched for?", "engineering", "medium", 0.01,
     "SELECT COUNT(*) FROM events WHERE event_name = 'view_search_results' AND (search_term IS NULL OR search_term = '')",
     "SELECT COUNT(*) FROM events WHERE event_name = 'view_search_results'"),
    ("search_terms_obfuscated", "How many search terms did Google's obfuscation replace?",
     "dataset, not a tracking fault", "info", None,
     f"SELECT COUNT(*) FROM events WHERE event_name = 'view_search_results' AND search_term IN {_PLACE}",
     "SELECT COUNT(*) FROM events WHERE event_name = 'view_search_results'"),
    ("page_views_without_location", "Does every page view say which page?", "engineering", "medium", 0.005,
     "SELECT COUNT(*) FROM events WHERE event_name = 'page_view' AND (page_location IS NULL OR page_location = '')",
     "SELECT COUNT(*) FROM events WHERE event_name = 'page_view'"),
    # Information only: delivery, tax and discounts can legitimately separate order value from item value.
    # revenue_gap() reports the direction of the gaps, which is what tells a fault from a charge.
    ("purchase_revenue_mismatch", "Does each order's value match the sum of its items (within 1%)?",
     "check the direction of the gaps first", "info", None,
     f"SELECT COALESCE(SUM(CASE WHEN abs(rev - item_rev) > 0.01 * greatest(abs(item_rev), 0.01) THEN 1 ELSE 0 END), 0) FROM ({_REVENUE_JOIN})",
     f"SELECT COUNT(*) FROM ({_REVENUE_JOIN})"),
]
_ECOMMERCE_FIELDS = {
    ("purchase", "transaction_id"):
        f"{_PURCHASES} AND transaction_id IS NOT NULL AND transaction_id NOT IN {_MISSING}",
    ("purchase", "purchase_revenue_in_usd"): f"{_PURCHASES} AND purchase_revenue_usd > 0",
}


def _status(num: int, den: int, threshold) -> str:
    if den == 0:
        return "n/a"
    if threshold is None:
        return "info"
    return "fail" if num / den > threshold else "pass"


def coverage(con) -> pd.DataFrame:
    """How often each tracking-plan field is actually present on its event."""
    totals = dict(con.execute("SELECT event_name, COUNT(*) FROM events GROUP BY 1").fetchall())
    inventory = {(e, k): n for e, k, n in con.execute(
        "SELECT event_name, param_key, SUM(n_nonnull) FROM param_inventory GROUP BY 1, 2").fetchall()}
    rows = []
    for event, stage, field, source, _why in PLAN:
        total = int(totals.get(event, 0))
        if source == "event_param":
            ok = int(inventory.get((event, field), 0))
        elif source == "items":
            ok = int(con.execute(f"SELECT COUNT(*) FROM events WHERE event_name = '{event}' AND COALESCE(n_items, 0) > 0").fetchone()[0])
        else:
            ok = int(con.execute(_ECOMMERCE_FIELDS[(event, field)]).fetchone()[0])
        share = ok / total if total else float("nan")
        status = "not tracked" if total == 0 else ("pass" if share >= COVERAGE_TARGET else "fail")
        rows.append(dict(stage=stage, event=event, field=field, source=source, n_ok=ok, n_events=total,
                         coverage=share, target=COVERAGE_TARGET, status=status))
    return pd.DataFrame(rows)


def revenue_gap(con) -> dict:
    """How order values differ from their items: gaps all one way suggest charges, gaps both ways suggest noise."""
    gap = "rev - item_rev"
    tol = "0.01 * greatest(abs(item_rev), 0.01)"
    match, above, below, median_gap = con.execute(f"""SELECT
        COUNT(*) FILTER (WHERE abs({gap}) <= {tol}), COUNT(*) FILTER (WHERE {gap} > {tol}),
        COUNT(*) FILTER (WHERE -({gap}) > {tol}),
        MEDIAN(abs({gap}) / NULLIF(abs(item_rev), 0)) FILTER (WHERE abs({gap}) > {tol})
        FROM ({_REVENUE_JOIN})""").fetchone()
    return dict(match=int(match or 0), above=int(above or 0), below=int(below or 0),
                median_gap=float(median_gap) if median_gap is not None else float("nan"))


def run(con) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for check, question, owner, severity, threshold, num_sql, den_sql in CHECKS:
        num = int(con.execute(num_sql).fetchone()[0] or 0)
        den = int(con.execute(den_sql).fetchone()[0] or 0)
        rows.append(dict(check=check, question=question, owner=owner, severity=severity,
                         numerator=num, denominator=den, rate=num / den if den else float("nan"),
                         threshold=threshold, status=_status(num, den, threshold)))
    cov = coverage(con)
    below = int(cov["status"].isin(["fail", "not tracked"]).sum())
    rows.append(dict(check="tracking_plan_fields_below_target",
                     question=f"Is every tracking-plan field on at least {COVERAGE_TARGET:.0%} of its events?",
                     owner="engineering", severity="medium", numerator=below, denominator=len(cov),
                     rate=below / len(cov), threshold=0.0, status="fail" if below else "pass"))
    return pd.DataFrame(rows), cov
