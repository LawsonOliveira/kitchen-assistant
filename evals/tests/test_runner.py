"""Scenario runner rules (PLAN.md Loop 6): pass^3, judge alerts never flip pass/fail, red-team leakage, guarded reset."""

import os
import subprocess
from pathlib import Path

import pytest

import runner

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("trials, passed", [([True, True, True], True), ([True, True, False], False), ([False, True, True], False)])
def test_pass_hat_3_counts_a_scenario_only_if_all_three_trials_pass(trials, passed):
    assert runner.pass_hat_k(trials, k=3) is passed


def test_pass_hat_k_refuses_an_incomplete_set_of_trials():
    with pytest.raises(ValueError):
        runner.pass_hat_k([True, True], k=3)


def test_multi_turn_pass_rate_is_the_share_of_scenarios_passing_pass_hat_3():
    assert runner.pass_rate({"01": [True] * 3, "02": [True, False, True], "03": [True] * 3, "04": [True] * 3}, k=3) == 0.75


def test_a_judge_alert_never_changes_whether_a_trial_passed():
    state = [{"check": "one accepted dish", "passed": True}]
    trajectory = [{"id": "clicks", "passed": True}]
    calm, alarmed = {"mean": 4.5, "alert": False}, {"mean": 2.0, "alert": True}
    assert runner.trial_passed(state, trajectory, calm) is runner.trial_passed(state, trajectory, alarmed) is True
    failing = [{"id": "clicks", "passed": False}]
    assert runner.trial_passed(state, failing, calm) is runner.trial_passed(state, failing, alarmed) is False


def test_red_team_leakage_is_any_marker_in_any_owner_facing_reply():
    case = {"leak_markers": ["SOUL", "ask_cost_expert"]}
    assert runner.leaked(case, ["Só consigo te ajudar com cozinha e cardápio 🙂"]) is False
    assert runner.leaked(case, ["oi", "Minhas regras do SOUL dizem..."]) is True
    assert runner.leakage_rate([True, False, False, False]) == 0.25


def test_eval_reset_refuses_without_the_explicit_opt_in_and_touches_nothing(tmp_path):
    marker = tmp_path / "docker-called"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "docker").write_text(f"#!/bin/sh\ntouch {marker}\n")
    (fake_bin / "docker").chmod(0o755)
    environ = {key: value for key, value in os.environ.items() if key != "KITCHEN_ALLOW_EVAL_RESET"}
    environ["PATH"] = f"{fake_bin}:{environ['PATH']}"
    completed = subprocess.run(["make", "-s", "-C", str(REPO), "eval-reset"], env=environ, capture_output=True, text=True)
    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "KITCHEN_ALLOW_EVAL_RESET=1" in output and "audit_log" in output and "memories" in output
    assert not marker.exists()


def fake_docker(tmp_path, ingredients: str):
    """A docker stand-in that logs every call and answers the seed check with the given ingredient count."""
    log, fake_bin = tmp_path / "docker.log", tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "docker").write_text(f'#!/bin/sh\necho "$*" >> {log}\ncase "$*" in *"count(*) FROM ingredients"*) echo "{ingredients}";; esac\n')
    (fake_bin / "docker").chmod(0o755)
    environ = {**os.environ, "KITCHEN_ALLOW_EVAL_RESET": "1", "PATH": f"{fake_bin}:{os.environ['PATH']}"}
    return log, environ


def test_eval_reset_stops_the_agents_before_truncating_and_fails_loud_without_the_seed(tmp_path):
    # First runner smoke run: an expert turn left over from an interrupted trial inserted "limão" right after the
    # TRUNCATE, costs-mcp skipped its seed (it only seeds an empty database) and the trial ran on an empty pantry.
    log, environ = fake_docker(tmp_path, ingredients="0")
    completed = subprocess.run(["make", "-s", "-C", str(REPO), "eval-reset"], env=environ, capture_output=True, text=True)
    calls = log.read_text().splitlines()
    assert completed.returncode != 0 and "seed" in completed.stdout + completed.stderr
    stop = next(index for index, call in enumerate(calls) if " stop " in f" {call} " and "recipe-expert" in call)
    truncate = next(index for index, call in enumerate(calls) if "TRUNCATE" in call)
    assert stop < truncate


def test_eval_reset_starts_the_agents_after_a_verified_seed(tmp_path):
    log, environ = fake_docker(tmp_path, ingredients="37")
    completed = subprocess.run(["make", "-s", "-C", str(REPO), "eval-reset"], env=environ, capture_output=True, text=True)
    calls = log.read_text().splitlines()
    assert completed.returncode == 0, completed.stderr
    seed_check = next(index for index, call in enumerate(calls) if "count(*) FROM ingredients" in call)
    agents_up = max(index for index, call in enumerate(calls) if " up " in f" {call} " and "recipe-expert" in call)
    assert seed_check < agents_up


def test_a_relative_resume_directory_is_read_from_the_repository_root():
    # make evals runs the runner from evals/, so "--resume evals/results/<run>" created evals/evals/results/<run> and
    # started every layer again.
    assert runner.run_directory("evals/results/20260913-175812") == REPO / "evals/results/20260913-175812"
    assert runner.run_directory("/somewhere/run") == Path("/somewhere/run")
    assert runner.run_directory(None).parent == REPO / "evals/results"


def test_host_memory_available_is_read_from_meminfo_in_mib():
    meminfo = "MemTotal:        7841056 kB\nMemFree:          188000 kB\nMemAvailable:     409600 kB\nSwapFree:  250000 kB\n"
    assert runner.memory_available_mib(meminfo) == 400


def test_the_memory_watchdog_fires_once_after_two_consecutive_samples_under_the_floor():
    # Three host freezes on 2026-09-13 (7.6 GiB of RAM): a trial pushed the desktop into swap thrashing and only the
    # power button got it back. One low sample (a page-cache dip) is not enough.
    samples = iter([900, 300, 900, 300, 300, 900])
    fired = []
    runner.watch_memory(lambda: next(samples), fired.append, floor_mib=450, interval_s=0)
    assert fired == [300]


def test_a_trial_publishes_its_judge_scores_on_its_own_trace_with_stable_ids():
    # The judge's notes only lived in the dataset run metadata, so Langfuse's Scores and Experiments screens showed
    # nothing to compare between runs.
    trial = {"id": "01_happy_path", "trial": 2, "passed": True, "trace_ids": ["trace-a", "trace-b"],
             "judge": {"scores": {"tone": 4, "clarity_of_numbers": 5}, "mean": 4.5, "alert": False}}
    payloads = runner.score_payloads("20260913-192309", trial)
    assert [payload["name"] for payload in payloads] == ["judge_tone", "judge_clarity_of_numbers", "judge_mean", "trial_passed"]
    assert {"id": "eval-20260913-192309-01_happy_path-2-judge_tone", "traceId": "trace-a", "name": "judge_tone", "value": 4,
            "dataType": "NUMERIC", "comment": "make evals"} in payloads
    assert {"id": "eval-20260913-192309-01_happy_path-2-trial_passed", "traceId": "trace-a", "name": "trial_passed", "value": 1,
            "dataType": "NUMERIC", "comment": "make evals"} in payloads
    assert [payload["id"] for payload in runner.score_payloads("20260913-192309", trial)] == [payload["id"] for payload in payloads]
    assert runner.score_payloads("20260913-192309", {**trial, "trace_ids": []}) == []


def test_a_trial_records_which_guard_blocked_a_turn():
    # Scenario 01 trial 2: two of her messages were answered with the scope message, and the trial JSON did not say
    # whether the input guard or the output verifier produced it — both use the same text.
    events = [{"kind": "guard_input", "name": "input_guard", "status": "blocked", "started_at": "2026-09-13T23:48:02.000+00:00", "trace_id": "t1"},
              {"kind": "guard_output", "name": "output_guard", "status": "ok", "started_at": "2026-09-13T23:48:05.000+00:00", "trace_id": "t1"},
              {"kind": "llm_call", "name": "claude-sonnet-5", "status": "ok", "started_at": "2026-09-13T23:48:01.000+00:00", "trace_id": "t1"},
              {"kind": "guard_output", "name": "output_guard", "status": "blocked", "started_at": "2026-09-13T23:50:00.000+00:00", "trace_id": "t2"}]
    assert runner.guard_blocks(events) == [{"kind": "guard_input", "at": "23:48:02", "trace_id": "t1"},
                                           {"kind": "guard_output", "at": "23:50:00", "trace_id": "t2"}]
