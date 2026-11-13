from __future__ import annotations

from src.config import DEFAULT_SEED
from src.generators.master_data_generator import generate_dataset
from src.utils.dataset_io import dataset_json
from src.validation.dataset_validation import validate_dataset


def test_starter_dataset_is_reproducible() -> None:
    dataset_a = generate_dataset(seed=DEFAULT_SEED, scale="starter")
    dataset_b = generate_dataset(seed=DEFAULT_SEED, scale="starter")
    assert validate_dataset(dataset_a) == []
    assert validate_dataset(dataset_b) == []
    assert dataset_a == dataset_b
    assert dataset_json(dataset_a) == dataset_json(dataset_b)
