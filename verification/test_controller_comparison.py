# SPDX-License-Identifier: Apache-2.0
"""Protect scientific interpretation of the comparison against harness errors."""
import itertools
import subprocess

import pytest

from compare_controllers import classify, configuration, expression, instrument, random_words, run_case


def evaluate(tree, values):
    if isinstance(tree, str):
        return values[tree]
    if tree[0] == "~":
        return not evaluate(tree[1], values)
    a, b = (evaluate(t, values) for t in tree[1:])
    return a and b if tree[0] == "&" else a or b


def test_gate_expansion_preserves_precedence_and_parentheses():
    # Independent Boolean truth tables; a precedence error changes the controller.
    for a, b, c in itertools.product((False, True), repeat=3):
        values = dict(a=a, b=b, c=c)
        assert evaluate(expression("~a | b & c"), values) == ((not a) or (b and c))
        assert evaluate(expression("~(a | b) & c"), values) == (not (a or b) and c)


@pytest.mark.parametrize("source", ["a && b", "a ^ b", "a ? b : c", "a[0]", "a + b", "(a", "a)", "a |", ""])
def test_new_compiler_grammar_requires_explicit_support(source):
    with pytest.raises(ValueError):
        expression(source)


def test_wrong_module_is_not_silently_instrumented():
    with pytest.raises(ValueError, match="inventory"):
        instrument("module Renamed; endmodule")


def test_frozen_prng_and_shared_environment():
    assert list(itertools.islice(random_words(0), 5)) == [270369, 67634689, 2647435461, 307599695, 2398689233]
    assert configuration(42, 3, 4)["environment_ns"] == configuration(42, 3, 23)["environment_ns"]


PASS = "RESULT PASS accepted=53 delivered=49 aborted=4 returned=47 offered=51 peak=2 resets=7"
FATAL = "FATAL: P:\\repo\\bench.sv:48: DATA_HOLD channel=1\n"


def test_required_activity_and_accounting():
    assert classify(0, PASS)["status"] == "PASS"
    for log in ("", PASS.replace("delivered=49", "delivered=48"), PASS.replace("aborted=4", "aborted=0"),
                PASS.replace("resets=7", "resets=0"), PASS + "\n" + PASS):
        assert classify(0, log)["status"] == "INFRASTRUCTURE_ERROR"


def test_simulator_failure_is_not_a_counterexample():
    for code, log in ((1, "syntax error"), (0, FATAL), (-11, FATAL), (1, PASS),
                      (1, FATAL.replace("DATA_HOLD", "MISSING_CELL_DELAY"))):
        assert classify(code, log)["status"] == "INFRASTRUCTURE_ERROR"
    assert classify(1, FATAL)["status"] == "VIOLATION"
    # Icarus can run two armed monitors at the same simulation time before exit.
    assert classify(1, FATAL + FATAL)["all_diagnostics"] == ["DATA_HOLD", "DATA_HOLD"]
    assert classify(1, FATAL.replace("DATA_HOLD", "SIM_DEADLINE"))["status"] == "BOUNDED_NONPROGRESS"


def test_host_timeout_overwrites_stale_simulation_log(tmp_path, monkeypatch):
    (tmp_path / "simulation.log").write_text(PASS)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("vvp", 20)
    monkeypatch.setattr(subprocess, "run", timeout)
    result = run_case(tmp_path / "bench.vvp", tmp_path, configuration(0, 3, 4))
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["diagnostic"] == "HOST_TIMEOUT"
    assert "RESULT PASS" not in (tmp_path / "simulation.log").read_text()
