from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.database.base import Base
import src.models  # noqa: F401


def main() -> None:
    dialect = postgresql.dialect()
    statements = [
        "-- Generated from SQLAlchemy metadata by scripts/export_schema.py.",
        "-- Apply only through the reviewed Alembic migration workflow.",
    ]
    for table in Base.metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in table.indexes:
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
    output = ROOT_DIR / "database" / "schema.sql"
    output.write_text("\n\n".join(statements) + "\n", encoding="utf-8")
    print(f"Wrote {len(Base.metadata.tables)} tables to {output}")


if __name__ == "__main__":
    main()
