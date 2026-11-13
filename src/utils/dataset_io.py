from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Date, DateTime, Numeric

from src.database.base import Base
from src import models
from src.generators.master_data_generator import TABLE_NAMES

DATETIME_FIELDS = {
    column.name
    for table in Base.metadata.tables.values()
    for column in table.columns
    if isinstance(column.type, DateTime)
} | {"generated_at"}
DATE_FIELDS = {
    column.name
    for table in Base.metadata.tables.values()
    for column in table.columns
    if isinstance(column.type, Date)
}
DECIMAL_FIELDS = {
    column.name
    for table in Base.metadata.tables.values()
    for column in table.columns
    if isinstance(column.type, Numeric)
}


def json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__} to JSON.")


def dataset_json(dataset: dict[str, Any]) -> str:
    return json.dumps(dataset, default=json_default, indent=2, sort_keys=True) + "\n"


def write_dataset(path: Path, dataset: dict[str, Any]) -> str:
    content = dataset_json(dataset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))
    return content


def load_dataset(path: Path) -> dict[str, Any]:
    def decode_row(row: dict[str, Any]) -> dict[str, Any]:
        for key, value in tuple(row.items()):
            if not isinstance(value, str):
                continue
            if key in DATETIME_FIELDS:
                row[key] = datetime.fromisoformat(value)
            elif key in DATE_FIELDS:
                row[key] = date.fromisoformat(value)
            elif key in DECIMAL_FIELDS:
                row[key] = Decimal(value)
        return row

    return json.loads(path.read_text(encoding="utf-8"), object_hook=decode_row)


def write_csv_exports(dataset: dict[str, Any], export_dir: Path) -> dict[str, str]:
    export_dir.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for table_name in TABLE_NAMES:
        rows = dataset[table_name]
        columns = Base.metadata.tables[table_name].columns.keys()
        path = export_dir / f"{table_name}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        digests[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests
