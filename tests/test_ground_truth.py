from __future__ import annotations

from copy import deepcopy

from src.generators.anomaly_injector import inject_anomalies, validate_anomaly_ground_truth
from src.generators.master_data_generator import generate_dataset
from src.metrics.anomaly_metrics import anomaly_summary
from src.utils.dataset_io import dataset_json
from src.validation.dataset_validation import validate_dataset


EXPECTED_ANOMALIES = {
    "MISSING_REQUIRED_REVIEW",
    "DOUBLE_BOOKING",
    "OFFER_OUTSIDE_BAND",
    "WITHDRAWN_CANDIDATE_SCHEDULED",
    "IRRELEVANT_EVALUATION_CRITERIA",
}


def test_five_anomaly_cases_have_separate_ground_truth_and_are_detectable() -> None:
    dataset = generate_dataset()
    before = dataset_json(dataset)
    cases, ground_truth = inject_anomalies(dataset)

    assert len(cases) == len(ground_truth) == 5
    assert {row["issue_type"] for row in ground_truth} == EXPECTED_ANOMALIES
    assert validate_anomaly_ground_truth(cases, ground_truth) == []
    summary = anomaly_summary(ground_truth)
    assert summary["total"] == 5
    assert all(summary[key] == 1 for key in summary if key != "total")
    assert dataset_json(dataset) == before
    assert all(
        "issue_type" not in case
        and all("expected_label" not in record for rows in case["records"].values() for record in rows)
        for case in cases
    )
    assert validate_dataset(dataset) == []


def test_anomaly_truth_mismatch_is_reported() -> None:
    cases, ground_truth = inject_anomalies(generate_dataset())
    altered_truth = deepcopy(ground_truth)
    altered_truth[0]["issue_type"] = "DOUBLE_BOOKING"
    errors = validate_anomaly_ground_truth(cases, altered_truth)
    assert errors
