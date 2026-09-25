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
Not yet run on the real export. Follow **Run it on the real data** below: `python -m basketpath.build`
replaces this section with the headline numbers and writes the full readout to `reports/findings.md`.
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
      └─ db.py      DuckDB views → one row per session, with nested funnel flags
          ├─ audit.py      13 checks + tracking-plan coverage → marts/audit_scorecard.csv
          ├─ analysis.py   funnel · search vs intent · checkout · trading windows · segments
          ├─ report.py     weekly KPI report with a data-quality gate → reports/weekly/
          └─ readout.py    charts, findings, OKRs → reports/, docs/okrs.md
```

Definitions for every metric are in [docs/metrics.md](docs/metrics.md). The tracking plan is in
[docs/tracking_plan.md](docs/tracking_plan.md), generated from the same code the audit runs.

### The data-quality gate

A weekly report is marked **Held: do not circulate** when more than 5% of that week's purchase events have no
transaction ID, or more than 2% of sessions have no `session_start`. It prints the reasons. A report that flags its
own broken inputs is safer than one that silently publishes them.

## Why trust it: the tests

The real export has no answer key, so every check is first proved on generated data in exactly the extract's
schema, with tracking faults planted at known counts:

- Each of the audit's checks finds exactly the number of faults planted, and plan coverage measures the planted gap.
- In the generated data, search has **no** effect on buying by construction, but the people who search are more
  likely to buy anyway. The naive comparison shows a clear gap; the like-for-like comparison recovers roughly zero.
- The statistics match textbook values (a Wilson interval, a z-test, the classic 3,841-per-arm sample size, and a
  Simpson's-paradox example).
- The weekly gate holds exactly the one week where transaction IDs were planted missing.
- The build is idempotent: two runs give byte-identical marts.

```bash
pip install -e ".[dev]"
pytest                                   # 21 tests, under 10 seconds
python -m basketpath.build --fixture     # full build on generated data → build/fixture/
```

Everything built from generated data goes to `build/fixture/` and is labelled as not being findings.

## Tableau and the GA4 interface

- [tableau/BUILD.md](tableau/BUILD.md): building and publishing the dashboard from the marts.
- [docs/ga4_demo_segments.md](docs/ga4_demo_segments.md): rebuilding the segments and funnel in GA4's own interface.
- [docs/memo_template.md](docs/memo_template.md): the one-page memo to a product manager.

## Limitations

- This is Google's **obfuscated** sample. Some values are placeholders (for example `<Other>`), and Google notes
  that the sample is not fully internally consistent. The audit reports placeholders separately from tracking faults.
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
