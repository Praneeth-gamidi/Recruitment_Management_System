from __future__ import annotations

import pytest

from src.generators.master_data_generator import build_config, generate_dataset
from src.validation.dataset_validation import validate_dataset


def test_generate_starter_dataset_matches_configured_counts() -> None:
    dataset = generate_dataset(seed=20261022, scale="starter")
    assert len(dataset["requisitions"]) == 10
    assert len(dataset["candidates"]) == 50
    assert len(dataset["applications"]) == 80
    assert len(dataset["interviews"]) == 20
    assert len(dataset["offers"]) == 4
    assert len(dataset["metadata"]["record_counts"]) == 21
    assert validate_dataset(dataset) == []


def test_full_dataset_configuration_is_available_without_generation() -> None:
    config = build_config("full")
    assert config["requisitions"] == 200
    assert config["candidates"] == 5000
    assert config["applications"] == 8000
    assert config["interviews"] == 2000


def test_unknown_scale_and_invalid_config_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown dataset scale"):
        build_config("unknown")
    with pytest.raises(ValueError, match="unique candidate/requisition"):
        build_config("starter", {"applications": 501})


def test_starter_lifecycle_states_are_valid_and_history_is_complete() -> None:
    dataset = generate_dataset()
    applications = {row["application_id"]: row for row in dataset["applications"]}
    histories: dict[str, list[dict]] = {}
    for history in dataset["application_stage_history"]:
        histories.setdefault(history["application_id"], []).append(history)
    for application_id, application in applications.items():
        history = sorted(histories[application_id], key=lambda row: row["history_sequence"])
        assert history[-1]["new_stage"] == application["current_stage"]
        assert history[-1]["new_status"] == application["status"]


def test_generator_does_not_change_application_global_random_state() -> None:
    import random

    random.seed(9001)
    expected = random.random()
    random.seed(9001)
    generate_dataset()
    assert random.random() == expected
