# Building the Tableau Public dashboard

The build writes tidy CSVs to `marts/`. Tableau Public (free) connects to them directly. Build the
dashboard yourself and publish it: you need to be able to talk through every chart.

**Rule for every rate:** re-aggregate from counts, for example `SUM([purchasing_sessions]) / SUM([sessions])`.
Averaging daily rates weights a quiet Sunday the same as Black Friday.

## Data sources (Connect → Text file)

| File | One row per | Use for |
|---|---|---|
| `marts/daily_kpis.csv` | day | Trading overview, peak calendar |
| `marts/funnel.csv` | breakdown × group × step | Funnel |
| `marts/checkout_by_device.csv` | device | Checkout |
| `marts/segments.csv` | segment | Segment table |
| `marts/audit_scorecard.csv` | audit check | Data-quality panel |

## Dashboard 1: trading overview

- Calculated fields: `Conversion = SUM([purchasing_sessions]) / SUM([sessions])`;
  `Checkout completion = SUM([checkout_completed]) / SUM([checkout_sessions])`.
- Line chart of `date` (continuous day) against `Conversion`. Add a 7-day moving average as a table calculation.
- Put `calendar_label` on Label, with annotations on Black Friday, Cyber Monday and Christmas Day.
- KPI tiles: total sessions, conversion, revenue.

## Dashboard 2: funnel

- Filter `breakdown` to one value (single-value dropdown); `group` on Colour; `step` on Rows, sorted by `step_order`.
- `SUM([sessions])` on Columns; label with `rate_from_previous`.
- Title the biggest drop so the viewer does not have to find it.

## Dashboard 3: checkout, segments and data quality

- Bar chart of `purchased_rate` by `device_category` with `completion_lo` and `completion_hi` as error bars
  (a reference band per bar).
- Table from `segments.csv`: segment, sessions, conversion, revenue per session.
- Small table from `audit_scorecard.csv` showing checks with status `fail`: the caveats travel with the numbers.

## Publish

Save to Tableau Public, set the workbook to show sheets as tabs, and paste the link under **Results** in the README.
