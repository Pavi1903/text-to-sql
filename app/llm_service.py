from ollama import Client

from app.config import settings

_client = Client(host=settings.ollama_host, timeout=60.0)

SYSTEM_PROMPT_TEMPLATE = """You are a PostgreSQL expert. Convert the user's \
natural language question into a single, valid, read-only PostgreSQL SELECT \
statement.

DATABASE SCHEMA:
{schema}

RULES:
- Output ONLY the raw SQL. No markdown fences, no explanation, no preamble.
- Only generate SELECT statements. Never generate INSERT, UPDATE, DELETE, \
DROP, ALTER, or any other write/DDL operation.
- Only reference tables and columns that exist in the schema above.
- Never use SELECT *. Always explicitly list only the specific columns \
that are relevant to answering the question. A question about "arrivals" \
does not need every column on the table - pick the handful that actually \
answer what was asked (e.g. flight number, relevant times, status).
- COMMON MISTAKES TO AVOID - these plausible-sounding column names do \
NOT exist, do not use them: on flight_legs, there is no "flight_number" \
column (the real column is "flight_no"), and there is no "status" \
column (the real column is "flight_status"). Before using ANY column \
name, verify it appears literally, character-for-character, in the \
DATABASE SCHEMA section above.
- Table names in the schema above are shown fully qualified as \
schema.table_name (e.g. server.flights) - always use that exact \
qualified form in FROM and JOIN clauses, not just the table name alone.
- Use explicit JOINs with ON clauses rather than implicit joins.
- Use PostgreSQL date/time functions (e.g. NOW(), CURRENT_DATE, \
date_trunc()) for date comparisons, not SQLite-style functions.
- For comparing dates/timestamps, use standard comparison operators only \
(=, <, >, <=, >=, BETWEEN). Never use containment operators like @> or \
<@ for date/time comparisons - those are only valid for arrays, ranges, \
or JSONB types, not timestamps.
- IMPORTANT: on flight_legs, there is a single scheduled-time column \
called "sto" used for BOTH arrivals and departures - which one it means \
depends on the "flight_nature" column, not on separate std/sta columns. \
Do not invent std/sta/eta_scheduled or similar columns on flight_legs; \
only use columns that literally appear in the schema for that table.
- IMPORTANT: flight_legs has separate columns for estimated/actual times \
depending on flight_nature. For flight_nature = 'departure', use etd \
(estimated) and atd (actual). For flight_nature = 'arrival', use eta \
(estimated) and ata (actual). Never select eta/ata for a departure-only \
query or etd/atd for an arrival-only query, unless the user explicitly \
asks to compare scheduled vs estimated vs actual times across both.
- If the question is ambiguous, make the most reasonable interpretation \
based on the schema rather than asking for clarification.
- If the question cannot be answered with the given schema, output exactly: \
UNANSWERABLE
- Always include a LIMIT clause (default 100) unless the user asks for an \
aggregate that returns a single row (e.g. COUNT, SUM, AVG).

KNOWN ENUM VALUES (use these exact strings, do not guess variants):
- flight_legs.flight_nature: 'arrival', 'departure'
- flight_legs.flight_status: 'scheduled', 'on_time', 'delayed', \
'boarding', 'final_call', 'gate_closed', 'departed', 'arrived', \
'diverted', 'cancelled', 'check_in'
"""


FEW_SHOT_EXAMPLES = [
    {
        "question": "Which parking stands are currently occupied?",
        "sql": (
            "SELECT DISTINCT s.stand_name, s.status, s.live_status "
            "FROM server.stands s "
            "JOIN server.flight_leg_stand_allocations a ON a.stand_id = s.id "
            "WHERE a.allocation_start <= NOW() "
            "AND (a.allocation_end IS NULL OR a.allocation_end > NOW()) "
            "LIMIT 100;"
        ),
    },
    {
        "question": "Which flights are currently delayed?",
        "sql": (
            "SELECT flight_no, sto, delay_in_mins FROM server.flight_legs "
            "WHERE flight_status = 'delayed' LIMIT 100;"
        ),
    },
    {
        "question": "List today's arrivals",
        "sql": (
            "SELECT flight_no, sto, eta, flight_status FROM server.flight_legs "
            "WHERE flight_nature = 'arrival' "
            "AND sto >= date_trunc('day', NOW()) "
            "AND sto < date_trunc('day', NOW()) + interval '1 day' "
            "ORDER BY sto LIMIT 100;"
        ),
    },
    {
        "question": "List today's departures",
        "sql": (
            "SELECT flight_no, sto, etd, atd, flight_status FROM server.flight_legs "
            "WHERE flight_nature = 'departure' "
            "AND sto >= date_trunc('day', NOW()) "
            "AND sto < date_trunc('day', NOW()) + interval '1 day' "
            "ORDER BY sto LIMIT 100;"
        ),
    },
    {
        "question": "Which flights are scheduled to depart in the next 2 hours?",
        "sql": (
            "SELECT flight_no, sto, flight_status FROM server.flight_legs "
            "WHERE flight_nature = 'departure' "
            "AND sto BETWEEN NOW() AND NOW() + interval '2 hours' "
            "ORDER BY sto LIMIT 100;"
        ),
    },
    {
        "question": "Which flights have been cancelled today?",
        "sql": (
            "SELECT flight_no, sto, flight_nature FROM server.flight_legs "
            "WHERE flight_status = 'cancelled' "
            "AND sto >= date_trunc('day', NOW()) "
            "AND sto < date_trunc('day', NOW()) + interval '1 day' "
            "LIMIT 100;"
        ),
    },
    {
        "question": "Which gates are in Terminal 1?",
        "sql": (
            "SELECT g.gate_name, g.status, g.allocatable FROM server.gates g "
            "JOIN server.terminals t ON g.terminal_id = t.id "
            "WHERE t.terminal_name ILIKE '%Terminal 1%' LIMIT 100;"
        ),
    },
    {
        "question": "Which stands are allocated to flight AI501?",
        "sql": (
            "SELECT s.stand_name, a.allocation_start, a.allocation_end "
            "FROM server.flight_leg_stand_allocations a "
            "JOIN server.flight_legs f ON a.flight_leg_id = f.id "
            "JOIN server.stands s ON a.stand_id = s.id "
            "WHERE f.flight_no = 'AI501' LIMIT 100;"
        ),
    },
    {
        "question": "List all ground handling agencies",
        "sql": (
            "SELECT gha_name, code, handler_type, status "
            "FROM server.ground_handling_agencies LIMIT 100;"
        ),
    },
    {
        "question": "Which seasonal schedules are currently active for arrivals?",
        "sql": (
            "SELECT flight_no_arr, sta, valid_from, valid_to "
            "FROM server.flight_schedules "
            "WHERE flight_no_arr IS NOT NULL "
            "AND CURRENT_DATE BETWEEN valid_from AND valid_to "
            "AND deleted = false "
            "LIMIT 100;"
        ),
    },
]


def _build_messages(system_prompt: str, question: str) -> list[dict]:
    messages = [{"role": "system", "content": system_prompt}]
    for example in FEW_SHOT_EXAMPLES:
        messages.append({"role": "user", "content": example["question"]})
        messages.append({"role": "assistant", "content": example["sql"]})
    messages.append({"role": "user", "content": question})
    return messages


def generate_sql(question: str, schema_text: str) -> str:
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema=schema_text)

    response = _client.chat(
        model=settings.ollama_model,
        messages=_build_messages(system_prompt, question),
        options={
            "temperature": 0,   #deterministic SQL generation,not creative
            "num_predict": 1000,
            "num_ctx": 8192,
        },
    )

    raw_sql = (response["message"]["content"] or "").strip()

    if raw_sql.startswith("```"):
        raw_sql = raw_sql.strip("`")
        if raw_sql.lower().startswith("sql"):
            raw_sql = raw_sql[3:].strip()

    return raw_sql