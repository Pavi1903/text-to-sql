"""
Introspects the live Postgres schema so the LLM always has an accurate,
up-to-date picture of the database - no manual schema docs to keep in sync.
Works generically against whatever tables actually exist; nothing here is
hardcoded to a specific schema.
"""

import time
from dataclasses import dataclass, field

from app.config import settings
from app.database import get_pool

_CACHE_TTL_SECONDS = 300
_cache: dict = {"schema_text": None, "table_names": set(), "fetched_at": 0.0}


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool = False


@dataclass
class ForeignKeyInfo:
    column: str
    references_table: str
    references_column: str


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)


COLUMNS_QUERY = """
SELECT c.table_name, c.column_name, c.data_type, c.is_nullable,
       (pk.column_name IS NOT NULL) AS is_primary_key
FROM information_schema.columns c
LEFT JOIN (
    SELECT kcu.table_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name
     AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'PRIMARY KEY'
      AND tc.table_schema = $1
) pk ON pk.table_name = c.table_name AND pk.column_name = c.column_name
WHERE c.table_schema = $1
ORDER BY c.table_name, c.ordinal_position;
"""

FOREIGN_KEYS_QUERY = """
SELECT
    tc.table_name AS source_table,
    kcu.column_name AS source_column,
    ccu.table_name AS target_table,
    ccu.column_name AS target_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu
  ON tc.constraint_name = ccu.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = $1;
"""


async def _fetch_live_schema() -> dict[str, TableInfo]:
    pool = get_pool()
    tables: dict[str, TableInfo] = {}
    schema_name = settings.db_schema

    async with pool.acquire() as conn:
        col_rows = await conn.fetch(COLUMNS_QUERY, schema_name)
        fk_rows = await conn.fetch(FOREIGN_KEYS_QUERY, schema_name)

    for row in col_rows:
        t = tables.setdefault(row["table_name"], TableInfo(name=row["table_name"]))
        t.columns.append(
            ColumnInfo(
                name=row["column_name"],
                data_type=row["data_type"],
                is_nullable=(row["is_nullable"] == "YES"),
                is_primary_key=row["is_primary_key"],
            )
        )

    for row in fk_rows:
        t = tables.get(row["source_table"])
        if t is not None:
            t.foreign_keys.append(
                ForeignKeyInfo(
                    column=row["source_column"],
                    references_table=row["target_table"],
                    references_column=row["target_column"],
                )
            )

    allowed = settings.allowed_tables_set
    if allowed:
        tables = {name: info for name, info in tables.items() if name in allowed}

    return tables


def _render_schema_text(tables: dict[str, TableInfo], schema_name: str) -> str:
    lines = []
    for table in tables.values():
        qualified_name = f"{schema_name}.{table.name}"
        lines.append(f"TABLE {qualified_name} (")
        for col in table.columns:
            pk = " PRIMARY KEY" if col.is_primary_key else ""
            nullable = "" if col.is_nullable else " NOT NULL"
            lines.append(f"  {col.name} {col.data_type}{pk}{nullable}")
        for fk in table.foreign_keys:
            lines.append(
                f"  FOREIGN KEY ({fk.column}) REFERENCES "
                f"{schema_name}.{fk.references_table}({fk.references_column})"
            )
        lines.append(")")
    return "\n".join(lines)


async def get_schema_context(force_refresh: bool = False) -> tuple[str, set[str]]:
    """Returns (schema_text_for_prompt, set_of_valid_table_names)."""
    now = time.time()
    if (
        not force_refresh
        and _cache["schema_text"] is not None
        and now - _cache["fetched_at"] < _CACHE_TTL_SECONDS
    ):
        return _cache["schema_text"], _cache["table_names"]

    tables = await _fetch_live_schema()
    schema_text = _render_schema_text(tables, settings.db_schema)

    _cache["schema_text"] = schema_text
    _cache["table_names"] = set(tables.keys())
    _cache["fetched_at"] = now

    return schema_text, _cache["table_names"]