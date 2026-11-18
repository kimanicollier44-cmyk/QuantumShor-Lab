"""Tests for QuantumShor-Lab: simulator, QFT, modexp, continued
fractions, the full Shor pipeline (success + failure table),
classical baselines, classifier, HOLD gates, determinism."""
import subprocess
import sys
from pathlib import Path

import main

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- simulator
def test_zero_state_and_hadamard():
    st = main.zero_state(3)
    assert abs(main.state_norm(st) - 1.0) < 1e-12
    main.apply_h(st, 0)
    probs = main.probabilities(st)
    assert abs(probs[0] - 0.5) < 1e-12 and abs(probs[1] - 0.5) < 1e-12
    assert probs[2] == 0.0


def test_bell_state():
    probs = main.probabilities(main.bell_state())
    assert abs(probs[0] - 0.5) < 1e-12 and abs(probs[3] - 0.5) < 1e-12
    assert probs[1] == 0.0 and probs[2] == 0.0


def test_cnot_and_swap():
    st = main.zero_state(2)
    main.apply_x(st, 1)
    main.apply_cnot(st, 1, 0)
    assert main.probabilities(st)[3] == 1.0
    st = main.zero_state(2)
    main.apply_x(st, 0)
    main.apply_swap(st, 0, 1)
    assert main.probabilities(st)[2] == 1.0


def test_controlled_phase():
    st = main.zero_state(2)
    main.apply_x(st, 0)
    main.apply_x(st, 1)
    main.apply_cp(st, 0, 1, main.math.pi)
    assert abs(st[3] - (-1.0)) < 1e-12


# ---------------------------------------------------------------- QFT
def test_qft_matches_direct_dft():
    t, size = 3, 8
    for x in range(size):
        st = main.zero_state(t)
        st[0] = 0j
        st[x] = 1.0 + 0j
        main.apply_qft(st, [0, 1, 2])
        for y in range(size):
            assert abs(st[y] - main.direct_qft_amplitude(x, y, size)) < 1e-9


def test_qft_inverse_roundtrip():
    st = main.periodic_state(4, 4, 1)
    before = list(st)
    main.apply_qft(st, [0, 1, 2, 3])
    main.apply_qft(st, [0, 1, 2, 3], inverse=True)
    assert all(abs(a - b) < 1e-9 for a, b in zip(st, before))


def test_qft_periodic_peaks_r4():
    st = main.periodic_state(8, 4, 3)
    main.apply_qft(st, list(range(8)), inverse=True)
    probs = main.probabilities(st)
    for y in range(256):
        if y % 64 == 0:
            assert abs(probs[y] - 0.25) < 1e-9
        else:
            assert probs[y] < 1e-12


def test_qft_periodic_peaks_r8():
    st = main.periodic_state(8, 8, 5)
    main.apply_qft(st, list(range(8)), inverse=True)
    probs = main.probabilities(st)
    for y in range(256):
        if y % 32 == 0:
            assert abs(probs[y] - 0.125) < 1e-9
        else:
            assert probs[y] < 1e-12


# ---------------------------------------------------------------- modexp
def test_modexp_bijection():
    perm = main.modexp_permutation(7, 15, 8, 4)
    assert sorted(perm) == list(range(len(perm)))


def test_modexp_entangled_distribution():
    st = main.zero_state(12)
    main.apply_x(st, 0)
    for j in range(8):
        main.apply_h(st, 4 + j)
    st = main.apply_permutation(st, main.modexp_permutation(7, 15, 8, 4))
    dist = {}
    for i, amp in enumerate(st):
        if amp != 0j:
            dist[i & 15] = dist.get(i & 15, 0.0) + abs(amp) ** 2
    assert set(dist) == {1, 4, 7, 13}
    assert all(abs(p - 0.25) < 1e-9 for p in dist.values())


def test_modexp_sequence_and_sizing():
    assert main.modexp_sequence(7, 15, 9) == [1, 7, 4, 13, 1, 7, 4, 13, 1]
    assert main.control_bits(15) == 8 and main.control_bits(21) == 9
    assert main.work_bits(15) == 4 and main.work_bits(21) == 5


def test_modexp_rejects_non_coprime():
    try:
        main.modexp_permutation(6, 21, 9, 5)
    except ValueError:
        return
    raise AssertionError("expected ValueError for gcd(a, N) > 1")


# ---------------------------------------------------------------- continued fractions
def test_cf_terms_and_convergents():
    assert main.cf_terms(85, 512) == [0, 6, 42, 2]
    assert (1, 6) in main.convergents(85, 512)
    assert (1, 4) in main.convergents(64, 256)


def test_recover_period():
    assert main.recover_period(64, 256, 7, 15)[0] == 4
    r, conv, mult = main.recover_period(256, 512, 2, 21)
    assert r == 6 and conv == (1, 2) and mult == 3  # 1/2 needs its multiple
    assert main.recover_period(0, 256, 7, 15) is None


# ---------------------------------------------------------------- classical yardsticks
def test_classical_orders():
    assert main.classical_order(7, 15) == 4
    assert main.classical_order(2, 21) == 6
    assert main.classical_order(14, 15) == 2
    assert main.classical_order(4, 21) == 3
    assert main.classical_order(5, 21) == 6
    assert main.classical_order(6, 21) is None


def test_trial_division_counts():
    assert main.trial_division(15) == (3, 5, 2)
    assert main.trial_division(21) == (3, 7, 2)
    assert main.trial_division(49) == (7, 7, 6)


# ---------------------------------------------------------------- the pipeline
def test_pipeline_factors_15():
    run = main.shor_run(7, 15)
    assert run["outcome"] == "factored"
    assert run["period"] == 4
    assert run["factors"] == [3, 5]
    assert run["Q"] == 256 and run["amplitudes"] == 4096
    assert abs(run["used_peak_probability"] - 0.25) < 1e-6


def test_pipeline_factors_21():
    run = main.shor_run(2, 21)
    assert run["outcome"] == "factored"
    assert run["period"] == 6
    assert run["factors"] == [3, 7]
    assert run["Q"] == 512 and run["amplitudes"] == 16384
    assert run["used_peak_probability"] > 0.10


def test_pipeline_minus_one_failure():
    run = main.shor_run(14, 15)
    assert run["outcome"] == "minus-one-retry"
    assert run["period"] == 2 and run["half_pow_mod"] == 14


def test_pipeline_odd_period_failure():
    run = main.shor_run(4, 21)
    assert run["outcome"] == "period-odd-retry"
    assert run["period"] == 3


def test_pipeline_21_minus_one_failure():
    run = main.shor_run(5, 21)
    assert run["outcome"] == "minus-one-retry"
    assert run["period"] == 6 and run["half_pow_mod"] == 20


def test_pipeline_not_coprime():
    run = main.shor_run(6, 21)
    assert run["outcome"] == "not-coprime" and run["gcd_found"] == 3


def test_retry_loop_receipts():
    attempts = main.retry_demo()
    assert [a["outcome"] for a in attempts] == ["minus-one-retry", "factored"]
    assert attempts[-1]["factors"] == [3, 5]


# ---------------------------------------------------------------- classifier
def test_classifier_scenarios():
    rep = main.classifier_report()
    assert rep["a7_N15_headline"] == "factorable-by-shor-toy"
    assert rep["a2_N21_headline"] == "factorable-by-shor-toy"
    assert rep["a14_N15_minus_one"] == "period-odd-retry"
    assert rep["a4_N21_odd_period"] == "period-odd-retry"
    assert rep["a5_N21_minus_one"] == "period-odd-retry"
    assert rep["a6_N21_not_coprime"] == "not-coprime"
    assert rep["a2_N33_too_big"] == "too-big-for-toy"


def test_classifier_matches_policy_on_grid():
    for features, label in main.TRAINING_GRID:
        assert main.classify_features(features) == label


def test_verdict_policy_order():
    assert main.verdict_label(33, 2, 10, 32) == "too-big-for-toy"
    assert main.verdict_label(21, 6, None, None) == "not-coprime"
    assert main.verdict_label(21, 4, 3, None) == "period-odd-retry"
    assert main.verdict_label(15, 14, 2, 14) == "period-odd-retry"
    assert main.verdict_label(15, 7, 4, 4) == "factorable-by-shor-toy"


# ---------------------------------------------------------------- gates + seats + CLI
def test_hold_gates():
    assert len(main.HOLD_GATES) == 14
    assert all(v.startswith("HOLD") for v in main.HOLD_GATES.values())
    assert main.gate("rsa_breaking_claim") == "HOLD"
    assert main.gate("real_key_recovery") == "HOLD"
    assert main.gate("run_simulation") == "PROCEED"


def test_seats_never_override():
    brains = main.brains_report()
    assert brains["decider"]["seat"] == "Gemini Argon 4 Extended Thinking"
    assert brains["decider"]["can_override_hold"] is False
    assert brains["advisor"]["can_override_hold"] is False
    assert brains["flow"]["rendered"] is False and brains["flow"]["live"] == 0


def test_checks_all_pass():
    checks = main.run_checks()
    assert all(ok for _, ok in checks), [n for n, ok in checks if not ok]


def _run_cli(*args):
    return subprocess.run([sys.executable, str(ROOT / "main.py"), *args],
                          capture_output=True, text=True, timeout=300)


def test_cli_hold_demo_exits_2():
    proc = _run_cli("hold-demo")
    assert proc.returncode == 2
    assert "rsa_breaking_claim" in proc.stdout


def test_cli_demo_deterministic():
    first = _run_cli("demo")
    second = _run_cli("demo")
    assert first.returncode == 0 and second.returncode == 0
    assert first.stdout == second.stdout
    assert "CHECKS" in first.stdout and "VERDICT PROCEED" in first.stdout
