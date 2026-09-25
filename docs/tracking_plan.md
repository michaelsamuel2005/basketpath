# Tracking plan

_Generated from `basketpath/plan.py`. Edit the plan there; the audit checks the data against it._

Every field below must be present on at least 95% of its events. `python -m basketpath.build` measures each one and writes the result to `marts/tracking_coverage.csv`.

| Journey stage | Event | Field | Stored in | Why a product team needs it |
|---|---|---|---|---|
| Arrive | `session_start` | `ga_session_id` | event_param | Joins every event to its visit |
| Arrive | `session_start` | `ga_session_number` | event_param | Separates first visits from returning ones |
| Arrive and browse | `page_view` | `page_location` | event_param | Which page the shopper saw |
| Arrive and browse | `page_view` | `page_title` | event_param | A readable page name for reporting |
| Arrive and browse | `page_view` | `ga_session_id` | event_param | Joins the page view to its visit |
| Search | `view_search_results` | `search_term` | event_param | What the shopper was looking for |
| Search | `view_search_results` | `ga_session_id` | event_param | Joins the search to its visit |
| Product | `view_item` | `items` | items | Which product was viewed |
| Basket | `add_to_cart` | `items` | items | What went into the basket |
| Checkout | `begin_checkout` | `items` | items | The basket at the start of checkout |
| Checkout | `add_shipping_info` | `ga_session_id` | event_param | Delivery step reached, joined to its visit |
| Checkout | `add_payment_info` | `ga_session_id` | event_param | Payment step reached, joined to its visit |
| Purchase | `purchase` | `transaction_id` | ecommerce | Counts each order once |
| Purchase | `purchase` | `purchase_revenue_in_usd` | ecommerce | Order value |
| Purchase | `purchase` | `items` | items | What was bought |

Fields stored as `ecommerce` or `items` are checked on the flattened columns (`transaction_id`, `purchase_revenue_usd`, `n_items`); `event_param` fields on the parameter inventory extracted from BigQuery.
