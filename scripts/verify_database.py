from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, select
from sqlalchemy.exc import SQLAlchemyError

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.database.base import Base
from src.database.session import SessionLocal, engine
from src.models import HiringManager


def verify() -> list[str]:
    inspector = inspect(engine)
    expected_tables = set(Base.metadata.tables)
    actual_tables = set(inspector.get_table_names())
    missing = expected_tables - actual_tables
    if missing:
        raise RuntimeError(f"Missing database tables: {', '.join(sorted(missing))}")

    report = [f"PostgreSQL connection: OK ({engine.dialect.name})"]
    report.append(f"Expected tables: {len(expected_tables)}; present: {len(expected_tables & actual_tables)}")
    totals = {
        "primary_keys": 0,
        "foreign_keys": 0,
        "unique_constraints": 0,
        "check_constraints": 0,
        "indexes": 0,
    }
    for table_name in sorted(expected_tables):
        model_table = Base.metadata.tables[table_name]
        db_pk = set(inspector.get_pk_constraint(table_name).get("constrained_columns") or [])
        model_pk = {column.name for column in model_table.primary_key.columns}
        if db_pk != model_pk:
            raise RuntimeError(f"Primary-key mismatch for {table_name}: {db_pk} != {model_pk}")
        totals["primary_keys"] += 1
        db_fks = {
            (
                tuple(fk["constrained_columns"] or ()),
                fk["referred_table"],
                tuple(fk["referred_columns"] or ()),
            )
            for fk in inspector.get_foreign_keys(table_name)
        }
        expected_fks = {
            (
                tuple(element.parent.name for element in constraint.elements),
                constraint.elements[0].column.table.name,
                tuple(element.column.name for element in constraint.elements),
            )
            for constraint in model_table.foreign_key_constraints
        }
        if db_fks != expected_fks:
            raise RuntimeError(f"Foreign-key definitions mismatch for {table_name}")
        totals["foreign_keys"] += len(expected_fks)
        db_uniques = {
            frozenset(item.get("column_names") or ())
            for item in inspector.get_unique_constraints(table_name)
        }
        expected_uniques = {
            frozenset(column.name for column in item.columns)
            for item in model_table.constraints
            if isinstance(item, UniqueConstraint)
        }
        if db_uniques != expected_uniques:
            raise RuntimeError(f"Unique-constraint definitions mismatch for {table_name}")
        totals["unique_constraints"] += len(expected_uniques)
        db_checks = {
            item.get("name")
            for item in inspector.get_check_constraints(table_name)
        }
        expected_checks = {
            item.name
            for item in model_table.constraints
            if isinstance(item, CheckConstraint)
        }
        if db_checks != expected_checks:
            raise RuntimeError(f"Check-constraint definitions mismatch for {table_name}")
        totals["check_constraints"] += len(expected_checks)
        db_indexes = {item["name"] for item in inspector.get_indexes(table_name)}
        expected_indexes = {item.name for item in model_table.indexes}
        if not expected_indexes.issubset(db_indexes):
            raise RuntimeError(f"Index definitions mismatch for {table_name}")
        totals["indexes"] += len(expected_indexes)
    report.append(
        "Catalog definitions: "
        f"{totals['primary_keys']} primary keys, {totals['foreign_keys']} foreign keys, "
        f"{totals['unique_constraints']} unique constraints, {totals['check_constraints']} checks, "
        f"{totals['indexes']} ORM indexes: OK"
    )
    report.append(f"ORM model registration: OK ({len(Base.registry.mappers)} mapped classes)")

    test_id = f"VERIFY-{uuid.uuid4().hex}"
    with SessionLocal() as session:
        transaction = session.begin()
        try:
            session.add(
                HiringManager(
                    hiring_manager_id=test_id,
                    employee_code=test_id.lower(),
                    name="Temporary verification record",
                    email=f"{test_id.lower()}@example.invalid",
                    department="Verification",
                )
            )
            session.flush()
        finally:
            transaction.rollback()
    with SessionLocal() as session:
        if session.scalar(
            select(HiringManager.hiring_manager_id).where(HiringManager.hiring_manager_id == test_id)
        ):
            raise RuntimeError("Verification insert was not rolled back.")
    report.append("Insert and rollback: OK; no verification record remains")
    return report


def main() -> int:
    try:
        for line in verify():
            print(f"[OK] {line}")
    except (SQLAlchemyError, RuntimeError) as error:
        print(f"[FAIL] Database verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
