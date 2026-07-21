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
