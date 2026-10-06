# SPDX-License-Identifier: Apache-2.0
import copy

import pytest

from run_l0 import BASELINE, SPEC, check_candidate, check_reports, expected_cases


def reports():
    baseline = {"status": "PASS", "required": BASELINE,
                "steps": [{"name": name, "exit_code": 0} for name in BASELINE]}
    campaign = {"status": "PASS", "depths": SPEC["depths"], "random_seeds": SPEC["seeds"],
                "seed_start": SPEC["seed_start"],
                "cases": [{"case": name, "status": "PASS", "stg_events": 1000} for name in expected_cases()],
                "controls": [{"case": name, "status": "VIOLATION", "all_diagnostics": [diagnostic]}
                             for name, diagnostic in SPEC["faults"].items()]}
    return copy.deepcopy((baseline, campaign))


def test_acceptance_inventory_is_finite_and_separate_from_development_seeds():
    baseline, campaign = reports()
    check_reports(baseline, campaign)
    assert len(expected_cases()) == len(set(expected_cases())) == 312
    seeds = [int(name.rsplit("_", 1)[1]) for name in expected_cases() if "_seed_" in name]
    assert len(seeds) == 256 and min(seeds) == 10000 and max(seeds) == 10063


@pytest.mark.parametrize("fault", ["partial", "duplicate", "inactive", "wrong_seed", "failure"])
def test_missing_duplicate_inactive_or_failed_acceptance_is_rejected(fault):
    baseline, campaign = reports()
    if fault == "partial":
        campaign["cases"].pop()
    elif fault == "duplicate":
        campaign["cases"][1] = campaign["cases"][0]
    elif fault == "inactive":
        campaign["cases"][0]["stg_events"] = 0
    elif fault == "wrong_seed":
        campaign["seed_start"] = 0
    else:
        campaign["cases"][0]["status"] = "BOUNDED_NONPROGRESS"
    with pytest.raises(RuntimeError, match="L0_CAMPAIGN_INCOMPLETE"):
        check_reports(baseline, campaign)


@pytest.mark.parametrize("fault", ["missing", "wrong_diagnostic", "pass", "crash"])
def test_fault_controls_require_the_exact_rejection(fault):
    baseline, campaign = reports()
    if fault == "missing":
        campaign["controls"].pop()
    elif fault == "wrong_diagnostic":
        campaign["controls"][0]["all_diagnostics"] = ["UNEXPECTED_TOKEN"]
    else:
        campaign["controls"][0]["status"] = fault.upper()
    with pytest.raises(RuntimeError, match="L0_FAULT_CONTROL"):
        check_reports(baseline, campaign)


@pytest.mark.parametrize("fault", ["missing_lane", "failed_lane", "stale_status"])
def test_incomplete_baseline_cannot_be_replaced_by_the_fresh_sweep(fault):
    baseline, campaign = reports()
    if fault == "missing_lane":
        baseline["steps"].pop()
    elif fault == "failed_lane":
        baseline["steps"][0]["exit_code"] = 1
    else:
        baseline["status"] = "RUNNING"
    with pytest.raises(RuntimeError, match="L0_BASELINE_INCOMPLETE"):
        check_reports(baseline, campaign)


def test_candidate_covers_source_addition_deletion_and_edits():
    candidate = {"schema": 1, "campaign": SPEC, "baseline": BASELINE, "sources": {"src/a": "digest"}}
    check_candidate(candidate, {"src/a": "digest"})
    for actual in ({}, {"src/a": "changed"}, {"src/a": "digest", "tools/b": "new"}):
        with pytest.raises(RuntimeError, match="L0_SOURCE_DRIFT"):
            check_candidate(candidate, actual)
    with pytest.raises(RuntimeError, match="L0_CANDIDATE_CONTRACT"):
        check_candidate(candidate | {"campaign": SPEC | {"seed_start": 0}}, candidate["sources"])
