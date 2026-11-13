from __future__ import annotations

from sqlalchemy import create_engine, event

from src.database.base import Base
from src.generators.master_data_generator import generate_dataset
from src.validation.dataset_validation import TABLE_NAMES, validate_dataset


def test_starter_records_satisfy_model_constraints_in_isolated_database() -> None:
    dataset = generate_dataset()
    assert validate_dataset(dataset) == []
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in TABLE_NAMES:
                continue
            rows = dataset[table.name]
            if rows:
                connection.execute(table.insert(), rows)
    engine.dispose()
