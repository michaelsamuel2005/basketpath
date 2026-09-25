# Rebuilding the segments in the Google Analytics interface

The pipeline defines segments as SQL. Product teams mostly work in an analytics tool, so this
shows the same thinking in GA4's own interface, using Google's free demo account for the same store.

**The demo account's data is not the BigQuery sample.** The periods and processing differ, so the
numbers will not match `reports/findings.md`. The point is fluency with the tool, not a second estimate.

1. **Open the demo account.** Search for Google's "Google Analytics demo account" help page and use its link
   to the GA4 Google Merchandise Store property. Access rules change, so follow that page's current instructions.
2. **Build three session segments** (Explore → Blank → Segments → + → Session segment):
   - *Searched*: include sessions where Event name exactly matches `view_search_results`.
   - *Abandoned basket*: include sessions with `add_to_cart`; exclude sessions with `purchase`.
   - *New visitors on mobile*: Device category = mobile, and the session is the user's first.
3. **Funnel exploration.** Steps `view_item` → `add_to_cart` → `begin_checkout` → `add_shipping_info` →
   `add_payment_info` → `purchase`. Break down by Device category, then compare the *Searched* segment with all users.
4. **Path exploration.** Start from `view_search_results` and see what shoppers do next.
5. **Keep evidence.** Save screenshots to `docs/ga4_demo/` and link them from the README, noting the dates shown.
