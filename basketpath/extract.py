"""Pull Google's public GA4 sample out of BigQuery, one day at a time, into local Parquet.

Runs free in a BigQuery sandbox (no billing account). Everything downstream reads the
Parquet files, so BigQuery is touched once.

    pip install -e ".[bigquery]"
    gcloud auth application-default login
    python -m basketpath.extract --project YOUR_PROJECT_ID --check   # one day, schema check
    python -m basketpath.extract --project YOUR_PROJECT_ID           # all 92 days
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib

from .schema import EVENT_COLUMNS, INVENTORY_COLUMNS, ITEM_COLUMNS, check_columns

TABLE = "bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*"
FIRST_DAY, LAST_DAY = dt.date(2020, 11, 1), dt.date(2021, 1, 31)
CHECK_DAY = dt.date(2020, 12, 1)


def _param(key: str, kind: str = "string") -> str:
    """One event parameter as a column. GA4 stores a value in whichever typed slot it chose."""
    if kind == "int":
        expr = "COALESCE(value.int_value, SAFE_CAST(value.string_value AS INT64))"
    else:
        expr = "COALESCE(value.string_value, CAST(value.int_value AS STRING))"
    return f"(SELECT {expr} FROM UNNEST(event_params) WHERE key = '{key}')"


EVENTS_SQL = f"""
SELECT
  PARSE_DATE('%Y%m%d', event_date)       AS event_date,
  TIMESTAMP_MICROS(event_timestamp)      AS event_ts,
  event_name,
  user_pseudo_id,
  {_param('ga_session_id', 'int')}       AS ga_session_id,
  {_param('ga_session_number', 'int')}   AS ga_session_number,
  {_param('page_location')}              AS page_location,
  {_param('page_title')}                 AS page_title,
  {_param('search_term')}                AS search_term,
  {_param('engagement_time_msec', 'int')} AS engagement_time_msec,
  {_param('session_engaged')}            AS session_engaged,
  device.category                        AS device_category,
  geo.country                            AS country,
  traffic_source.medium                  AS first_medium,
  traffic_source.source                  AS first_source,
  ecommerce.transaction_id               AS transaction_id,
  ecommerce.purchase_revenue_in_usd      AS purchase_revenue_usd,
  ARRAY_LENGTH(items)                    AS n_items,
  ecommerce.total_item_quantity          AS item_quantity
FROM `{TABLE}`
WHERE _TABLE_SUFFIX = @day
"""

ITEMS_SQL = f"""
SELECT
  PARSE_DATE('%Y%m%d', event_date)       AS event_date,
  TIMESTAMP_MICROS(event_timestamp)      AS event_ts,
  event_name,
  user_pseudo_id,
  {_param('ga_session_id', 'int')}       AS ga_session_id,
  i.item_id, i.item_name, i.item_category,
  i.price_in_usd                         AS price_usd,
  i.quantity,
  i.item_revenue_in_usd                  AS item_revenue_usd
FROM `{TABLE}`, UNNEST(items) AS i
WHERE _TABLE_SUFFIX = @day
  AND event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
"""

# Which parameters each event actually carries: the evidence for the tracking-plan audit.
INVENTORY_SQL = f"""
SELECT
  event_name,
  ep.key                                   AS param_key,
  COUNT(*)                                 AS n_present,
  COUNTIF(ep.value.string_value IS NOT NULL OR ep.value.int_value IS NOT NULL
          OR ep.value.double_value IS NOT NULL OR ep.value.float_value IS NOT NULL) AS n_nonnull
FROM `{TABLE}`, UNNEST(event_params) AS ep
WHERE _TABLE_SUFFIX BETWEEN @start AND @end
GROUP BY 1, 2
"""


def days(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(n) for n in range((end - start).days + 1)]


def run(project: str, start: dt.date, end: dt.date, out: pathlib.Path, check: bool = False) -> None:
    from google.cloud import bigquery  # optional dependency: pip install -e ".[bigquery]"

    client = bigquery.Client(project=project)

    def query(sql, **params):
        cfg = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter(k, "STRING", v) for k, v in params.items()])
        return client.query(sql, job_config=cfg).to_dataframe()

    if check:
        start = end = CHECK_DAY
    dry = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False, query_parameters=[
        bigquery.ScalarQueryParameter("day", "STRING", start.strftime("%Y%m%d"))])
    gb = client.query(EVENTS_SQL, job_config=dry).total_bytes_processed / 1e9
    print(f"one day of events scans about {gb:.2f} GB (the sandbox allows 1 TB a month)")

    for sub in ("events", "items"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    for day in days(start, end):
        suffix = day.strftime("%Y%m%d")
        ev = query(EVENTS_SQL, day=suffix)
        check_columns(ev.columns, EVENT_COLUMNS, f"events {suffix}")
        it = query(ITEMS_SQL, day=suffix)
        check_columns(it.columns, ITEM_COLUMNS, f"items {suffix}")
        ev[list(EVENT_COLUMNS)].to_parquet(out / "events" / f"events_{suffix}.parquet", index=False)
        it[list(ITEM_COLUMNS)].to_parquet(out / "items" / f"items_{suffix}.parquet", index=False)
        print(f"{suffix}: {len(ev):,} events, {len(it):,} item rows")
    inv = query(INVENTORY_SQL, start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))
    check_columns(inv.columns, INVENTORY_COLUMNS, "parameter inventory")
    inv.to_parquet(out / "param_inventory.parquet", index=False)
    print(f"parameter inventory: {len(inv)} (event, parameter) pairs -> {out}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="your Google Cloud project ID (a free sandbox works)")
    ap.add_argument("--start", type=dt.date.fromisoformat, default=FIRST_DAY)
    ap.add_argument("--end", type=dt.date.fromisoformat, default=LAST_DAY)
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/raw"))
    ap.add_argument("--check", action="store_true", help=f"extract {CHECK_DAY} only and validate the schema")
    a = ap.parse_args(argv)
    run(a.project, a.start, a.end, a.out / "check" if a.check else a.out, check=a.check)


if __name__ == "__main__":
    main()
