# basketpath

Search, browse and checkout analytics on real shopping behaviour: Google's public GA4 export from its
merchandise store (1 November 2020 to 31 January 2021, about 4.3 million events).

It answers the questions a product team working on search and checkout would ask, in the order
they should be asked:

1. **Can the tracking be trusted?** A tracking plan defines what each journey step must send. An audit measures the
   export against it before anything is reported, and says who should fix what.
2. **Where do shoppers drop out?** A nested funnel from product view to purchase, by device, new versus returning
   visitor, and channel.
3. **Does search help, or do people who search already intend to buy?** Searchers are compared with similar
   non-searchers, and the experiment that would settle the question is sized from measured baselines.
4. **Is finishing the shop harder on mobile?** Checkout completion step by step, by device, with intervals.
5. **What changed through Black Friday and Christmas?** Trading windows against a quiet baseline.

It also sets OKRs from the measured baselines, defines reusable custom segments, and produces a weekly KPI report
with a data-quality gate. Its tidy marts are ready for Tableau.

## Results

<!-- results:start -->
- **Data:** 360,129 sessions from 270,154 users, 2020-11-01 to 2021-01-31. Journey analyses use 244,763 sessions from 2020-11-26, when every journey event was tracked, excluding held week 2021-W04.
- **Orders:** 5,692 purchase events become 4,922 orders after removing 320 double-fired repeats and 450 empty events.
- **Tracking audit:** 6 of 14 checks failed: purchases missing transaction id, duplicate purchase events, purchases without revenue, ecommerce events without items, add to cart with many products, tracking plan fields below target.
- **Conversion:** 1.29% of sessions (95% CI 1.25% to 1.34%). Biggest drop: started a visit to viewed products, where 20.1% continue.
- **Search:** used in 4.3% of sessions. Naive conversion gap +2.86 pp; like for like +2.93 pp (95% CI +2.56 pp to +3.29 pp).
- **Checkout completion:** mobile 47.4%, desktop 45.2% (+2.15 pp).

Full readout: [reports/findings.md](reports/findings.md).
<!-- results:end -->

## Run it on the real data

The data lives in BigQuery. A free BigQuery sandbox is enough: no billing account, and the whole extract
is well inside the free monthly query allowance (the extractor prints the size before it runs).

1. Create a project at [console.cloud.google.com/bigquery](https://console.cloud.google.com/bigquery) and note its project ID.
2. Install and sign in:
   ```bash
   pip install -e ".[bigquery]"
   gcloud auth application-default login
   ```
3. Check one day first (1 December 2020): it validates the schema before you pull everything.
   ```bash
   python -m basketpath.extract --project YOUR_PROJECT_ID --check
   ```
4. Extract all 92 days to `data/raw/` (kept out of git), then build:
   ```bash
   python -m basketpath.extract --project YOUR_PROJECT_ID
   python -m basketpath.build
   ```
5. Commit `marts/`, `reports/`, `docs/` and this README. The weekly-report workflow then regenerates the reports
   from the committed marts every Monday.

## How it works

```
BigQuery (nested GA4 export)
  └─ extract.py     UNNEST event_params and items, one day at a time → Parquet
      └─ db.py      DuckDB views → orders (de-duplicated) → one row per session, with nested funnel flags
          ├─ audit.py      14 checks, including tracking-plan coverage → marts/audit_scorecard.csv
          ├─ analysis.py   funnel · search vs intent · checkout · trading windows · segments
          ├─ report.py     weekly KPI report with a data-quality gate → reports/weekly/
          └─ readout.py    charts, findings, OKRs → reports/, docs/okrs.md
```

Definitions for every metric are in [docs/metrics.md](docs/metrics.md). The tracking plan is in
[docs/tracking_plan.md](docs/tracking_plan.md), generated from the same code the audit runs.

### Orders, the analysis window and the data-quality gate

Three rules came out of diagnosing the real export, and all three are in [docs/metrics.md](docs/metrics.md):

- **Purchase events are not orders.** Repeats of an ID the same user already sent are removed (double-fires). Events
  with no ID and no revenue are not counted. Events with no ID but with revenue are counted and flagged.
- **Journey analyses start once the journey was fully tracked.** Basket and checkout tracking was switched on during
  November, so the build finds the first day from which every journey event fired normally, and starts there.
- **The weekly gate catches incidents, not chronic issues.** A week is marked **Held: do not circulate** when it is
  materially worse than the four weeks before it. Problems present every week become standing notes instead.
  Held weeks are also left out of the analyses.

## Why trust it: the tests

The real export has no answer key, so every check is first proved on generated data in exactly the extract's
schema, with tracking faults planted at known counts:

- Each of the audit's checks finds exactly the number of faults planted, and plan coverage measures the planted gap.
- The order rule removes a double-fire, drops an empty event and keeps an ID-less order with revenue, on a hand-built example.
- When basket tracking is removed before a given date, the analysis window starts on that date.
- In the generated data, search has **no** effect on buying by construction, but the people who search are more
  likely to buy anyway. The naive comparison shows a clear gap; the like-for-like comparison recovers roughly zero.
- The statistics match textbook values (a Wilson interval, a z-test, the classic 3,841-per-arm sample size, and a
  Simpson's-paradox example).
- The weekly gate holds exactly the one week with a planted incident, and a problem present in every week produces
  a note, not a hold.
- The build is idempotent: two runs give byte-identical marts.

```bash
pip install -e ".[dev]"
pytest                                   # 26 tests, about 10 seconds
python -m basketpath.build --fixture     # full build on generated data → build/fixture/
```

Everything built from generated data goes to `build/fixture/` and is labelled as not being findings.

## Tableau and the GA4 interface

- [tableau/BUILD.md](tableau/BUILD.md): building and publishing the dashboard from the marts.
- [docs/ga4_demo_segments.md](docs/ga4_demo_segments.md): rebuilding the segments and funnel in GA4's own interface.
- [docs/memo_template.md](docs/memo_template.md): the one-page memo to a product manager.

## Limitations

- This is Google's **obfuscated** sample. Some values are placeholders: every search term is `<obfuscated>`, so the
  analysis uses whether people searched, not what they searched for. The audit reports placeholders separately from
  tracking faults.
- The product lists inside `view_item` and `add_to_cart` events usually hold about eleven products, so the analysis
  works at session level, not product level.
- It is a merchandise store, not a grocer. The methods transfer; the numbers do not.
- Everything is observational. Differences between groups describe who did what, not what caused it.
- `traffic_source` in the GA4 export is the user's **first** acquisition channel, not the source of each visit.

## Repository layout

```
basketpath/   extract, db, plan, audit, analysis, stats, report, readout, build, fixture
tests/        audit, journey, reporting, statistics and extract-contract tests
docs/         tracking plan, metric definitions, OKRs, GA4 walkthrough, memo template
tableau/      dashboard build guide
data/reference/  trading calendar and trading windows
.github/workflows/  tests on every push; weekly report every Monday
```

Built by Michael Samuel.
