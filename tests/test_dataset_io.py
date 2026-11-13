from __future__ import annotations

from src.generators.master_data_generator import TABLE_NAMES, generate_dataset
from src.utils.dataset_io import dataset_json, load_dataset, write_csv_exports, write_dataset
from src.validation.dataset_validation import validate_dataset


def test_json_round_trip_and_csv_exports_are_stable(tmp_path) -> None:
    dataset = generate_dataset()
    json_path = tmp_path / "processed" / "dataset.json"
    written = write_dataset(json_path, dataset)
    assert json_path.read_bytes() == written.encode("utf-8")
    loaded = load_dataset(json_path)
    assert dataset_json(loaded) == written
    assert validate_dataset(loaded) == []

    hashes_a = write_csv_exports(dataset, tmp_path / "csv-a")
    hashes_b = write_csv_exports(dataset, tmp_path / "csv-b")
    assert hashes_a == hashes_b
    assert len(hashes_a) == len(TABLE_NAMES) == 21
