from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.database.base import Base
from src.generators.anomaly_injector import validate_anomaly_ground_truth
from src.utils.dataset_io import load_dataset
from src.validation.dataset_validation import TABLE_NAMES, validate_dataset


def _validate_database_constraints(dataset: dict) -> None:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            for table in Base.metadata.sorted_tables:
                if table.name not in TABLE_NAMES:
                    continue
                rows = dataset[table.name]
                if rows:
                    connection.execute(table.insert(), rows)
    finally:
        engine.dispose()


def main() -> None:
    dataset_path = ROOT / "data" / "processed" / "dataset.json"
    if not dataset_path.is_file():
        raise SystemExit("No dataset found; run scripts/generate_data.py first.")
    dataset = load_dataset(dataset_path)

    dataset_errors = validate_dataset(dataset)
    checks = {
        "structural_primary_keys_unique_and_required_fields": not any(
            "primary key" in error or "duplicate unique key" in error or "missing required field" in error
            for error in dataset_errors
        ),
        "foreign_key_relationships": not any("references missing" in error for error in dataset_errors),
        "lifecycle_scheduling_approval_and_compensation_rules": not any(
            "primary key" not in error
            and "duplicate unique key" not in error
            and "missing required field" not in error
            and "references missing" not in error
            for error in dataset_errors
        ),
    }

    sqlite_error: str | None = None
    try:
        _validate_database_constraints(dataset)
    except Exception as exc:
        sqlite_error = f"{type(exc).__name__}: {exc}"
    checks["model_database_constraints_and_relationship_insert"] = sqlite_error is None

    anomaly_path = ROOT / "data" / "anomalies" / "anomaly_cases.json"
    truth_path = ROOT / "data" / "ground_truth" / "anomalies.json"
    anomaly_errors: list[str] = []
    anomaly_counts: dict[str, int] = {}
    if not anomaly_path.is_file() or not truth_path.is_file():
        anomaly_errors.append("Anomaly input or ground-truth file is missing.")
    else:
        anomaly_cases = load_dataset(anomaly_path)
        ground_truth = json.loads(truth_path.read_text(encoding="utf-8"))
        anomaly_errors = validate_anomaly_ground_truth(anomaly_cases, ground_truth)
        for item in ground_truth:
            issue_type = item["issue_type"]
            anomaly_counts[issue_type] = anomaly_counts.get(issue_type, 0) + 1
    checks["five_approved_anomaly_cases_match_ground_truth"] = not anomaly_errors

    errors = dataset_errors + anomaly_errors
    if sqlite_error:
        errors.append(f"Isolated SQLite constraint verification failed: {sqlite_error}")
    report = {
        "dataset_name": dataset["metadata"]["dataset_name"],
        "seed": dataset["metadata"]["seed"],
        "scale": dataset["metadata"]["scale"],
        "passed": all(checks.values()) and not errors,
        "checks": checks,
        "record_counts": dataset["metadata"]["record_counts"],
        "total_records": sum(dataset["metadata"]["record_counts"].values()),
        "anomaly_counts": anomaly_counts,
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "anomaly_cases_sha256": (
            hashlib.sha256(anomaly_path.read_bytes()).hexdigest() if anomaly_path.is_file() else None
        ),
        "ground_truth_sha256": (
            hashlib.sha256(truth_path.read_bytes()).hexdigest() if truth_path.is_file() else None
        ),
        "errors": errors,
    }
    report_path = ROOT / "data" / "processed" / "validation.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for check_name, passed in checks.items():
        print(f"[{'OK' if passed else 'FAIL'}] {check_name}")
    print(f"Dataset validation {'passed' if report['passed'] else 'failed'} for {len(dataset['metadata']['record_counts'])} tables.")
    print(f"Seed: {report['seed']}; scale: {report['scale']}; records: {report['total_records']}")
    print(f"Anomaly counts: {anomaly_counts}")
    print(f"Report: {report_path.relative_to(ROOT)}")
    if not report["passed"]:
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
