"""
Deterministic safety net around the LLM's SQL output. This is the
rule-based half of the hybrid approach: the LLM decides *what* the query
is, this module decides whether it's *safe* to run.
"""

import re

import sqlparse
from sqlparse.sql import IdentifierList, Identifier
from sqlparse.tokens import Keyword, DML

FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "COPY", "CALL", "DO", "EXECUTE",
    "MERGE", "REPLACE", "VACUUM", "COMMENT", "LOCK",
}


class SQLValidationError(Exception):
    pass


def _extract_table_names(parsed_statement) -> set[str]:
    """
    Extracts table names referenced in FROM/JOIN clauses.

    Deliberately only looks at the token immediately following each
    FROM/JOIN keyword, rather than scanning forward until some stop-word
    (WHERE/ORDER BY/etc). The stop-word approach is fragile: sqlparse
    tokenizes "ORDER BY" as a single keyword token, not two, so a naive
    check for the literal string "ORDER" never matches and scanning
    continues past it - which previously caused a column reference in an
    ORDER BY clause (e.g. "ORDER BY f.sto") to be misread as a table
    name. Only looking at the token directly after FROM/JOIN sidesteps
    this class of bug entirely.
    """
    tables = set()
    tokens = list(parsed_statement.tokens)

    for idx, token in enumerate(tokens):
        is_from_or_join = token.ttype is Keyword and (
            token.value.upper() == "FROM" or "JOIN" in token.value.upper()
        )
        if not is_from_or_join:
            continue

        next_idx = idx + 1
        while next_idx < len(tokens) and tokens[next_idx].is_whitespace:
            next_idx += 1

        if next_idx >= len(tokens):
            continue

        nxt = tokens[next_idx]
        if isinstance(nxt, IdentifierList):
            for identifier in nxt.get_identifiers():
                tables.add(identifier.get_real_name())
        elif isinstance(nxt, Identifier):
            tables.add(nxt.get_real_name())

    return tables


def validate_and_sanitize(sql: str, allowed_tables: set[str], max_row_limit: int) -> str:
    """
    Raises SQLValidationError if the query is unsafe.
    Returns a (possibly modified) SQL string safe to execute.
    """
    cleaned = sql.strip().rstrip(";")

    if not cleaned:
        raise SQLValidationError("Empty SQL generated.")

    statements = sqlparse.parse(cleaned)
    if len(statements) != 1:
        raise SQLValidationError("Only a single SQL statement is allowed.")

    statement = statements[0]

    # Must be a SELECT
    dml_tokens = [t for t in statement.tokens if t.ttype is DML]
    if not dml_tokens or dml_tokens[0].value.upper() != "SELECT":
        raise SQLValidationError("Only SELECT statements are allowed.")

    # Reject forbidden keywords anywhere in the statement
    upper_sql = cleaned.upper()
    for word in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{word}\b", upper_sql):
            raise SQLValidationError(f"Forbidden keyword detected: {word}")

    # Reject multiple statements smuggled via semicolons/comments
    if ";" in sql.strip().rstrip(";"):
        raise SQLValidationError("Multiple statements are not allowed.")
    if "--" in cleaned or "/*" in cleaned:
        raise SQLValidationError("SQL comments are not allowed.")

    # Table allow-list check
    if allowed_tables:
        used_tables = _extract_table_names(statement)
        unknown = used_tables - allowed_tables
        if unknown:
            raise SQLValidationError(
                f"Query references disallowed or unknown tables: {unknown}"
            )

    limit_match = re.search(r"\bLIMIT\s+(\d+)\b", upper_sql)
    if limit_match:
        requested_limit = int(limit_match.group(1))
        if requested_limit > max_row_limit:
            cleaned = re.sub(
                r"\bLIMIT\s+\d+\b", f"LIMIT {max_row_limit}", cleaned, flags=re.IGNORECASE
            )
    else:
        cleaned = f"{cleaned}\nLIMIT {max_row_limit}"

    return cleaned