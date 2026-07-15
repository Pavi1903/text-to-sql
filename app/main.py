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


class NoCacheStaticFiles(StaticFiles):
    """Serves static files with caching disabled - useful while actively
    editing static/index.html during development, so changes show up on a
    normal refresh instead of needing a hard refresh / cache clear."""

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

# Wide open for local development. Lock this down (specific origins) before
# pointing the real frontend at this in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def catch_all_handler(request: Request, exc: Exception):
    # Ensures the frontend always gets JSON back, even for bugs we didn't
    # anticipate, instead of a plain-text 500 page that breaks res.json().
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

    schema_text, valid_tables = await get_schema_context()

    try:
        raw_sql = generate_sql(question, schema_text)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach the LLM to generate SQL: {e}",
        )

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

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            # Belt-and-braces: run inside a read-only transaction even
            # though the DB role itself should already be read-only.
            async with conn.transaction(readonly=True):
                records = await conn.fetch(safe_sql)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Query execution failed: {e} (SQL was: {safe_sql})",
        )

    rows = [dict(r) for r in records]

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
async def schema():
    """Debug endpoint - shows exactly what schema the LLM sees. Protect or
    remove this before exposing the API beyond your own machine, since it
    reveals your database structure."""
    schema_text, tables = await get_schema_context(force_refresh=True)
    return {"tables": sorted(tables), "schema_text": schema_text}


# Serves the test UI at http://localhost:8000/
app.mount("/", NoCacheStaticFiles(directory="static", html=True), name="static")
