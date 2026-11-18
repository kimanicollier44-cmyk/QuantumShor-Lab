#!/usr/bin/env python3
"""QuantumShor-Lab - educational Shor's algorithm / period-finding lab.

by Darion Kellar

Pure Python standard library. Zero dependencies. Zero network.
Education only - and the central lesson is stated up front:

  * Shor's algorithm is really two algorithms bolted together: a
    quantum period-finding subroutine (Hadamards, a modular-
    exponentiation unitary, and an inverse Quantum Fourier
    Transform) and a classical post-processing chain (continued
    fractions, then two gcd calls). This lab builds BOTH halves
    from scratch and runs them end to end on the labelled toy
    numbers 15 = 3 x 5 and 21 = 3 x 7.
  * Everything quantum here runs on a from-scratch statevector
    simulator written in this file: 2^n complex amplitudes, exact
    probabilities read off the state (no sampling noise), and a
    modular-exponentiation unitary built as an exact permutation
    of basis states by index arithmetic.
  * The simulator itself is classical and exponential: n qubits
    cost 2^n amplitudes, and this file says so wherever a size is
    printed. Factoring 15 on 4,096 amplitudes demonstrates the
    ALGORITHM's structure - it threatens no real cryptosystem,
    because a real one would need a quantum machine that does not
    exist here, running a circuit this laptop simulates only by
    paying exponential memory.
  * The failure cases are printed, not hidden: an odd period, or
    a^(r/2) = -1 (mod N), makes the classical step fail and the
    honest move is to pick another a. The lab's failure table is
    a first-class output, and its retry loop actually retries.

RSA-breaking, key-recovery, cryptanalysis, production, and
real-world speedup claims are permanent HOLD gates - with Gemini
Argon 4 Extended Thinking as DECIDER (names-only, tighten-only),
Muse as advisor (never overrides HOLD), and Google Flow
plan-only seats.
"""
import hashlib
import json
import math
import sys

# ---------------------------------------------------------------- constants
VERSION = "1.0.0"

# Labelled toy cap. The full quantum pipeline runs only for
# N <= TOY_N_CAP: N = 21 already needs 9 + 5 = 14 qubits, i.e.
# 16,384 amplitudes, and the cap is a statement about what this
# classical simulator can carry honestly, not about Shor's
# algorithm (whose register grows only polynomially on a real
# quantum machine - that contrast is the lesson).
TOY_N_CAP = 21

# The demo book: (a, N) pairs exercised end to end.
DEMO_SUCCESS = [(7, 15), (2, 21)]
DEMO_FAILURES = [(14, 15), (4, 21), (5, 21), (6, 21)]

# ---------------------------------------------------------------- HOLD gates
HOLD_GATES = {
    "rsa_breaking_claim": "HOLD - no claim of breaking RSA; factoring 15 and 21 on a classical simulator demonstrates an algorithm's structure, not an attack",
    "real_key_recovery": "HOLD - no recovering real private keys, seed phrases, or credentials of any kind",
    "ecc_discrete_log_attack_claim": "HOLD - no claim of attacking elliptic-curve or discrete-log systems in deployment; the period-finding idea is taught, not weaponised",
    "intercept_decrypt_claim": "HOLD - no decrypting intercepted, captured, or anyone else's traffic or files",
    "production_cryptanalysis_use": "HOLD - no production cryptanalysis use; this is a teaching simulator with a toy cap of N = 21",
    "quantum_hardware_claim": "HOLD - no claim of access to, or results from, real quantum hardware; every run here is a classical simulation",
    "real_world_speedup_claim": "HOLD - no claim of practical speedup; the simulator pays 2^n amplitudes, and the speedup statement is about gate counts on a machine that does not exist here",
    "password_or_hash_cracking": "HOLD - no live password, PIN, or hash cracking; nothing here searches a credential space",
    "financial_system_attack_claim": "HOLD - no attacking banks, payment networks, exchanges, or financial infrastructure",
    "surveillance_claim": "HOLD - no surveillance, tracking, or intelligence-collection use or claim",
    "benchmark_vendor_claim": "HOLD - no vendor or hardware benchmark claim; counts are against this file's own classical baselines",
    "patent_or_priority_claim": "HOLD - no patent, priority, or first-discovery claim; this is Shor's 1994 algorithm, taught from the textbook",
    "investment_claim": "HOLD - no investment claim; a factoring demo is not a prospectus",
    "certification_claim": "HOLD - no certification, accreditation, or compliance claim of any kind",
}


def gate(action):
    """Return 'HOLD' if the action is gated, else 'PROCEED' (sandbox sim)."""
    return "HOLD" if action in HOLD_GATES else "PROCEED"


# ================================================================ 1. Statevector simulator
# A state is a list of 2^n complex amplitudes. Qubit q is bit q of
# the basis index (little-endian). Gates are applied by index
# arithmetic - no matrices are ever materialised, and no library
# does the work. Norm is preserved by construction and asserted
# in the checks.

SQRT2_INV = 1.0 / math.sqrt(2.0)


def zero_state(n):
    """The |0...0> state on n qubits."""
    state = [0j] * (1 << n)
    state[0] = 1.0 + 0j
    return state


def apply_single(state, q, m00, m01, m10, m11):
    """Apply a 1-qubit gate (matrix [[m00, m01], [m10, m11]]) to qubit q."""
    step = 1 << q
    for base in range(0, len(state), step * 2):
        for off in range(step):
            i0 = base + off
            i1 = i0 + step
            a0, a1 = state[i0], state[i1]
            state[i0] = m00 * a0 + m01 * a1
            state[i1] = m10 * a0 + m11 * a1
    return state


def apply_h(state, q):
    return apply_single(state, q, SQRT2_INV, SQRT2_INV, SQRT2_INV, -SQRT2_INV)


def apply_x(state, q):
    return apply_single(state, q, 0.0, 1.0, 1.0, 0.0)


def apply_z(state, q):
    return apply_single(state, q, 1.0, 0.0, 0.0, -1.0)


def apply_cnot(state, control, target):
    """Flip `target` wherever `control` is 1."""
    for i in range(len(state)):
        if (i >> control) & 1 and not (i >> target) & 1:
            j = i | (1 << target)
            state[i], state[j] = state[j], state[i]
    return state


def apply_swap(state, q1, q2):
    """Swap qubits q1 and q2."""
    if q1 == q2:
        return state
    for i in range(len(state)):
        b1 = (i >> q1) & 1
        b2 = (i >> q2) & 1
        if b1 and not b2:
            j = i ^ (1 << q1) ^ (1 << q2)
            state[i], state[j] = state[j], state[i]
    return state


def apply_cp(state, q1, q2, angle):
    """Controlled phase: multiply by e^{i*angle} where both bits are 1."""
    phase = complex(math.cos(angle), math.sin(angle))
    mask = (1 << q1) | (1 << q2)
    for i in range(len(state)):
        if i & mask == mask:
            state[i] *= phase
    return state


def probabilities(state):
    return [abs(a) ** 2 for a in state]


def state_norm(state):
    return math.sqrt(sum(abs(a) ** 2 for a in state))


def bell_state():
    """H then CNOT on two qubits: (|00> + |11>) / sqrt(2)."""
    state = zero_state(2)
    apply_h(state, 0)
    apply_cnot(state, 0, 1)
    return state


# ================================================================ 2. Quantum Fourier Transform
# The QFT is built from scratch: Hadamards, controlled phase
# rotations R_m = diag(1, e^{2 pi i / 2^m}), and a final layer of
# swaps - the textbook circuit. `qubits` is ordered LEAST
# significant first: qubits[j] carries significance 2^j of the
# register value. The transform is
#   QFT|x> = (1/sqrt(Q)) * sum_y e^{+2 pi i x y / Q} |y>,  Q = 2^t,
# and the checks grade the circuit against that definition,
# computed directly, on every basis state of a 3-qubit register.

def qft_ops(qubits, inverse=False):
    """The gate list for the QFT (or its inverse) on `qubits`."""
    t = len(qubits)
    wires = list(reversed(qubits))  # most significant first
    ops = []
    for i in range(t):
        ops.append(("H", wires[i]))
        for j in range(i + 1, t):
            ops.append(("CP", wires[i], wires[j], math.pi / (2 ** (j - i))))
    for i in range(t // 2):
        ops.append(("SWAP", wires[i], wires[t - 1 - i]))
    if inverse:
        flipped = []
        for op in reversed(ops):
            if op[0] == "CP":
                flipped.append(("CP", op[1], op[2], -op[3]))
            else:
                flipped.append(op)
        ops = flipped
    return ops


def apply_qft(state, qubits, inverse=False):
    """Apply the QFT (or inverse QFT) to the given qubits of `state`."""
    for op in qft_ops(qubits, inverse=inverse):
        if op[0] == "H":
            apply_h(state, op[1])
        elif op[0] == "CP":
            apply_cp(state, op[1], op[2], op[3])
        else:
            apply_swap(state, op[1], op[2])
    return state


def direct_qft_amplitude(x, y, size):
    """The definition, computed directly: e^{+2 pi i x y / Q} / sqrt(Q)."""
    angle = 2.0 * math.pi * x * y / size
    return complex(math.cos(angle), math.sin(angle)) / math.sqrt(size)


def periodic_state(t, period, offset):
    """(1/sqrt(m)) * sum_k |offset + k*period> on t qubits.

    Requires offset < period and period * m <= 2^t with the terms
    exactly filling the register when period divides 2^t.
    """
    size = 1 << t
    state = [0j] * size
    terms = list(range(offset, size, period))
    amp = 1.0 / math.sqrt(len(terms))
    for x in terms:
        state[x] = amp
    return state


# ================================================================ 3. Modular exponentiation
# The oracle U: |x>|y> -> |x>|y * a^x mod N> for y < N, identity
# on the y >= N padding of the work register. Multiplication by
# a^x is a bijection on Z_N exactly when gcd(a, N) = 1, so U is
# an exact permutation of basis states - applied by index
# arithmetic, moving amplitudes without touching their values.
# Starting the work register at |1> gives |x>|a^x mod N>.

def work_bits(N):
    """Bits needed to hold a value < N."""
    return max(1, (N - 1).bit_length())


def control_bits(N):
    """t with Q = 2^t >= N^2 (Shor's register sizing, labelled)."""
    return math.ceil(2.0 * math.log2(N))


def modexp_permutation(a, N, t, w):
    """perm[i] = j means basis state |i> maps to |j> under U.

    Index layout: index = (x << w) | y, x the control value
    (t bits), y the work value (w bits).
    """
    if math.gcd(a, N) != 1:
        raise ValueError("modexp unitary needs gcd(a, N) = 1")
    perm = [0] * (1 << (t + w))
    mask = (1 << w) - 1
    for i in range(len(perm)):
        x = i >> w
        y = i & mask
        if y < N:
            y = (y * pow(a, x, N)) % N
        perm[i] = (x << w) | y
    return perm


def apply_permutation(state, perm):
    """new_state[perm[i]] = state[i] - an exact unitary by construction."""
    out = [0j] * len(state)
    for i, amp in enumerate(state):
        if amp != 0j:
            out[perm[i]] = amp
    return out


def modexp_sequence(a, N, count):
    """[a^0 mod N, a^1 mod N, ..., a^(count-1) mod N] - the period
    is visible in this classical sequence before any qubit moves."""
    return [pow(a, x, N) for x in range(count)]


def classical_order(a, N):
    """Smallest r >= 1 with a^r = 1 (mod N), by direct search.

    This is the classical yardstick: the quantum pipeline must
    recover the same r from measurement peaks + continued
    fractions, and the checks hold it to that.
    """
    if math.gcd(a, N) != 1:
        return None
    r = 1
    value = a % N
    while value != 1:
        value = (value * a) % N
        r += 1
        if r > N + 1:  # cannot happen for coprime a; a guard, not a path
            return None
    return r


# ================================================================ 4. Continued fractions
# The classical bridge from a measured y to the period. y/Q is
# close to some k/r with r < N; the convergents of y/Q are the
# best rational approximations with small denominators, and one
# of them has denominator r (or a divisor of r - the multiples
# fallback below exists for exactly that case, e.g. y = Q/2
# giving the convergent 1/2 when the true period is 6).

def cf_terms(num, den):
    """Continued-fraction terms of num/den via the Euclidean algorithm."""
    terms = []
    while den:
        terms.append(num // den)
        num, den = den, num % den
    return terms


def convergents(num, den):
    """All convergents (p, q) of num/den, simplest first."""
    out = []
    p_prev, p_cur = 0, 1
    q_prev, q_cur = 1, 0
    for term in cf_terms(num, den):
        p_prev, p_cur = p_cur, term * p_cur + p_prev
        q_prev, q_cur = q_cur, term * q_cur + q_prev
        out.append((p_cur, q_cur))
    return out


def recover_period(y, Q, a, N):
    """Recover the period of a^x mod N from a measured outcome y.

    First pass: the convergent denominators q of y/Q themselves
    (1 <= q < N). Second pass: the bounded multiples 2q and 3q -
    a convergent can land on a divisor of the true period (the
    classic case: y = Q/2 gives 1/2 when r = 6). The bound is
    the honesty line: with UNbounded multiples, the q = 1
    convergent would "recover" any period by scanning m = 1, 2,
    3, ... - which is classical order-finding wearing a quantum
    hat, and this lab does not wear it. Returns
    (r, convergent, multiple) or None.
    """
    if y == 0:
        return None
    dens = [(p, q) for (p, q) in convergents(y, Q) if 1 <= q < N]
    for m in (1, 2, 3):
        for (p, q) in dens:
            r = m * q
            if r < N and pow(a, r, N) == 1:
                return (r, (p, q), m)
    return None


# ================================================================ 5. The Shor pipeline
# One full run: Hadamards on the control register, the modexp
# permutation, the inverse QFT, then the EXACT outcome
# distribution read off the statevector (marginalising the work
# register). No sampling: the probabilities printed are the
# probabilities a perfect machine would sample from.

def outcome_distribution(a, N):
    """Run the quantum half; return (info, [(y, P(y)), ...]).

    info carries the register arithmetic: t, Q, w, total qubits,
    and the amplitude count 2^(t+w) - the exponential price tag,
    printed wherever a size is printed.
    """
    t = control_bits(N)
    w = work_bits(N)
    Q = 1 << t
    state = zero_state(t + w)
    apply_x(state, 0)  # work register := |1>
    for j in range(t):
        apply_h(state, w + j)
    state = apply_permutation(state, modexp_permutation(a, N, t, w))
    apply_qft(state, [w + j for j in range(t)], inverse=True)
    mask = (1 << w) - 1
    dist = [0.0] * Q
    for i, amp in enumerate(state):
        if amp != 0j:
            dist[i >> w] += abs(amp) ** 2
    info = {"t": t, "Q": Q, "w": w, "qubits": t + w,
            "amplitudes": 1 << (t + w)}
    return info, dist


def shor_run(a, N):
    """The full pipeline for one (a, N): quantum half + classical half.

    Returns a report dict. The factoring step follows the
    textbook: r must be even and a^(r/2) must not be -1 (mod N);
    both failures are reported as outcomes, not exceptions.
    """
    if math.gcd(a, N) != 1:
        return {"a": a, "N": N, "outcome": "not-coprime",
                "gcd_found": math.gcd(a, N),
                "note": "gcd(a, N) > 1: Shor needs a coprime base - "
                        "and the gcd itself is already a factor, "
                        "found classically before any qubit moves"}
    info, dist = outcome_distribution(a, N)
    peaks = sorted(((y, p) for y, p in enumerate(dist) if p > 0.01),
                   key=lambda row: (-row[1], row[0]))
    recovered = None
    used_peak = None
    for (y, p) in peaks:
        recovered = recover_period(y, info["Q"], a, N)
        if recovered is not None:
            used_peak = (y, p)
            break
    report = {"a": a, "N": N, **info,
              "peaks": [(y, round(p, 6)) for y, p in peaks[:8]],
              "peak_count_over_1pct": len(peaks)}
    if recovered is None:
        report.update({"outcome": "no-period-recovered", "period": None})
        return report
    r, convergent, multiple = recovered
    report.update({"period": r, "used_peak": used_peak[0],
                   "used_peak_probability": round(used_peak[1], 6),
                   "convergent": list(convergent),
                   "convergent_multiple": multiple})
    if r % 2 == 1:
        report.update({"outcome": "period-odd-retry", "half_pow_mod": None})
        return report
    half = pow(a, r // 2, N)
    report["half_pow_mod"] = half
    if half == N - 1:
        report.update({"outcome": "minus-one-retry"})
        return report
    f1 = math.gcd(half - 1, N)
    f2 = math.gcd(half + 1, N)
    factors = sorted({f for f in (f1, f2) if 1 < f < N})
    report.update({"outcome": "factored" if factors else "trivial-gcd",
                   "factors": factors})
    return report


def attempt_book():
    """The demo book, run end to end: two successes, then the
    failure table - odd period, a^(r/2) = -1 twice over, and a
    non-coprime base. Every entry is a real pipeline run (or, for
    the non-coprime row, the gcd check that precedes one)."""
    book = {}
    for (a, N) in DEMO_SUCCESS + DEMO_FAILURES:
        book[f"a{a}_N{N}"] = shor_run(a, N)
    return book


def retry_demo(N=15, candidates=(14, 7)):
    """The honest retry loop: try candidates in order, keep the
    failure receipts, stop at the first factored outcome."""
    attempts = []
    for a in candidates:
        report = shor_run(a, N)
        attempts.append({"a": a, "outcome": report["outcome"],
                         "period": report.get("period")})
        if report["outcome"] == "factored":
            attempts[-1]["factors"] = report["factors"]
            break
    return attempts


# ================================================================ 6. Classical baseline
# Trial division, with every divisibility test counted. At toy
# sizes it beats the quantum pipeline silly - 2 steps for both
# demo numbers - and the lab prints that too. The honest scaling
# statement: trial division costs ~sqrt(N) tests, Shor's quantum
# half costs polynomially many GATES in log N on a quantum
# machine, and this classical simulator pays 2^(t+w) amplitudes
# to imitate it. Three different cost models; the lab keeps them
# in three separate columns and never merges them into a
# "speedup" headline.

def trial_division(N):
    """Return (small_factor, co_factor, steps_counted)."""
    steps = 0
    d = 2
    while d * d <= N:
        steps += 1
        if N % d == 0:
            return (d, N // d, steps)
        d += 1
    return (N, 1, steps)


def classical_report():
    rows = {}
    for N in (15, 21, 33, 35, 49, 91, 221):
        f1, f2, steps = trial_division(N)
        rows[f"N{N}"] = {"factors": [f1, f2], "trial_steps": steps}
    return {"trial_division": rows,
            "scaling_note": "trial division ~ sqrt(N) counted tests; "
                            "Shor gate count is polynomial in log2(N) "
                            "on a quantum machine; this simulator pays "
                            "2^(t+w) amplitudes - three cost models, "
                            "never merged into one speedup number"}


# ================================================================ 7. kNN run-verdict classifier
# Features: (N size, r parity, a^(r/2) mod N). The training grid
# is generated by evaluating the lab's own policy inputs
# classically (gcd, classical order, half power) over a fixed
# (a, N) book - the classifier interpolates the policy, it does
# not replace the pipeline, and the checks verify it reproduces
# the policy on every grid row.

def verdict_label(N, a, r, half_pow):
    """The lab's verdict policy, applied in a fixed order:
    size first, then coprimality, then the classical-step tests."""
    if N > TOY_N_CAP:
        return "too-big-for-toy"
    if math.gcd(a, N) != 1:
        return "not-coprime"
    if r is None or r % 2 == 1 or half_pow == N - 1:
        return "period-odd-retry"
    return "factorable-by-shor-toy"


def run_features(N, a):
    """(N, r_parity_code, half_pow) for one (a, N), evaluated
    classically. r_parity_code: 0 even, 1 odd, -1 not applicable."""
    if math.gcd(a, N) != 1:
        return (N, -1, None)
    r = classical_order(a, N)
    if r % 2 == 1:
        return (N, 1, None)
    return (N, 0, pow(a, r // 2, N))


def _grid_book():
    pairs = []
    for N in (15, 21):
        for a in (1, 2, 4, 5, 6, 7, 8, 11, 13, 14, 16, 20):
            if a < N:
                pairs.append((a, N))
    for (a, N) in ((2, 33), (5, 33), (2, 35), (6, 35)):
        pairs.append((a, N))
    return pairs


def _training_grid():
    rows = []
    for (a, N) in _grid_book():
        features = run_features(N, a)
        r = classical_order(a, N) if math.gcd(a, N) == 1 else None
        half = features[2]
        rows.append((features, verdict_label(N, a, r, half)))
    return rows


TRAINING_GRID = _training_grid()


def _scaled(features):
    # N is weighted hardest (the size verdict dominates), parity
    # codes sit at 0 / 1 / 2 so the not-applicable cluster stands
    # apart from both parities, and the half power is scaled by N.
    N, parity_code, half_pow = features
    parity = {0: 0.0, 1: 1.0, -1: 2.0}[parity_code]
    half = (half_pow / N) if half_pow is not None else 0.0
    return (4.0 * N / 35.0, parity, 2.0 * half)


def classify_features(features, k=3):
    """kNN over the policy-labelled grid, deterministic tie-breaking."""
    target = _scaled(features)
    ranked = []
    for features, label in TRAINING_GRID:
        point = _scaled(features)
        dist = math.sqrt(sum((x - y) ** 2 for x, y in zip(target, point)))
        ranked.append((dist, features, label))
    ranked.sort(key=lambda row: (row[0], row[1][0], row[1][1],
                                 row[1][2] if row[1][2] is not None else -1))
    votes = {}
    for _, _, label in ranked[:k]:
        votes[label] = votes.get(label, 0) + 1
    priority = {"factorable-by-shor-toy": 0, "period-odd-retry": 1,
                "not-coprime": 2, "too-big-for-toy": 3}
    return sorted(votes.items(), key=lambda kv: (-kv[1], priority[kv[0]]))[0][0]


def classify_run(N, a, k=3):
    """Classify one (a, N) run by its classically evaluated features."""
    return classify_features(run_features(N, a), k=k)


def classifier_report():
    scenarios = {
        "a7_N15_headline": (15, 7),
        "a2_N21_headline": (21, 2),
        "a14_N15_minus_one": (15, 14),
        "a4_N21_odd_period": (21, 4),
        "a5_N21_minus_one": (21, 5),
        "a6_N21_not_coprime": (21, 6),
        "a2_N33_too_big": (33, 2),
    }
    return {name: classify_run(N, a)
            for name, (N, a) in scenarios.items()}


# ================================================================ 8. Advisory seats
def _trace(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def argon4_decide(topic="quantumshor-demo"):
    """Gemini Argon 4 DECIDER seat: MAP->MODEL->STRESS->DECIDE.

    Names-only keys, live calls 0, tighten-only: can add HOLDs, never lift one.
    """
    stages = ["MAP", "MODEL", "STRESS", "DECIDE"]
    payload = {"seat": "gemini-argon-4", "topic": topic, "stages": stages}
    return {
        "seat": "Gemini Argon 4 Extended Thinking",
        "role": "DECIDER",
        "pipeline": stages,
        "tiers": [2048, 8192, 32768],
        "key": "names-only (GEMINI_API_KEY name checked, value never read)",
        "live_calls": 0,
        "decision": "PROCEED - sandbox simulation only, all cryptanalysis gates stay HOLD",
        "can_override_hold": False,
        "trace_sha256_16": _trace(payload),
    }


def claude_advisor(topic="quantumshor-demo"):
    """Muse advisor seat: advises, can never override a HOLD."""
    return {
        "seat": "Muse",
        "role": "ADVISOR",
        "key": "names-only (MODEL_API_KEY name checked, value never read)",
        "live_calls": 0,
        "advice": "Say it in the first line of every report: this factors 15 and 21 by paying 2^n classical amplitudes, so it teaches the algorithm's shape and threatens nothing - then show the peaks, the convergent that recovered r, and the failure table with the same prominence as the factors.",
        "can_override_hold": False,
    }


def google_flow_plan():
    """Google Flow seat: plan-only, nothing rendered, nothing live."""
    return {
        "seat": "Google Flow",
        "role": "PLAN-ONLY",
        "shots": ["a control register blooming into uniform superposition",
                  "the modexp permutation braiding x into a^x mod N",
                  "an inverse QFT comb sharpening into period peaks",
                  "a continued-fraction ladder climbing from y/Q to r",
                  "two gcd gates opening on 3 x 5 while the odd-r run is sent back to retry"],
        "rendered": False,
        "live": 0,
    }


def brains_report():
    return {"decider": argon4_decide(), "advisor": claude_advisor(),
            "flow": google_flow_plan()}


# ================================================================ checks
def run_checks():
    c = []

    def chk(name, ok):
        c.append((name, bool(ok)))

    # 1. simulator basics
    st = zero_state(3)
    chk("zero_state_norm", abs(state_norm(st) - 1.0) < 1e-12)
    apply_h(st, 0)
    chk("hadamard_probabilities",
        all(abs(p - 0.5) < 1e-12 for p in probabilities(st)[:2])
        and probabilities(st)[2] == 0.0)
    bell = bell_state()
    chk("bell_state_probabilities",
        abs(probabilities(bell)[0] - 0.5) < 1e-12
        and abs(probabilities(bell)[3] - 0.5) < 1e-12
        and probabilities(bell)[1] == 0.0)
    st = zero_state(2)
    apply_x(st, 1)
    apply_cnot(st, 1, 0)
    chk("cnot_truth_table", probabilities(st)[3] == 1.0)
    st = zero_state(2)
    apply_x(st, 0)
    apply_swap(st, 0, 1)
    chk("swap_moves_amplitude", probabilities(st)[2] == 1.0)
    st = zero_state(2)
    apply_x(st, 0)
    apply_x(st, 1)
    apply_cp(st, 0, 1, math.pi)
    chk("controlled_phase_pi",
        abs(st[3] - (-1.0)) < 1e-12 and abs(st[0]) < 1e-12)

    # 2. QFT graded against its own definition
    t = 3
    size = 1 << t
    ok = True
    for x in range(size):
        st = zero_state(t)
        st[0] = 0j
        st[x] = 1.0 + 0j
        apply_qft(st, [0, 1, 2])
        for y in range(size):
            if abs(st[y] - direct_qft_amplitude(x, y, size)) > 1e-9:
                ok = False
    chk("qft_matches_direct_dft_t3", ok)
    st = periodic_state(4, 4, 1)
    before = list(st)
    apply_qft(st, [0, 1, 2, 3])
    apply_qft(st, [0, 1, 2, 3], inverse=True)
    chk("qft_inverse_roundtrip",
        all(abs(a - b) < 1e-9 for a, b in zip(st, before)))
    st = periodic_state(8, 4, 3)
    apply_qft(st, list(range(8)), inverse=True)
    probs = probabilities(st)
    chk("qft_periodic_peaks_exact_r4",
        all(abs(probs[y] - 0.25) < 1e-9 if y % 64 == 0
            else probs[y] < 1e-12 for y in range(256)))
    st = periodic_state(8, 8, 5)
    apply_qft(st, list(range(8)), inverse=True)
    probs = probabilities(st)
    chk("qft_periodic_peaks_exact_r8",
        all(abs(probs[y] - 0.125) < 1e-9 if y % 32 == 0
            else probs[y] < 1e-12 for y in range(256)))

    # 3. modexp unitary
    perm = modexp_permutation(7, 15, 8, 4)
    chk("modexp_is_bijection", sorted(perm) == list(range(len(perm))))
    st = zero_state(12)
    apply_x(st, 0)
    for j in range(8):
        apply_h(st, 4 + j)
    st = apply_permutation(st, perm)
    dist = {}
    for i, amp in enumerate(st):
        if amp != 0j:
            dist.setdefault(i & 15, 0.0)
            dist[i & 15] += abs(amp) ** 2
    chk("modexp_entangled_work_distribution",
        set(dist) == {1, 4, 7, 13}
        and all(abs(p - 0.25) < 1e-9 for p in dist.values()))
    chk("modexp_sequence_shows_period",
        modexp_sequence(7, 15, 9) == [1, 7, 4, 13, 1, 7, 4, 13, 1])
    chk("register_sizing", control_bits(15) == 8 and control_bits(21) == 9
        and work_bits(15) == 4 and work_bits(21) == 5)

    # 4. continued fractions
    chk("cf_terms_85_512", cf_terms(85, 512) == [0, 6, 42, 2])
    chk("convergents_include_1_over_6",
        (1, 6) in convergents(85, 512))
    chk("convergents_64_256", (1, 4) in convergents(64, 256))
    chk("recover_period_from_64", recover_period(64, 256, 7, 15)[0] == 4)
    chk("recover_period_from_256_needs_multiple",
        recover_period(256, 512, 2, 21)[0] == 6
        and recover_period(256, 512, 2, 21)[1] == (1, 2)
        and recover_period(256, 512, 2, 21)[2] == 3)
    chk("recover_period_zero_outcome_none",
        recover_period(0, 256, 7, 15) is None)

    # 5. classical yardsticks
    chk("classical_orders",
        classical_order(7, 15) == 4 and classical_order(2, 21) == 6
        and classical_order(14, 15) == 2 and classical_order(4, 21) == 3
        and classical_order(5, 21) == 6)
    chk("trial_division_counts",
        trial_division(15) == (3, 5, 2) and trial_division(21) == (3, 7, 2)
        and trial_division(49) == (7, 7, 6))

    # 6. the full pipeline, end to end
    run = shor_run(7, 15)
    chk("pipeline_15_recovers_period",
        run["period"] == 4 and run["outcome"] == "factored")
    chk("pipeline_15_factors", run["factors"] == [3, 5])
    chk("pipeline_15_peak_probability",
        abs(run["used_peak_probability"] - 0.25) < 1e-6)
    chk("pipeline_15_sizes", run["Q"] == 256 and run["amplitudes"] == 4096)
    run = shor_run(2, 21)
    chk("pipeline_21_recovers_period",
        run["period"] == 6 and run["outcome"] == "factored")
    chk("pipeline_21_factors", run["factors"] == [3, 7])
    chk("pipeline_21_sizes", run["Q"] == 512 and run["amplitudes"] == 16384)
    chk("pipeline_21_peak_probability_high",
        run["used_peak_probability"] > 0.10)
    run = shor_run(14, 15)
    chk("pipeline_minus_one_failure",
        run["period"] == 2 and run["half_pow_mod"] == 14
        and run["outcome"] == "minus-one-retry")
    run = shor_run(4, 21)
    chk("pipeline_odd_period_failure",
        run["period"] == 3 and run["outcome"] == "period-odd-retry")
    run = shor_run(5, 21)
    chk("pipeline_21_minus_one_failure",
        run["period"] == 6 and run["half_pow_mod"] == 20
        and run["outcome"] == "minus-one-retry")
    run = shor_run(6, 21)
    chk("pipeline_not_coprime", run["outcome"] == "not-coprime"
        and run["gcd_found"] == 3)
    attempts = retry_demo()
    chk("retry_loop_keeps_receipts",
        [a["outcome"] for a in attempts] == ["minus-one-retry", "factored"]
        and attempts[-1]["factors"] == [3, 5])

    # 7. classifier - labels come from the lab's own policy
    rep = classifier_report()
    chk("classifier_headline_15", rep["a7_N15_headline"]
        == "factorable-by-shor-toy")
    chk("classifier_headline_21", rep["a2_N21_headline"]
        == "factorable-by-shor-toy")
    chk("classifier_minus_one_retry", rep["a14_N15_minus_one"]
        == "period-odd-retry")
    chk("classifier_odd_period_retry", rep["a4_N21_odd_period"]
        == "period-odd-retry")
    chk("classifier_21_minus_one_retry", rep["a5_N21_minus_one"]
        == "period-odd-retry")
    chk("classifier_not_coprime", rep["a6_N21_not_coprime"] == "not-coprime")
    chk("classifier_too_big", rep["a2_N33_too_big"] == "too-big-for-toy")
    chk("classifier_matches_policy_on_grid",
        all(classify_features(f) == label for f, label in TRAINING_GRID))

    # gates + seats
    chk("hold_gates_14", len(HOLD_GATES) == 14
        and all(v.startswith("HOLD") for v in HOLD_GATES.values()))
    chk("gate_rsa_hold", gate("rsa_breaking_claim") == "HOLD")
    chk("gate_key_recovery_hold", gate("real_key_recovery") == "HOLD")
    chk("gate_hardware_hold", gate("quantum_hardware_claim") == "HOLD")
    chk("gate_speedup_hold", gate("real_world_speedup_claim") == "HOLD")
    chk("gate_sandbox_proceed", gate("run_simulation") == "PROCEED")
    brains = brains_report()
    chk("argon4_no_override", brains["decider"]["can_override_hold"] is False
        and brains["decider"]["seat"]
        == "Gemini Argon 4 Extended Thinking")
    chk("claude_no_override", brains["advisor"]["can_override_hold"] is False)
    chk("flow_plan_only", brains["flow"]["rendered"] is False
        and brains["flow"]["live"] == 0)
    return c


# ================================================================ CLI / demo
def _print_run(report):
    a, N = report["a"], report["N"]
    if report["outcome"] == "not-coprime":
        print(f"    a={a} N={N}: NOT COPRIME - gcd = {report['gcd_found']} "
              f"(a factor, found classically; no quantum run)")
        return
    print(f"    a={a} N={N}: t={report['t']} Q={report['Q']} "
          f"w={report['w']} qubits={report['qubits']} "
          f"amplitudes={report['amplitudes']}")
    print(f"      peaks (y, P): {report['peaks']}")
    if report.get("period") is not None:
        print(f"      peak y={report['used_peak']} (P="
              f"{report['used_peak_probability']}) -> convergent "
              f"{report['convergent'][0]}/{report['convergent'][1]}"
              f" x{report['convergent_multiple']} -> r = {report['period']}")
    if report["outcome"] == "factored":
        print(f"      a^(r/2) mod N = {report['half_pow_mod']} -> "
              f"gcd(-1) x gcd(+1) -> FACTORS {report['factors']} "
              f"({report['factors'][0]} x {report['factors'][1]} = {N})")
    elif report["outcome"] == "period-odd-retry":
        print(f"      r is ODD - a^(r/2) is not an integer power: "
              f"RETRY with another a")
    elif report["outcome"] == "minus-one-retry":
        print(f"      a^(r/2) mod N = {report['half_pow_mod']} = -1 (mod N): "
              f"gcd gives only trivial factors: RETRY with another a")


def demo():
    print("=" * 68)
    print("QuantumShor-Lab - Shor's algorithm & period-finding lab")
    print("by Darion Kellar | MIT | pure stdlib | zero network | EDUCATION ONLY")
    print("=" * 68)
    print("\n[1] THE HONEST CORE - what this does and does not do")
    print("    Shor = quantum period finding + classical post-processing.")
    print("    This lab builds both halves from scratch and factors the")
    print("    labelled toys 15 = 3 x 5 and 21 = 3 x 7 end to end. The")
    print("    simulator pays 2^n classical amplitudes to do it - it")
    print("    teaches the algorithm's structure and threatens nothing.")
    print("\n[2] Modular exponentiation - the period is in the sequence")
    print(f"    7^x mod 15: {modexp_sequence(7, 15, 9)}  (period 4)")
    print(f"    2^x mod 21: {modexp_sequence(2, 21, 8)}  (period 6)")
    print("    The unitary is an exact permutation |x>|y> -> |x>|y*a^x mod N>;")
    print("    applied to |x>|1> it writes the whole sequence into amplitudes.")
    print("\n[3] QFT verification - a periodic state peaks at multiples of Q/r")
    st = periodic_state(8, 4, 3)
    apply_qft(st, list(range(8)), inverse=True)
    probs = probabilities(st)
    print("    period 4, Q=256: P(y) = 0.25 exactly at y in "
          f"{[y for y in range(256) if probs[y] > 0.01]}, ~0 elsewhere")
    print("\n[4] Headline run - factor 15 with a = 7")
    _print_run(shor_run(7, 15))
    print("\n[5] Second run - factor 21 with a = 2")
    _print_run(shor_run(2, 21))
    print("\n[6] The failure table - printed, not hidden")
    for (a, N) in DEMO_FAILURES:
        _print_run(shor_run(a, N))
    print("    Retry loop on N=15 with candidates (14, 7):")
    for attempt in retry_demo():
        print(f"      a={attempt['a']}: {attempt['outcome']}"
              + (f" -> {attempt['factors']}" if "factors" in attempt else ""))
    print("\n[7] Classical baseline - counted, and honestly faster here")
    for name, row in classical_report()["trial_division"].items():
        print(f"    {name}: factors {row['factors']} in "
              f"{row['trial_steps']} counted trial-division steps")
    print("    Trial division ~ sqrt(N) tests; Shor's gate count is")
    print("    polynomial in log2(N) on a quantum machine; this simulator")
    print("    pays 2^(t+w) amplitudes. Three cost models, never merged.")
    print("\n[8] Run-verdict classifier (TinyML kNN, labels from lab policy)")
    for name, label in classifier_report().items():
        print(f"    {name:28s} -> {label}")
    print("\n[9] Advisory seats")
    brains = brains_report()
    print(f"    decider: {brains['decider']['decision']} "
          f"trace={brains['decider']['trace_sha256_16']}")
    print(f"    advisor can_override_hold = {brains['advisor']['can_override_hold']}")
    print(f"    flow rendered = {brains['flow']['rendered']} "
          f"live = {brains['flow']['live']}")
    print(f"\n[10] HOLD gates: {len(HOLD_GATES)}")
    for key in HOLD_GATES:
        print(f"    HOLD  {key}")
    checks = run_checks()
    passed = sum(1 for _, ok in checks if ok)
    print(f"\nCHECKS {passed}/{len(checks)}")
    for name, ok in checks:
        if not ok:
            print(f"    FAIL {name}")
    verdict = "PROCEED" if passed == len(checks) else "HOLD"
    print(f"VERDICT {verdict} (sandbox simulation only) | HOLD gates {len(HOLD_GATES)}")
    return 0 if passed == len(checks) else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == "demo":
        return demo()
    cmd = argv[0]
    if cmd == "checks":
        checks = run_checks()
        for name, ok in checks:
            print(f"{'PASS' if ok else 'FAIL'} {name}")
        print(f"CHECKS {sum(1 for _, ok in checks if ok)}/{len(checks)}")
        return 0 if all(ok for _, ok in checks) else 1
    if cmd == "modexp":
        a = int(argv[1]) if len(argv) > 1 else 7
        N = int(argv[2]) if len(argv) > 2 else 15
        print(json.dumps({"a": a, "N": N,
                          "sequence": modexp_sequence(a, N, 2 * N),
                          "classical_order": classical_order(a, N)},
                         indent=2, sort_keys=True))
        return 0
    if cmd == "qft":
        t = int(argv[1]) if len(argv) > 1 else 8
        period = int(argv[2]) if len(argv) > 2 else 4
        offset = int(argv[3]) if len(argv) > 3 else 3
        st = periodic_state(t, period, offset)
        apply_qft(st, list(range(t)), inverse=True)
        probs = probabilities(st)
        peaks = {str(y): round(p, 6) for y, p in enumerate(probs) if p > 0.01}
        print(json.dumps({"t": t, "Q": 1 << t, "period": period,
                          "offset": offset, "peaks": peaks},
                         indent=2, sort_keys=True))
        return 0
    if cmd == "period":
        a = int(argv[1]) if len(argv) > 1 else 7
        N = int(argv[2]) if len(argv) > 2 else 15
        info, dist = outcome_distribution(a, N)
        peaks = sorted(((y, round(p, 6)) for y, p in enumerate(dist)
                        if p > 0.01), key=lambda row: (-row[1], row[0]))
        print(json.dumps({"a": a, "N": N, **info, "peaks": peaks},
                         indent=2, sort_keys=True))
        return 0
    if cmd == "factor":
        a = int(argv[1]) if len(argv) > 1 else 7
        N = int(argv[2]) if len(argv) > 2 else 15
        print(json.dumps(shor_run(a, N), indent=2, sort_keys=True))
        return 0
    if cmd == "classical":
        print(json.dumps(classical_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "classify":
        print(json.dumps(classifier_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "brains":
        print(json.dumps(brains_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "holds":
        for key, value in HOLD_GATES.items():
            print(f"{key}: {value}")
        return 0
    if cmd == "hold-demo":
        action = argv[1] if len(argv) > 1 else "rsa_breaking_claim"
        print(f"{action}: {HOLD_GATES.get(action, 'PROCEED - not gated')}")
        return 2 if gate(action) == "HOLD" else 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
