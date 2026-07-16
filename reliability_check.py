"""
Reliability check - asks the SAME question multiple times against the
live chatbot and reports what fraction of attempts pass a given check.

Useful for quantifying non-deterministic failure patterns (like a
hallucination that shows up sometimes but not always) with a real
number, instead of relying on "it seemed to work" / "it seemed broken"
from a single observation.

USAGE:
    Edit CASE_TO_CHECK and NUM_RUNS below, then:
        python reliability_check.py

Each run is a real call through the full pipeline (LLM -> validator ->
DB), so with a local model this can take a while - 10 runs at, say,
5-15 seconds each is a few minutes, not instant.
"""

import test_harness


CASE_TO_CHECK = {
    "question": "Which flights are delayed right now?",
    "sql_not_contains": ["allocation_start", "allocation_end"],
}

NUM_RUNS = 10


def main():
    passed = 0
    failed = 0
    failure_reasons = []

    print(f"Question: {CASE_TO_CHECK['question']!r}")
    print(f"Running {NUM_RUNS} times against {test_harness.API_URL}\n")

    for i in range(1, NUM_RUNS + 1):
        ok, message = test_harness.check_case(CASE_TO_CHECK)
        status = "PASS" if ok else "FAIL"
        print(f"[{i:>2}/{NUM_RUNS}] {status}" + ("" if ok else f"  -> {message}"))
        if ok:
            passed += 1
        else:
            failed += 1
            failure_reasons.append(message)

    pct = 100 * passed / NUM_RUNS
    print(f"\n{passed}/{NUM_RUNS} passed ({pct:.0f}% reliability on this check)")

    if failure_reasons:
        print("\nDistinct failure reasons seen:")
        for reason in set(failure_reasons):
            count = failure_reasons.count(reason)
            short = reason if len(reason) <= 160 else reason[:160] + "..."
            print(f"  ({count}x) {short}")


if __name__ == "__main__":
    main()