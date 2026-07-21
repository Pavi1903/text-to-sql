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
    cleaned = sql.strip().rstrip(";")

    if not cleaned:
        raise SQLValidationError("Empty SQL generated.")

    statements = sqlparse.parse(cleaned)
    if len(statements) != 1:
        raise SQLValidationError("Only a single SQL statement is allowed.")

    statement = statements[0]

    dml_tokens = [t for t in statement.tokens if t.ttype is DML]
    if not dml_tokens or dml_tokens[0].value.upper() != "SELECT":
        raise SQLValidationError("Only SELECT statements are allowed.")

    upper_sql = cleaned.upper()
    for word in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{word}\b", upper_sql):
            raise SQLValidationError(f"Forbidden keyword detected: {word}")

    if ";" in sql.strip().rstrip(";"):
        raise SQLValidationError("Multiple statements are not allowed.")
    if "--" in cleaned or "/*" in cleaned:
        raise SQLValidationError("SQL comments are not allowed.")

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
