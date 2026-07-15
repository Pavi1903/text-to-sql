"""
Regression test harness for the text-to-SQL chatbot.

Runs a list of (question, expected result) pairs against the live /query
endpoint and reports pass/fail. Use this after any prompt/schema change
to catch regressions before they reach a demo.

WORKFLOW:
    1. Ask a question in the browser, verify the answer is correct by
       cross-checking in pgAdmin (see PGADMIN_VERIFICATION.md)
    2. Once verified, add it to test_cases.json with the real, confirmed
       expected result
    3. Run this script any time you change llm_service.py, schema_service.py,
       or sql_validator.py, to make sure nothing broke

USAGE:
    Make sure the server is running (uvicorn app.main:app), then:
        python test_harness.py
"""

import json
import sys
import urllib.error
import urllib.request

API_URL = "http://127.0.0.1:8000/query"
TEST_CASES_FILE = "test_cases.json"


def run_query(question: str) -> dict:
    payload = json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            detail = body.get("detail", str(body))
        except Exception:
            detail = str(e)
        return {"error": True, "status": e.code, "detail": detail}
    except Exception as e:
        return {"error": True, "detail": str(e)}


def check_case(case: dict) -> tuple[bool, str]:
    question = case["question"]
    result = run_query(question)

    if result.get("error"):
        if case.get("expect_error"):
            return True, "OK (error expected)"
        return False, f"Request failed unexpectedly: {result.get('detail')}"

    if case.get("expect_error"):
        return False, "Expected this question to fail/error, but it succeeded"

    rows = result.get("rows", [])
    row_count = result.get("row_count", len(rows))
    generated_sql = result.get("generated_sql", "")

    if "expected_row_count" in case and row_count != case["expected_row_count"]:
        return False, (
            f"Expected exactly {case['expected_row_count']} rows, got "
            f"{row_count}. SQL: {generated_sql}"
        )

    if "expected_min_rows" in case and row_count < case["expected_min_rows"]:
        return False, (
            f"Expected at least {case['expected_min_rows']} rows, got "
            f"{row_count}. SQL: {generated_sql}"
        )

    if "expected_max_rows" in case and row_count > case["expected_max_rows"]:
        return False, (
            f"Expected at most {case['expected_max_rows']} rows, got "
            f"{row_count}. SQL: {generated_sql}"
        )

    # For aggregate questions (COUNT, SUM, AVG, etc.) the result is a
    # single row containing the value, not N rows - so "row count" isn't
    # what you want to check. Use expected_field_value to check the
    # actual value instead, e.g.:
    #   "expected_field_value": {"field": "count", "value": 7328}
    if "expected_field_value" in case:
        spec = case["expected_field_value"]
        field, expected_value = spec["field"], spec["value"]
        if not rows:
            return False, f"Expected a row with {field}={expected_value}, but got no rows. SQL: {generated_sql}"
        actual_value = rows[0].get(field)
        if actual_value != expected_value:
            return False, (
                f"Expected {field}={expected_value!r}, got {field}={actual_value!r}. "
                f"SQL: {generated_sql}"
            )

    rows_text = json.dumps(rows, default=str).lower()

    for needle in case.get("expected_contains", []):
        if needle.lower() not in rows_text:
            return False, (
                f"Expected to find '{needle}' in results but didn't. "
                f"SQL: {generated_sql}"
            )

    for needle in case.get("expected_not_contains", []):
        if needle.lower() in rows_text:
            return False, (
                f"Expected '{needle}' NOT in results but found it. "
                f"SQL: {generated_sql}"
            )

    return True, f"OK ({row_count} rows)"


def main():
    try:
        with open(TEST_CASES_FILE) as f:
            test_cases = json.load(f)
    except FileNotFoundError:
        print(f"'{TEST_CASES_FILE}' not found. Copy test_cases.example.json "
              f"to {TEST_CASES_FILE} and fill in real expected values first.")
        sys.exit(1)

    if not test_cases:
        print("No test cases defined yet. Add some to test_cases.json.")
        sys.exit(0)

    passed = 0
    failed = 0
    skipped = 0

    print(f"Running {len(test_cases)} test case(s) against {API_URL}\n")

    for case in test_cases:
        if case.get("skip"):
            print(f"[SKIP] - {case['question']}")
            skipped += 1
            continue

        question = case["question"]
        ok, message = check_case(case)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {question}")
        if not ok:
            print(f"       -> {message}")
        if ok:
            passed += 1
        else:
            failed += 1

    total = passed + failed
    print(f"\n{passed}/{total} passed" + (f" ({skipped} skipped)" if skipped else ""))

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()