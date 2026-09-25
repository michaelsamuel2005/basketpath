from basketpath import analysis


def test_funnel_is_nested_and_starts_from_every_session(fx):
    con, _, _ = fx
    f = analysis.funnel(con)
    overall = f[f["breakdown"] == "overall"].sort_values("step_order")
    assert overall["sessions"].is_monotonic_decreasing
    n = con.execute("SELECT COUNT(*) FROM (SELECT DISTINCT user_pseudo_id, ga_session_id FROM events "
                    "WHERE ga_session_id IS NOT NULL)").fetchone()[0]
    assert overall["sessions"].iloc[0] == n
    for breakdown, g in f.groupby("breakdown"):
        assert g[g["step_order"] == 0]["sessions"].sum() == n, breakdown


def test_buyers_with_no_tracked_checkout_leave_the_full_path_but_not_conversion(fx):
    con, key, _ = fx
    f = analysis.funnel(con)
    purchased = f[(f["breakdown"] == "overall") & (f["step"] == "Purchased")]["sessions"].iloc[0]
    buyers = con.execute("SELECT COUNT(*) FROM sessions WHERE has_purchase").fetchone()[0]
    assert purchased == buyers - key["planted"]["purchase_sessions_without_checkout"]


def test_previous_buyer_flag_only_looks_backwards(fx):
    con, _, _ = fx
    assert con.execute("SELECT COUNT(*) FROM sessions WHERE ga_session_number = 1 AND prior_purchaser").fetchone()[0] == 0
    wrong = con.execute("""
        SELECT COUNT(*) FROM sessions AS s WHERE prior_purchaser <> EXISTS (
          SELECT 1 FROM sessions AS e WHERE e.user_pseudo_id = s.user_pseudo_id
            AND e.start_ts < s.start_ts AND e.has_purchase)""").fetchone()[0]
    assert wrong == 0


def test_search_gap_is_real_but_explained_by_who_searches(fx):
    # In the generated data search has no effect by construction, only a different mix of visitors.
    con, _, _ = fx
    s, strata = analysis.search_vs_intent(con)
    naive, adjusted = s["naive"], s["adjusted"]
    assert naive["lo"] > 0, "the naive gap should be clearly positive"
    assert abs(adjusted["diff"]) < 3 * adjusted["se"], "like for like, the gap should vanish"
    assert s["share_explained"] > 0.6 and adjusted["coverage"] > 0.95
    assert strata["n_search"].sum() == s["search_sessions"]


def test_follow_up_test_is_sized_from_real_baselines(fx):
    con, _, _ = fx
    f = analysis.follow_up_test(con)
    assert f["enough"] and 0 < f["baseline_weekly_conversion"] < 1
    sizes = [p["users_per_arm"] for p in f["plans"]]
    assert sizes == sorted(sizes, reverse=True), "smaller lifts need more users"


def test_segments_are_consistent_with_the_session_table(fx):
    con, _, _ = fx
    seg = analysis.segments(con).set_index("segment")
    assert seg.loc["Searched", "sessions"] + seg.loc["Did not search", "sessions"] == seg.loc["All sessions", "sessions"]
    assert seg.loc["Abandoned basket", "purchasing_sessions"] == 0
