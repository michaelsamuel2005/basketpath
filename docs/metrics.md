# Metric definitions

One definition per metric, matching the code. Session logic is in `SESSIONS_SQL` in
[`basketpath/db.py`](../basketpath/db.py); everything else is in [`basketpath/analysis.py`](../basketpath/analysis.py).

| Metric | Definition | Why this definition |
|---|---|---|
| Session | All events sharing `user_pseudo_id` and `ga_session_id`. | GA4's own visit key. Events without a session ID cannot be placed in a visit; the audit counts them. |
| Session conversion | Sessions with at least one `purchase` event, divided by sessions. | Session level matches how a journey is experienced. Tests are sized per user (see below). |
| Funnel steps | Viewed a product (`view_item`), added to basket (`add_to_cart`), began checkout (`begin_checkout`), added delivery details (`add_shipping_info`), added payment details (`add_payment_info`), purchased (`purchase`). | The GA4 recommended e-commerce events. |
| Nested funnel | A session counts at a step only if it also reached every earlier step, in any order, in the same session. | Keeps the funnel monotone. A basket add from a listing page without a product view is excluded from later steps; the "Abandoned basket" segment counts it regardless. |
| Search session | At least one `view_search_results` event. | |
| Checkout completion | Sessions that began checkout and purchased, divided by sessions that began checkout. | |
| Revenue per purchasing session | Purchase revenue (USD), divided by sessions with a purchase. | Per session, not per order, because transaction IDs are not reliable enough in this export to count orders (see the audit). |
| Visitor type | New if `ga_session_number` = 1, otherwise returning. | |
| Channel | The user's first-acquisition medium (`traffic_source.medium`), grouped. | In the GA4 export this field records how the user was **first** acquired, not the source of this visit. |
| Previous buyer | The user purchased in an earlier session within the data window. | Purchases before 1 November 2020 are invisible, so this undercounts early in the window. |
| Engaged session | Any event in the session carries `session_engaged = '1'`. | GA4's engagement flag. |

## Statistics

- **Intervals for rates:** 95% Wilson score intervals.
- **Differences between two rates:** unpooled 95% interval with a pooled two-proportion z-test.
- **Like-for-like comparison (search):** the non-search sessions are re-weighted to the search sessions' mix across device × visitor type × channel × previous buyer (direct standardisation). Strata without both groups are dropped, and the share of search sessions they held is reported as lost coverage.
- **Experiment sizing:** users, not sessions, are the unit, so repeat visits by one person do not understate the variance. Users per arm come from the standard two-proportion formula at 5% significance and 80% power, using conversion measured in the baseline weeks.
