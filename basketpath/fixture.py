"""Generated data in exactly the shape `extract` writes, with tracking faults planted at known counts.

For tests and CI only. In the real export the right answer is unknown, so every audit check
and every statistic is proved here against an answer key first. Nothing generated here is
ever reported as a finding.

Search has no effect on buying in this data by construction: returning visitors, desktop
users, paid-search visitors and previous buyers both search more and buy more. A method that
controls for that mix should find the search "effect" close to zero.
"""
from __future__ import annotations

import json
import pathlib
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .schema import EVENT_COLUMNS, ITEM_COLUMNS

FIRST, N_DAYS = date(2020, 11, 1), 92
PEAK = {date(2020, 11, 27), date(2020, 11, 28), date(2020, 11, 29), date(2020, 11, 30)}
GATE_WEEK = (date(2020, 12, 7), date(2020, 12, 13))  # missing transaction IDs are planted in this week only
DEVICES, DEVICE_P = ["desktop", "mobile", "tablet"], [0.55, 0.42, 0.03]
MEDIA = [("organic", "google"), ("(none)", "(direct)"), ("referral", "shop.googlemerchandisestore.com"),
         ("cpc", "google"), ("<Other>", "<Other>")]
MEDIA_P = [0.35, 0.25, 0.25, 0.10, 0.05]
COUNTRIES = ["United States", "India", "Canada", "United Kingdom", "France", "Japan"]
COUNTRY_P = [0.50, 0.12, 0.10, 0.10, 0.10, 0.08]
PAGES = {"/": "Home", "/Google+Redesign/Apparel": "Apparel", "/Google+Redesign/Drinkware": "Drinkware",
         "/Google+Redesign/Bags": "Bags", "/Google+Redesign/Office": "Office", "/basket.html": "Shopping Cart"}
TERMS = ["hoodie", "mug", "backpack", "stickers", "water bottle", "notebook", "t-shirt", "cap"]
CATEGORIES = ["Apparel", "Drinkware", "Bags", "Office", "Lifestyle", "Stationery"]
INT_COLS = [c for c, t in EVENT_COLUMNS.items() if t == "int"]
PARAMS = ["ga_session_id", "ga_session_number", "page_location", "page_title",
          "search_term", "engagement_time_msec", "session_engaged"]

PLANTED = {  # audit check -> count. The audit must find exactly these.
    "events_missing_session_id": 10,
    "sessions_without_session_start": 40,
    "sessions_with_repeated_session_start": 15,
    "purchases_missing_transaction_id": 25,
    "duplicate_purchase_events": 12,
    "purchases_without_revenue": 8,
    "ecommerce_events_without_items": 30,
    "purchase_sessions_without_checkout": 20,
    "searches_without_term": 25,
    "search_terms_obfuscated": 30,
    "page_views_without_location": 18,
    "purchase_revenue_mismatch": 6,
}
PAGE_TITLE_MISSING_SHARE = 0.08


def _simulate(n_users: int, rng) -> tuple[list[dict], list[dict]]:
    catalog = [(f"GGOEGX{i:04d}", f"Google Item {i}", CATEGORIES[i % len(CATEGORIES)],
                float(rng.choice([4.99, 9.99, 14.99, 19.99, 29.99, 49.99]))) for i in range(40)]
    ev, it = [], []
    txn = 400000
    for _ in range(n_users):
        uid = f"{rng.integers(10**9, 10**10)}.{rng.integers(10**9, 10**10)}"
        dev = DEVICES[rng.choice(3, p=DEVICE_P)]
        med, src = MEDIA[rng.choice(len(MEDIA), p=MEDIA_P)]
        ctry = COUNTRIES[rng.choice(len(COUNTRIES), p=COUNTRY_P)]
        n_sessions = 1 + int(rng.poisson(0.7))
        d0 = int(rng.integers(0, N_DAYS))
        offsets = np.concatenate([[0], np.cumsum(rng.integers(1, 15, size=n_sessions - 1))])
        bought_before = False
        for k, off in enumerate(offsets, start=1):
            if d0 + off >= N_DAYS:
                break
            day = FIRST + timedelta(days=int(d0 + off))
            t0 = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(seconds=int(rng.integers(0, 80000)))
            sid, returning = int(t0.timestamp()), k > 1
            p_search = 0.06 + 0.22 * returning + 0.04 * (dev == "desktop") + 0.06 * (med == "cpc")
            p_buy = (0.02 * (3.0 if returning else 1.0) * (1.5 if dev == "desktop" else 1.0)
                     * (2.0 if bought_before else 1.0) * (1.5 if med == "cpc" else 1.0)
                     * (1.8 if day in PEAK else 1.0))
            searched, bought = rng.random() < p_search, rng.random() < min(p_buy, 0.8)
            base = dict(event_date=day, user_pseudo_id=uid, ga_session_id=sid, ga_session_number=k,
                        device_category=dev, country=ctry, first_medium=med, first_source=src)
            clock = [t0]

            def emit(name, **kw):
                clock[0] += timedelta(seconds=int(rng.integers(3, 90)))
                row = dict.fromkeys(EVENT_COLUMNS)
                row.update(base, event_name=name, event_ts=clock[0], **kw)
                ev.append(row)
                return row

            def with_items(name, lines, qty, revenue=False, **kw):
                row = emit(name, n_items=len(lines), item_quantity=sum(qty), **kw)
                for (iid, iname, cat, price), q in zip(lines, qty):
                    it.append(dict(event_date=day, event_ts=row["event_ts"], event_name=name, user_pseudo_id=uid,
                                   ga_session_id=sid, item_id=iid, item_name=iname, item_category=cat,
                                   price_usd=price, quantity=q,
                                   item_revenue_usd=round(price * q, 2) if revenue else None))

            n_pv = 1 + int(rng.poisson(2.0))
            engaged = "1" if n_pv > 1 else "0"
            if k == 1:
                emit("first_visit")
            emit("session_start", session_engaged=engaged)
            for _ in range(n_pv):
                path = list(PAGES)[int(rng.integers(len(PAGES)))]
                emit("page_view", page_location="https://shop.googlemerchandisestore.com" + path,
                     page_title=PAGES[path], session_engaged=engaged)
            emit("user_engagement", engagement_time_msec=int(rng.integers(1000, 180000)), session_engaged=engaged)
            if searched:
                emit("view_search_results", search_term=TERMS[int(rng.integers(len(TERMS)))], session_engaged=engaged)
            viewed = bought or rng.random() < 0.45
            carted = bought or (viewed and rng.random() < 0.25)
            checkout = bought or (carted and rng.random() < 0.45)
            ship = bought or (checkout and rng.random() < 0.8)
            pay = bought or (ship and rng.random() < 0.7)
            basket = [catalog[j] for j in rng.choice(len(catalog), size=int(rng.integers(1, 4)), replace=False)]
            qty = [int(rng.integers(1, 3)) for _ in basket]
            if viewed:
                with_items("view_item", basket[:1], [1])
            if carted:
                with_items("add_to_cart", basket, qty)
            if checkout:
                with_items("begin_checkout", basket, qty)
            if ship:
                emit("add_shipping_info")
            if pay:
                emit("add_payment_info")
            if bought:
                txn += 1
                revenue = round(sum(round(p * q, 2) for (_, _, _, p), q in zip(basket, qty)), 2)
                with_items("purchase", basket, qty, revenue=True, transaction_id=str(txn), purchase_revenue_usd=revenue)
                bought_before = True
    return ev, it


def _key(df: pd.DataFrame) -> pd.Series:
    return (df["user_pseudo_id"] + "|" + df["ga_session_id"].astype("string") + "|"
            + df["event_ts"].dt.strftime("%Y%m%d%H%M%S") + "|" + df["event_name"])


def generate(out_dir, n_users: int = 9000, seed: int = 20201101) -> dict:
    """Write raw/events, raw/items and raw/param_inventory.parquet under out_dir; return the answer key."""
    rng = np.random.default_rng(seed)
    ev, it = _simulate(n_users, rng)
    E = pd.DataFrame(ev, columns=list(EVENT_COLUMNS))
    I = pd.DataFrame(it, columns=list(ITEM_COLUMNS))
    for df in (E, I):
        df["event_ts"] = pd.to_datetime(df["event_ts"], utc=True)
        df["ga_session_id"] = df["ga_session_id"].astype("Int64")
    E["_key"], I["_key"] = _key(E), _key(I)

    r = np.random.default_rng(seed + 1)
    used: set[int] = set()

    def pick(mask, k):
        pool = E.index[mask & ~E.index.isin(list(used))]
        if len(pool) < k:
            raise RuntimeError(f"need {k} rows to plant a fault, found {len(pool)}")
        chosen = r.choice(pool, size=k, replace=False)
        used.update(int(c) for c in chosen)
        return chosen

    name = E["event_name"]
    pv, search, purchase = name.eq("page_view"), name.eq("view_search_results"), name.eq("purchase")
    E.loc[pick(pv, 10), "ga_session_id"] = pd.NA
    E.loc[pick(pv, 18), "page_location"] = None
    n_pv = int(pv.sum())
    title_missing = round(PAGE_TITLE_MISSING_SHARE * n_pv)
    E.loc[pick(pv, title_missing), "page_title"] = None
    E.loc[pick(search, 25), "search_term"] = None
    E.loc[pick(search, 30), "search_term"] = "<Other>"

    in_gate = E["event_date"].between(*GATE_WEEK)
    E.loc[pick(purchase & in_gate, 25), "transaction_id"] = None
    zero = pick(purchase, 8)
    E.loc[zero, "purchase_revenue_usd"] = 0.0
    I.loc[I["_key"].isin(E.loc[zero, "_key"]), "item_revenue_usd"] = 0.0
    off = pick(purchase, 6)
    E.loc[off, "purchase_revenue_usd"] = (E.loc[off, "purchase_revenue_usd"] * 1.2).round(2)
    dup_src = pick(purchase, 12)
    dup = E.loc[dup_src].copy()
    dup["event_ts"] += pd.Timedelta(seconds=2)
    dup_items = I[I["_key"].isin(E.loc[dup_src, "_key"])].copy()
    dup_items["event_ts"] += pd.Timedelta(seconds=2)
    dup["_key"], dup_items["_key"] = _key(dup), _key(dup_items)

    empty_cart = pick(name.eq("add_to_cart"), 30)
    I = I[~I["_key"].isin(E.loc[empty_cart, "_key"])]
    E.loc[empty_cart, ["n_items", "item_quantity"]] = [0, None]
    E = pd.concat([E, dup], ignore_index=True)
    I = pd.concat([I, dup_items], ignore_index=True)

    # Session-level faults, on sessions chosen without overlap.
    sess = E.loc[E["ga_session_id"].notna(), ["user_pseudo_id", "ga_session_id"]].drop_duplicates()
    sess["s"] = sess["user_pseudo_id"] + "|" + sess["ga_session_id"].astype("string")
    E["_s"] = E["user_pseudo_id"] + "|" + E["ga_session_id"].astype("string")
    buyers = set(E.loc[E["event_name"].eq("purchase"), "_s"])
    no_checkout = r.choice(sorted(buyers), size=20, replace=False)
    rest = sorted(set(sess["s"]) - set(no_checkout))
    chosen = r.choice(rest, size=55, replace=False)
    no_start, twice = chosen[:40], chosen[40:]
    drop_checkout = E["_s"].isin(no_checkout) & E["event_name"].eq("begin_checkout")
    I = I[~I["_key"].isin(E.loc[drop_checkout, "_key"])]
    E = E[~drop_checkout & ~(E["_s"].isin(no_start) & E["event_name"].eq("session_start"))]
    again = E[E["_s"].isin(twice) & E["event_name"].eq("session_start")].copy()
    again["event_ts"] += pd.Timedelta(seconds=1)
    E = pd.concat([E, again], ignore_index=True)

    E = E.drop(columns=["_key", "_s"]).sort_values("event_ts", kind="stable").reset_index(drop=True)
    I = I.drop(columns=["_key"]).sort_values("event_ts", kind="stable").reset_index(drop=True)
    for c in INT_COLS:
        E[c] = E[c].astype("Int64")
    E["purchase_revenue_usd"] = E["purchase_revenue_usd"].astype("Float64")
    I["quantity"] = I["quantity"].astype("Int64")
    for c in ("price_usd", "item_revenue_usd"):
        I[c] = I[c].astype("Float64")

    raw = pathlib.Path(out_dir) / "raw"
    for sub in ("events", "items"):
        (raw / sub).mkdir(parents=True, exist_ok=True)
    for d, g in E.groupby("event_date"):
        g.to_parquet(raw / "events" / f"events_{d:%Y%m%d}.parquet", index=False)
    for d, g in I.groupby("event_date"):
        g.to_parquet(raw / "items" / f"items_{d:%Y%m%d}.parquet", index=False)
    inv = [dict(event_name=ev_name, param_key=p, n_present=int(n), n_nonnull=int(n))
           for p in PARAMS for ev_name, n in E.groupby("event_name")[p].count().items() if n > 0]
    pd.DataFrame(inv).astype({"n_present": "int64", "n_nonnull": "int64"}).to_parquet(raw / "param_inventory.parquet", index=False)

    key = {"planted": PLANTED, "page_title": {"missing": title_missing, "total": n_pv},
           "gate_week": "2020-W50", "true_search_effect_within_strata": 0.0}
    (pathlib.Path(out_dir) / "answer_key.json").write_text(json.dumps(key, indent=2))
    return key
