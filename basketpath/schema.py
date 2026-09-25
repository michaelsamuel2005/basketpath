"""The contract between extraction and analysis.

`extract` must produce exactly these columns from BigQuery, and the generated test data
must match them too, so the tests exercise the same shape the real data has.
"""
from __future__ import annotations

EVENT_COLUMNS: dict[str, str] = {
    "event_date": "date", "event_ts": "timestamp", "event_name": "string",
    "user_pseudo_id": "string", "ga_session_id": "int", "ga_session_number": "int",
    "page_location": "string", "page_title": "string", "search_term": "string",
    "engagement_time_msec": "int", "session_engaged": "string",
    "device_category": "string", "country": "string",
    "first_medium": "string", "first_source": "string",
    "transaction_id": "string", "purchase_revenue_usd": "float",
    "n_items": "int", "item_quantity": "int",
}
ITEM_COLUMNS: dict[str, str] = {
    "event_date": "date", "event_ts": "timestamp", "event_name": "string",
    "user_pseudo_id": "string", "ga_session_id": "int",
    "item_id": "string", "item_name": "string", "item_category": "string",
    "price_usd": "float", "quantity": "int", "item_revenue_usd": "float",
}
INVENTORY_COLUMNS: dict[str, str] = {
    "event_name": "string", "param_key": "string", "n_present": "int", "n_nonnull": "int",
}
# Values that mean "no transaction ID" in a GA4 export.
MISSING_TXN = ("", "(not set)")
# Values Google's obfuscation writes in place of real ones. Reported, never treated as tracking faults.
PLACEHOLDERS = ("<Other>", "(not set)", "(data deleted)")


def check_columns(columns, contract: dict, what: str) -> None:
    missing = [c for c in contract if c not in list(columns)]
    if missing:
        raise ValueError(f"{what} is missing columns {missing}; expected {list(contract)}")
