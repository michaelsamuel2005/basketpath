"""Local analytics store: DuckDB views over the extracted Parquet, the order rule, and the session table."""
from __future__ import annotations

import pathlib

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "data" / "reference"

# How purchase events become orders (docs/metrics.md explains why):
#   - an event with a valid transaction ID counts once per user; later events with the same ID and user are
#     repeats, typically a confirmation page firing twice;
#   - an event without a usable ID counts if it carries revenue: it is probably a real order, but it cannot be
#     checked for duplicates, so it is flagged;
#   - an event with no usable ID and no revenue is empty, and is not an order.
PURCHASES_SQL = """
CREATE OR REPLACE TABLE purchases AS
WITH p AS (
  SELECT user_pseudo_id, ga_session_id, event_ts, event_date, transaction_id, purchase_revenue_usd,
         transaction_id IS NOT NULL AND transaction_id NOT IN ('', '(not set)') AS has_valid_id
  FROM events WHERE event_name = 'purchase'),
r AS (
  SELECT *,
         has_valid_id AND row_number() OVER (
             PARTITION BY transaction_id, user_pseudo_id
             ORDER BY event_ts, purchase_revenue_usd DESC NULLS LAST, ga_session_id) > 1 AS is_repeat,
         NOT has_valid_id AND COALESCE(purchase_revenue_usd, 0) <= 0 AS is_empty
  FROM p)
SELECT *, NOT is_repeat AND NOT is_empty AS counts_as_order FROM r
"""

SESSIONS_SQL = """
CREATE OR REPLACE TABLE sessions AS
WITH s AS (
  SELECT
    user_pseudo_id, ga_session_id,
    MIN(event_ts)                                                   AS start_ts,
    arg_min(event_date, event_ts)                                   AS session_date,
    arg_min(device_category, event_ts)                              AS device_category,
    arg_min(country, event_ts)                                      AS country,
    arg_min(first_medium, event_ts)                                 AS first_medium,
    MIN(ga_session_number)                                          AS ga_session_number,
    COUNT(*) FILTER (WHERE event_name = 'session_start')            AS n_session_start,
    COUNT(*) FILTER (WHERE event_name = 'page_view')                AS page_views,
    COUNT(*) FILTER (WHERE event_name = 'view_search_results')      AS searches,
    bool_or(session_engaged = '1')                                  AS engaged,
    bool_or(event_name = 'view_item')                               AS has_view_item,
    bool_or(event_name = 'add_to_cart')                             AS has_add_to_cart,
    bool_or(event_name = 'begin_checkout')                          AS has_begin_checkout,
    bool_or(event_name = 'add_shipping_info')                       AS has_shipping,
    bool_or(event_name = 'add_payment_info')                        AS has_payment,
    bool_or(event_name = 'purchase')                                AS has_purchase_event
  FROM events
  WHERE ga_session_id IS NOT NULL
  GROUP BY user_pseudo_id, ga_session_id),
o AS (
  SELECT user_pseudo_id, ga_session_id,
         COUNT(*) FILTER (WHERE counts_as_order)                                  AS orders,
         COALESCE(SUM(purchase_revenue_usd) FILTER (WHERE counts_as_order), 0)   AS revenue_usd
  FROM purchases WHERE ga_session_id IS NOT NULL
  GROUP BY user_pseudo_id, ga_session_id),
j AS (
  SELECT s.*, COALESCE(o.orders, 0) AS orders, COALESCE(o.revenue_usd, 0) AS revenue_usd,
         COALESCE(o.orders, 0) > 0 AS has_purchase
  FROM s LEFT JOIN o USING (user_pseudo_id, ga_session_id))
SELECT
  *,
  searches > 0 AS has_search,
  COALESCE(engaged, FALSE) AS is_engaged,
  CASE WHEN ga_session_number IS NULL THEN 'unknown'
       WHEN ga_session_number = 1 THEN 'new' ELSE 'returning' END AS user_type,
  CASE first_medium WHEN 'organic' THEN 'organic search' WHEN 'cpc' THEN 'paid search'
       WHEN 'referral' THEN 'referral' WHEN '(none)' THEN 'direct' ELSE 'other or unknown' END AS medium_group,
  -- Funnel steps are nested: each step counts only sessions that also reached every earlier step.
  has_view_item                                                     AS f_view_item,
  has_view_item AND has_add_to_cart                                 AS f_add_to_cart,
  has_view_item AND has_add_to_cart AND has_begin_checkout          AS f_checkout,
  has_view_item AND has_add_to_cart AND has_begin_checkout AND has_shipping AS f_shipping,
  has_view_item AND has_add_to_cart AND has_begin_checkout AND has_shipping AND has_payment AS f_payment,
  has_view_item AND has_add_to_cart AND has_begin_checkout AND has_shipping AND has_payment AND has_purchase AS f_purchase,
  COALESCE(MAX(CAST(has_purchase AS INT)) OVER (
      PARTITION BY user_pseudo_id ORDER BY start_ts
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) = 1     AS prior_purchaser
FROM j
"""


def build(con) -> None:
    """Create the order and session tables from an `events` relation already defined on `con`."""
    con.execute(PURCHASES_SQL)
    con.execute(SESSIONS_SQL)


def connect(raw_dir, reference_dir=REFERENCE) -> duckdb.DuckDBPyConnection:
    raw = pathlib.Path(raw_dir)
    for sub in ("events", "items"):
        if not list((raw / sub).glob("*.parquet")):
            raise FileNotFoundError(
                f"No Parquet files in {raw / sub}. Extract the data first: see 'Run it on the real data' in README.md")
    con = duckdb.connect()
    con.execute(f"CREATE VIEW events AS SELECT * FROM read_parquet('{(raw / 'events').as_posix()}/*.parquet', union_by_name = true)")
    con.execute(f"CREATE VIEW items AS SELECT * FROM read_parquet('{(raw / 'items').as_posix()}/*.parquet', union_by_name = true)")
    con.execute(f"CREATE VIEW param_inventory AS SELECT * FROM read_parquet('{(raw / 'param_inventory.parquet').as_posix()}')")
    ref = pathlib.Path(reference_dir)
    con.execute(f"CREATE TABLE calendar AS SELECT CAST(date AS DATE) AS date, label FROM read_csv('{(ref / 'trading_calendar.csv').as_posix()}', header = true)")
    con.execute(f"CREATE TABLE trading_windows AS SELECT window_name, CAST(start_date AS DATE) AS start_date, CAST(end_date AS DATE) AS end_date, role FROM read_csv('{(ref / 'trading_windows.csv').as_posix()}', header = true)")
    build(con)
    return con
