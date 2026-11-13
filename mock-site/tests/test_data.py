from data import find_discrepancies, generate_reports, planted_discrepancies


def test_same_date_and_seed_give_same_data():
    assert generate_reports("2026-11-10", seed=7) == generate_reports("2026-11-10", seed=7)


def test_different_date_or_seed_gives_different_data():
    base = generate_reports("2026-11-10", seed=7)
    assert generate_reports("2026-11-11", seed=7) != base
    assert generate_reports("2026-11-10", seed=8) != base


def test_reference_function_finds_exactly_the_planted_discrepancies():
    for date in ("2026-11-03", "2026-11-10", "2026-11-12"):
        report_a, report_b = generate_reports(date, seed=42)
        found = {(d["id"], d["kind"]) for d in find_discrepancies(report_a, report_b)}
        planted = {(d["id"], d["kind"]) for d in planted_discrepancies(date, seed=42)}
        assert found == planted


def test_every_kind_of_discrepancy_is_planted():
    kinds = {d["kind"] for d in planted_discrepancies("2026-11-10", seed=42)}
    assert kinds == {"amount_mismatch", "rounding", "missing_in_a", "missing_in_b"}


def test_rounding_differences_stay_under_one_thousand():
    report_a, report_b = generate_reports("2026-11-10", seed=42)
    for d in find_discrepancies(report_a, report_b):
        if d["kind"] == "rounding":
            assert 0 < abs(d["diff"]) < 1000
        if d["kind"] == "amount_mismatch":
            assert abs(d["diff"]) >= 1000
