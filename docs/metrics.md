# Metric definitions

One definition per metric, matching the code. The order rule and session logic are in
[`basketpath/db.py`](../basketpath/db.py); everything else is in [`basketpath/analysis.py`](../basketpath/analysis.py)
and [`basketpath/report.py`](../basketpath/report.py).

## Orders

The export's purchase events are not orders. Diagnosing them on the real data found three kinds:

| Purchase event | Rule | Why |
|---|---|---|
| Valid transaction ID, first time that user sends it | **Order** | The normal case. |
| Valid transaction ID the same user already sent | **Removed** as a repeat | Almost all repeats sit in the same session, in the same minute, with the same value: a confirmation page firing twice. |
| No usable ID (`NULL`, empty or `(not set)`) but with revenue | **Order**, flagged | Their values match valid orders, so they look like real orders that lost their ID. They cannot be checked for duplicates. |
| No usable ID and no revenue | **Not an order** ("empty") | Carries nothing an order would; after mid-November these are the only events missing IDs. |

The same ID from a different user is kept as a separate order: the few cases found look like IDs reused by Google's
obfuscation rather than repeats.

## Sessions and the journey

| Metric | Definition | Why this definition |
|---|---|---|
| Session | All events sharing `user_pseudo_id` and `ga_session_id`. | GA4's own visit key. |
| Session conversion | Sessions with at least one order, divided by sessions. | Session level matches how a journey is experienced. Tests are sized per user (below). |
| Funnel steps | Viewed products (`view_item`), added to basket (`add_to_cart`), began checkout (`begin_checkout`), added delivery details (`add_shipping_info`), added payment details (`add_payment_info`), purchased (an order). | GA4's recommended e-commerce events. |
| "Viewed products" | A `view_item` event. | In this export `view_item` usually lists around eleven products and `view_item_list` almost never fires, so this step means seeing products, not opening one product page. |
| Nested funnel | A session counts at a step only if it also reached every earlier step, in any order, in the same session. | Keeps the funnel monotone. |
| Search session | At least one `view_search_results` event. | Search terms are obfuscated, so only the act of searching is used. |
| Checkout completion | Sessions that began checkout and ordered, divided by sessions that began checkout. | |
| Revenue per order | Order revenue (USD), divided by orders. | Uses the order rule above. |
| Visitor type | New if `ga_session_number` = 1, otherwise returning. | |
| Channel | The user's first-acquisition medium (`traffic_source.medium`), grouped. | In the GA4 export this records how the user was **first** acquired, not the source of this visit. |
| Previous buyer | The user ordered in an earlier session within the data. | Orders before 1 November 2020 are invisible, so this undercounts early on. |
| Engaged session | Any event carries `session_engaged = '1'`. | GA4's engagement flag. |

## Which data each analysis uses

- **Journey analyses** (funnel, search, checkout, segments, OKR baselines, experiment sizing) use the *analysis window*.
  It starts on the first day after which every journey event fired at a normal rate on every day. An event counts as
  firing normally on a day when its rate per session over the three days to that day is at least a quarter of its
  typical rate. The window also leaves out any week the data-quality gate held. The real export's basket and checkout
  tracking was switched on during November, so comparing steps before then would compare tracking, not shoppers.
- **Peak-trading windows** compare conversion and checkout completion, which rely on events tracked throughout, so
  they use the whole period except held weeks.
- **The weekly reports** cover every week, with notes where tracking was incomplete.

## The data-quality gate

A weekly report is **held** when the week is materially worse than the four weeks before it (median). That means
empty purchase events more than 10 points above that median, or sessions without `session_start` more than 5 points
above it. A problem present every week is a standing note on each report, not a hold: the gate catches incidents,
while the audit covers chronic issues.

## Statistics

- **Intervals for rates:** 95% Wilson score intervals.
- **Differences between two rates:** unpooled 95% interval with a pooled two-proportion z-test.
- **Like-for-like comparison (search):** non-search sessions are re-weighted to the search sessions' mix across
  device × visitor type × channel × previous buyer (direct standardisation). Strata without both groups are dropped, and
  the share of search sessions they held is reported as lost coverage.
- **Experiment sizing:** users, not sessions, are the unit, so repeat visits by one person do not understate the
  variance. Users per arm come from the standard two-proportion formula at 5% significance and 80% power, using
  conversion in normal January weeks inside the analysis window.
