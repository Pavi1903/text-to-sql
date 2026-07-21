import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope
from pydantic import BaseModel

from app.config import settings
from app.database import init_pool, close_pool, get_pool
from app.schema_service import get_schema_context
from app.llm_service import generate_sql
from app.sql_validator import validate_and_sanitize, SQLValidationError

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("timing")


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="Airport Text-to-SQL API", lifespan=lifespan)

<<<<<<< HEAD
=======

>>>>>>> c25fdf3b4ec48ebcd684ce56aed678c8732cd9c3
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def catch_all_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": f"Unexpected server error: {exc}"})


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    question: str
    generated_sql: str
    rows: list[dict]
    row_count: int


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    t_start = time.perf_counter()

    schema_text, valid_tables = await get_schema_context()
    t_schema = time.perf_counter()

    try:
        raw_sql = generate_sql(question, schema_text)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach the LLM to generate SQL: {e}",
        )
    t_llm = time.perf_counter()

    if raw_sql.strip().upper() == "UNANSWERABLE":
        raise HTTPException(
            status_code=422,
            detail="This question can't be answered with the current database schema.",
        )

    try:
        safe_sql = validate_and_sanitize(
            raw_sql,
            allowed_tables=valid_tables if settings.allowed_tables_set else set(),
            max_row_limit=settings.max_row_limit,
        )
    except SQLValidationError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Generated query failed safety validation: {e} (SQL was: {raw_sql})",
        )
    t_validate = time.perf_counter()

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                records = await conn.fetch(safe_sql)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Query execution failed: {e} (SQL was: {safe_sql})",
        )

    t_db = time.perf_counter()

    rows = [dict(r) for r in records]

    logger.info(
        f"[TIMING] '{question[:50]}' | "
        f"schema={1000*(t_schema-t_start):.0f}ms | "
        f"llm={1000*(t_llm-t_schema):.0f}ms | "
        f"validate={1000*(t_validate-t_llm):.0f}ms | "
        f"db={1000*(t_db-t_validate):.0f}ms | "
        f"total={1000*(t_db-t_start):.0f}ms"
    )

    return QueryResponse(
        question=question,
        generated_sql=safe_sql,
        rows=rows,
        row_count=len(rows),
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/schema")
async def schema(tables: str | None = None):
    schema_text, all_tables = await get_schema_context(force_refresh=True)
    if tables:
        requested = {t.strip() for t in tables.split(",") if t.strip()}
        matched = requested & all_tables
        unmatched = requested - all_tables

        blocks = schema_text.split("TABLE ")
        filtered_blocks = [
            b for b in blocks
            if b and any(b.startswith(f"{settings.db_schema}.{name}") or b.startswith(f"{name}")
                          for name in matched)
        ]
        filtered_text = "TABLE " + "\nTABLE ".join(filtered_blocks) if filtered_blocks else ""

        return {
            "requested": sorted(requested),
            "matched": sorted(matched),
            "not_found": sorted(unmatched),
            "schema_text": filtered_text,
        }

    return {"tables": sorted(all_tables), "schema_text": schema_text}


<<<<<<< HEAD
app.mount("/", NoCacheStaticFiles(directory="static", html=True), name="static")
=======
app.mount("/", NoCacheStaticFiles(directory="static", html=True), name="static")
>>>>>>> c25fdf3b4ec48ebcd684ce56aed678c8732cd9c3
