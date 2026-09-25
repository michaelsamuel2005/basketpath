"""The tracking plan: what each step of the shopping journey must send, and why.

One source of truth. The audit measures the data against it, and docs/tracking_plan.md
is generated from it, so the documentation cannot drift from what is checked.
"""
from __future__ import annotations

import pathlib

COVERAGE_TARGET = 0.95

# (event, journey stage, field, where GA4 stores it, why a product team needs it)
PLAN: list[tuple[str, str, str, str, str]] = [
    ("session_start", "Arrive", "ga_session_id", "event_param", "Joins every event to its visit"),
    ("session_start", "Arrive", "ga_session_number", "event_param", "Separates first visits from returning ones"),
    ("page_view", "Arrive and browse", "page_location", "event_param", "Which page the shopper saw"),
    ("page_view", "Arrive and browse", "page_title", "event_param", "A readable page name for reporting"),
    ("page_view", "Arrive and browse", "ga_session_id", "event_param", "Joins the page view to its visit"),
    ("view_search_results", "Search", "search_term", "event_param", "What the shopper was looking for"),
    ("view_search_results", "Search", "ga_session_id", "event_param", "Joins the search to its visit"),
    ("view_item", "Product", "items", "items", "Which product was viewed"),
    ("add_to_cart", "Basket", "items", "items", "What went into the basket"),
    ("begin_checkout", "Checkout", "items", "items", "The basket at the start of checkout"),
    ("add_shipping_info", "Checkout", "ga_session_id", "event_param", "Delivery step reached, joined to its visit"),
    ("add_payment_info", "Checkout", "ga_session_id", "event_param", "Payment step reached, joined to its visit"),
    ("purchase", "Purchase", "transaction_id", "ecommerce", "Counts each order once"),
    ("purchase", "Purchase", "purchase_revenue_in_usd", "ecommerce", "Order value"),
    ("purchase", "Purchase", "items", "items", "What was bought"),
]


def render_markdown() -> str:
    lines = [
        "# Tracking plan",
        "",
        "_Generated from `basketpath/plan.py`. Edit the plan there; the audit checks the data against it._",
        "",
        f"Every field below must be present on at least {COVERAGE_TARGET:.0%} of its events. "
        "`python -m basketpath.build` measures each one and writes the result to `marts/tracking_coverage.csv`.",
        "",
        "| Journey stage | Event | Field | Stored in | Why a product team needs it |",
        "|---|---|---|---|---|",
    ]
    for event, stage, field, source, why in PLAN:
        lines.append(f"| {stage} | `{event}` | `{field}` | {source} | {why} |")
    lines += ["", "Fields stored as `ecommerce` or `items` are checked on the flattened columns "
              "(`transaction_id`, `purchase_revenue_usd`, `n_items`); `event_param` fields on the "
              "parameter inventory extracted from BigQuery.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    out = pathlib.Path("docs/tracking_plan.md")
    out.write_text(render_markdown())
    print(f"wrote {out}")
