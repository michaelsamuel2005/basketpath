from basketpath import audit
from basketpath.plan import PLAN


def test_every_planted_tracking_fault_is_found_at_exactly_its_count(fx):
    con, key, _ = fx
    card, _ = audit.run(con)
    found = dict(zip(card["check"], card["numerator"]))
    for check, planted in key["planted"].items():
        assert found[check] == planted, check


def test_plan_coverage_measures_the_planted_gap_and_fails_it(fx):
    con, key, _ = fx
    _, cov = audit.run(con)
    title = cov[(cov["event"] == "page_view") & (cov["field"] == "page_title")].iloc[0]
    assert title["n_events"] == key["page_title"]["total"]
    assert title["n_ok"] == key["page_title"]["total"] - key["page_title"]["missing"]
    assert title["status"] == "fail"
    assert len(cov) == len(PLAN) and set(cov[cov["status"] == "fail"]["field"]) == {"page_title"}


def test_obfuscation_placeholders_are_reported_not_failed(fx):
    con, _, _ = fx
    card, _ = audit.run(con)
    row = card[card["check"] == "search_terms_obfuscated"].iloc[0]
    assert row["status"] == "info" and row["numerator"] > 0
