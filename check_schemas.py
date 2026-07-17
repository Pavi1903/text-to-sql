import asyncio
import asyncpg
from app.config import settings


async def main():
    conn = await asyncpg.connect(dsn=settings.database_url)

    rows = await conn.fetch("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name;
    """)

    if not rows:
        print("No tables found at all. This connection may not have SELECT "
              "permission granted on any table, or the database is empty.")
    else:
        print(f"Found {len(rows)} table(s):\n")
        current_schema = None
        for row in rows:
            if row["table_schema"] != current_schema:
                current_schema = row["table_schema"]
                print(f"\nSCHEMA: {current_schema}")
            print(f"  - {row['table_name']}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
