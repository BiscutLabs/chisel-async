# SPDX-License-Identifier: Apache-2.0
"""Acceptance machinery tests use synthetic evidence, never held-out executions."""
from pathlib import Path

import pytest

import l1_acceptance as l1


def test_frozen_plan_inventory_and_holdout():
    p = l1.read(l1.DEFAULT_PLAN)
    assert p["seeds"] == [41411, 41428, 41443, 41470]
    l1.check_plan(p)
    assert len(set(p["seeds"])) == 4 and {s % 2 for s in p["seeds"]} == {0, 1}
    assert set(p["seeds"]).isdisjoint(range(303))
    assert set(p["seeds"]).isdisjoint((2147483648, 4294967295))
    assert len(p["composition"]["fixtures"]) == 11
    assert len(p["phase"]["fixtures"]) == 18
    assert len(p["exports"]) == 34
    assert p["activity"]["positive_cases_including_regressions"] == 44 + 72 + 18 + 16 + 101 + 5 + 4 + 8 + 8
    assert p["activity"]["diagnostic_controls"] == 10 + 16 + 4 + 2 + 2 + 1
    assert len(p["sources"]) >= 140
    assert all(c["G"] == c["C"] + 1 for c in p["closure_parameters"])
    old = l1.read(l1.ROOT / "verification/l1-plan.json")
    assert p["baseline"] == old["baseline"] and p["production"] == old["production"]
    assert p["sources"] == old["sources"] and p["exports"] == old["exports"]
    assert set(p["seeds"]).isdisjoint(old["seeds"])
    assert p["supersession"]["used_seeds"] == old["seeds"]
    assert p["supersession"]["used_closure_parameters"] == old["closure_parameters"]
    assert {c["C"] for c in p["closure_parameters"]} == {5_000_000, 11_000_000, 19_000_000, 29_000_000}
    for role in ("C", "T", "H", "X"):
        assert {c[role] for c in p["closure_parameters"]}.isdisjoint(c[role] for c in old["closure_parameters"])


@pytest.mark.parametrize("seeds", ([], [1, 2, 3], [1, 2, 3, 3], [1, 3, 5, 7], [False, 2, 3, 4], [1, 2, 3, 2**32]))
def test_plan_rejects_incomplete_duplicate_or_invalid_seed_inventory(seeds):
    with pytest.raises(RuntimeError, match="L1_PLAN_CONTRACT"):
        l1.check_plan({"schema": "chisel-async-l1-plan-v1", "seeds": seeds})


def test_plan_cannot_reuse_exposed_candidate_seeds():
    plan = l1.read(l1.DEFAULT_PLAN)
    plan["seeds"][0] = plan["supersession"]["used_seeds"][0]
    with pytest.raises(RuntimeError, match="L1_PLAN_REUSED_SEED"):
        l1.check_plan(plan)


@pytest.mark.parametrize("mutation", ("missing", "duplicate", "wrong_seed", "empty", "extra"))
def test_inventory_rejects_vacuous_partial_and_substituted_results(mutation):
    rows = [{"fixture": "fifo", "seed": s} for s in (41003, 41018)]
    expected = [("fifo", 41003), ("fifo", 41018)]
    l1.inventory(rows, expected, ("fixture", "seed"), "BAD_INVENTORY")
    if mutation == "missing": rows.pop()
    elif mutation == "duplicate": rows[1] = rows[0]
    elif mutation == "wrong_seed": rows[1]["seed"] = 17
    elif mutation == "empty": rows.clear()
    else: rows.append({"fixture": "fifo", "seed": 999})
    with pytest.raises(RuntimeError, match="BAD_INVENTORY"):
        l1.inventory(rows, expected, ("fixture", "seed"), "BAD_INVENTORY")


@pytest.mark.parametrize("mutation", ("edit", "add", "delete", "empty"))
def test_candidate_source_drift_fails_closed(monkeypatch, mutation):
    expected = {"src/a": "a", "verification/b": "b"}
    actual = dict(expected)
    if mutation == "edit": actual["src/a"] = "x"
    elif mutation == "add": actual["tools/new"] = "x"
    elif mutation == "delete": del actual["src/a"]
    else: actual.clear()
    monkeypatch.setattr(l1, "source_inventory", lambda *a, **k: actual)
    with pytest.raises(RuntimeError, match="L1_SOURCE_DRIFT"):
        l1.check_sources({"sources": expected})


def test_candidate_tracks_acceptance_and_ci_inputs(monkeypatch, tmp_path):
    names = ["src/a.scala", "verification/l1_acceptance.py", "verification/l1-plan.json", "verification/l1-plan-2.json",
             ".github/workflows/ci.yml", "README.md"]
    for name in names:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("content\n")
    monkeypatch.setattr(l1, "git", lambda *a, **k: "\0".join(names).encode())
    assert set(l1.source_inventory(tmp_path, acceptance=True)) == set(names[:-1])
    assert set(l1.source_inventory(tmp_path)) == {"src/a.scala"}


def test_normalized_sources_are_portable_but_raw_evidence_is_exact(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"x\r\ny\r\n")
    b.write_bytes(b"x\ny\n")
    assert l1.sha(a, True) == l1.sha(b, True)
    assert l1.sha(a) != l1.sha(b)


@pytest.mark.parametrize("filename,key", (("trace.txt", "trace_sha256"), ("simulation.log", "log_sha256"),
                                        ("bench.sv", "bench_sha256"), ("results.xml", "xml_sha256")))
def test_modified_raw_artifact_rejected_even_with_stale_pass(tmp_path, filename, key):
    path = tmp_path / filename
    path.write_text("original")
    row = {"status": "PASS", key: l1.sha(path)}
    l1.artifact_hashes(row, tmp_path)
    path.write_text("changed")
    with pytest.raises(RuntimeError, match="L1_ARTIFACT_HASH"):
        l1.artifact_hashes(row, tmp_path)


def test_compiled_source_tamper_rejected(tmp_path):
    (tmp_path / "build").mkdir()
    p = tmp_path / "build/model.sv"
    p.write_text("original")
    row = {"sources": {p.name: l1.sha(p)}}
    l1.artifact_hashes(row, tmp_path)
    p.write_text("changed")
    with pytest.raises(RuntimeError, match="L1_SOURCE_ARTIFACT_HASH"):
        l1.artifact_hashes(row, tmp_path)


@pytest.mark.parametrize("log", ("", "FATAL: bench.sv:1: PROGRESS_TIMEOUT\n", "FATAL: bench.sv:1: EXPECTED\nFATAL: bench.sv:2: OTHER\n"))
def test_controls_reject_absent_wrong_or_multiple_fatals(log):
    with pytest.raises(RuntimeError, match="L1_WRONG_DIAGNOSTIC"):
        l1.exact_fatal(log, "EXPECTED")
    l1.exact_fatal("FATAL: bench.sv:1: EXPECTED\n", "EXPECTED")


def test_trace_control_rejects_success_and_unrelated_failure():
    with pytest.raises(RuntimeError, match="L1_CONTROL_ESCAPED"):
        l1.rejection(lambda: None, "EXPECTED")
    def fail(message): raise AssertionError(message)
    with pytest.raises(RuntimeError, match="L1_WRONG_DIAGNOSTIC"):
        l1.rejection(lambda: fail("WRONG"), "EXPECTED")
    l1.rejection(lambda: fail("EXPECTED"), "EXPECTED")


def synthetic_mutex_log():
    lines = []
    for epoch in (0, 1):
        for mode in range(3):
            for i in range(8):
                lines.append(f"CHOICE|{epoch}|{mode}|{i}|{1+i%2}|{10+i}|{epoch*10000+mode*100+i}")
    for i in range(110):
        latency = 10 + i % 91
        lines += [f"MUTEX_SCHEDULE|dut|{i*200}|{i}|1|{latency}", f"MUTEX_COMMIT|dut|{i*200+latency}|{i}|1"]
    return "\n".join(lines + ["RANDOM_MUTEX_PASS"]) + "\n"


def finished_mutex_log(path, ending="\n"):
    return synthetic_mutex_log().replace("\n", ending) + f"{path}:76: $finish called at 21600 (1fs){ending}"


@pytest.mark.parametrize("paths", ((r"C:\run (test)\41003_0\bench.sv", r"C:\run (test)\41003_1\bench.sv"),
                                  ("/tmp/run/41003_0/bench.sv", "/tmp/run/41003_1/bench.sv"),
                                  (r"C:\run\41003_0\bench.sv", "/tmp/run/41003_1/bench.sv"),
                                  ("C:/run [test]/41003_0/bench.sv", "/tmp/run [test]/41003_1/bench.sv")))
@pytest.mark.parametrize("ending", ("\n", "\r\n", ""))
def test_noise_comparison_ignores_only_known_terminal_bench_paths(paths, ending):
    # The optional ending applies only to the final line; decision rows remain
    # separated even when the terminal finish record has no trailing newline.
    logs = [synthetic_mutex_log() + f"{p}:76: $finish called at 21600 (1fs){ending}" for p in paths]
    l1.check_mutex_noise_logs(logs[0], paths[0], logs[1], paths[1])
    expected = synthetic_mutex_log() + f"<case-bench>:76: $finish called at 21600 (1fs){ending}"
    assert l1.comparable_mutex_log(logs[0], paths[0]) == expected


@pytest.mark.parametrize("before,after", (("CHOICE|0|0|0|1|10|0", "CHOICE|0|0|0|2|10|0"),
                                         ("MUTEX_SCHEDULE|dut|0|0|1|10", "MUTEX_SCHEDULE|dut|0|0|1|11"),
                                         ("MUTEX_COMMIT|dut|10|0|1", "MUTEX_COMMIT|dut|11|0|1"),
                                         (":76: $finish", ":77: $finish"),
                                         ("called at 21600", "called at 21601"),
                                         ("(1fs)", "(1ps)")))
def test_noise_comparison_still_rejects_decision_timing_and_finish_changes(before, after):
    first, second = "/tmp/41003_0/bench.sv", "/tmp/41003_1/bench.sv"
    left, right = finished_mutex_log(first), finished_mutex_log(second)
    assert before in right
    with pytest.raises(RuntimeError, match="L1_MUTEX_GLOBAL_RNG_INTERFERENCE"):
        l1.check_mutex_noise_logs(left, first, right.replace(before, after, 1), second)


@pytest.mark.parametrize("mutation", ("wrong_path", "missing", "not_terminal", "wrong_finish_content"))
def test_noise_comparison_rejects_unrecognized_finish_identity(mutation):
    path = "/tmp/41003_0/bench.sv"
    log = finished_mutex_log(path)
    if mutation == "wrong_path": log = log.replace(path, "/tmp/unrelated/bench.sv")
    elif mutation == "missing": log = synthetic_mutex_log()
    elif mutation == "not_terminal": log += "unexpected output\n"
    else: log = log.replace("$finish called", "$finish unexpectedly called")
    with pytest.raises(RuntimeError, match="L1_MUTEX_FINISH_IDENTITY"):
        l1.comparable_mutex_log(log, path)


def test_noise_comparison_keeps_nonterminal_source_paths_significant():
    first, second = "/tmp/41003_0/bench.sv", "/tmp/41003_1/bench.sv"
    left = "other record from " + first + "\n" + finished_mutex_log(first)
    right = "other record from " + second + "\n" + finished_mutex_log(second)
    with pytest.raises(RuntimeError, match="L1_MUTEX_GLOBAL_RNG_INTERFERENCE"):
        l1.check_mutex_noise_logs(left, first, right, second)


def test_comparison_does_not_modify_raw_log_or_recorded_hash(tmp_path):
    path = tmp_path / "simulation.log"
    bench = r"C:\run\41003_0\bench.sv"
    path.write_text(finished_mutex_log(bench))
    before = path.read_bytes()
    record = {"log_sha256": l1.sha(path)}
    l1.comparable_mutex_log(path.read_text(), bench)
    l1.artifact_hashes(record, tmp_path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("path", (r"C:\old-host\41003_0\bench.sv", "/old-host/41003_0/bench.sv"))
def test_audit_uses_retained_compile_path_for_relocated_native_artifacts(path):
    row = {"seed": 41003, "noise": 0, "compile": ["iverilog", "-s", "MutexReview", "-o", "sim.vvp", path, "source.sv"]}
    assert l1.mutex_bench_path(row) == path
    row["noise"] = 1
    with pytest.raises(RuntimeError, match="L1_MUTEX_BENCH_IDENTITY"):
        l1.mutex_bench_path(row)


def test_full_mutex_audit_accepts_relocated_artifacts_without_ignoring_raw_hashes(tmp_path):
    output = tmp_path / "downloaded-artifact"
    rows = []
    for noise in (0, 1):
        directory = output / f"41003_{noise}"
        directory.mkdir(parents=True)
        original_bench = f"/ci/original/mutex/41003_{noise}/bench.sv"
        (directory / "bench.sv").write_text("synthetic bench\n")
        log = finished_mutex_log(original_bench)
        (directory / "simulation.log").write_text(log)
        row = {"seed": 41003, "noise": noise, "status": "PASS", "exit_code": 0,
               "compile": ["iverilog", "-o", "/ci/original/sim.vvp", original_bench, "model.sv"],
               "bench_sha256": l1.sha(directory / "bench.sv"), "log_sha256": l1.sha(directory / "simulation.log"),
               "evidence": l1.mutex_log(log)}
        l1.write(directory / "case.json", row)
        rows.append(row)
    directory = output / "constant_resolution"
    directory.mkdir()
    lines = []
    for line in synthetic_mutex_log().splitlines():
        fields = line.split("|")
        if fields[0] == "MUTEX_SCHEDULE": fields[-1] = "10"
        if fields[0] == "MUTEX_COMMIT": fields[2] = str(int(fields[3]) * 200 + 10)
        lines.append("|".join(fields))
    log = "\n".join(lines) + "\n"
    (directory / "simulation.log").write_text(log)
    control = {"status": "EXPECTED_REJECTION", "exit_code": 0, "diagnostic": "L1_MUTEX_LATENCY_COVERAGE",
               "evidence": l1.mutex_log(log), "log_sha256": l1.sha(directory / "simulation.log")}
    l1.write(directory / "case.json", control)
    l1.write(output / "report.json", {"status": "PASS", "cases": rows, "faults": [control], "distinct_latencies": 91})
    plan = {"seeds": [41003], "mutex_min_latencies": 60}
    l1.audit_mutex(plan, output)
    (output / "41003_1/simulation.log").write_text("changed")
    with pytest.raises(RuntimeError, match="L1_ARTIFACT_HASH"):
        l1.audit_mutex(plan, output)


@pytest.mark.parametrize("mutation,diagnostic", (("empty", "L1_MUTEX_RESET_REPRODUCIBILITY"), ("choice", "L1_MUTEX_RESET_REPRODUCIBILITY"),
                                              ("commit", "L1_MUTEX_COMMIT"), ("bounds", "L1_MUTEX_BOUNDS")))
def test_mutex_raw_log_inventory_and_timing(mutation, diagnostic):
    log = synthetic_mutex_log()
    assert l1.mutex_log(log)["commits"] == 110
    if mutation == "empty": log = "RANDOM_MUTEX_PASS\n"
    elif mutation == "choice": log = log.replace("CHOICE|1|0|0|1|10|10000", "CHOICE|1|0|0|2|10|10000")
    elif mutation == "commit": log = log.replace("MUTEX_COMMIT|dut|10|0|1", "MUTEX_COMMIT|dut|11|0|1")
    else: log = log.replace("MUTEX_SCHEDULE|dut|0|0|1|10", "MUTEX_SCHEDULE|dut|0|0|1|101")
    with pytest.raises(RuntimeError, match=diagnostic):
        l1.mutex_log(log)


def test_constant_resolution_and_missing_winner_coverage_fail():
    row = l1.mutex_log(synthetic_mutex_log())
    assert l1.mutex_coverage([row], 60) == 91
    row["latencies"] = [10]
    with pytest.raises(RuntimeError, match="L1_MUTEX_LATENCY_COVERAGE"):
        l1.mutex_coverage([row], 60)
    row["winners"]["1"] = [1]
    with pytest.raises(RuntimeError, match="L1_MUTEX_WINNER_COVERAGE"):
        l1.mutex_coverage([row], 60)


def test_activity_formula_keeps_reset_and_warm_cases_distinct():
    plan = l1.read(l1.DEFAULT_PLAN)
    assert l1.phase_total(plan, "two_fork", 41003, "standard") == 261
    assert l1.phase_total(plan, "two_fork", 41018, "standard") == 258
    assert l1.phase_total(plan, "two_fork", 0, "reset_partial_fork") == 259
    assert l1.phase_total(plan, "encoding_from_dual", 0, "reset_partial_valid") == 578
    assert l1.phase_total(plan, "encoding_from_dual", 0, "reset_partial_spacer") == 579


def test_attempt_never_overwrites_existing_evidence(tmp_path):
    output = tmp_path / "retained"
    output.mkdir()
    sentinel = output / "report.json"
    sentinel.write_text('{"status":"ERROR","error":"original failure"}')
    before = sentinel.read_bytes()
    with pytest.raises(RuntimeError, match="L1_OUTPUT_EXISTS"):
        l1.run(Path("absent-plan"), Path("absent-candidate"), Path("absent-generated"), output)
    assert sentinel.read_bytes() == before


def test_failed_attempt_records_error_in_fresh_directory(tmp_path):
    output = tmp_path / "attempt"
    with pytest.raises(FileNotFoundError):
        l1.run(tmp_path / "absent-plan", tmp_path / "absent-candidate", tmp_path, output)
    report = l1.read(output / "report.json")
    assert report["status"] == "ERROR" and report["error"]


def test_changed_export_identity_is_rejected_before_copy(tmp_path):
    fixture = tmp_path / "generated/f"
    fixture.mkdir(parents=True)
    l1.write(fixture / "contract.json", {"semantic_sha256": "changed", "manifest": {
        "probe_abi": {"sha256": "probe"}, "port_abi": {"sha256": "port"}}})
    plan = {"exports": {"f": {"semantic_sha256": "frozen", "probe_abi_sha256": "probe", "port_abi_sha256": "port"}}}
    with pytest.raises(RuntimeError, match="L1_EXPORT_IDENTITY"):
        l1.prepare_exports(plan, fixture.parent, tmp_path / "copy")
    assert not (tmp_path / "copy").exists()
