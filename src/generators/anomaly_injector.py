from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Any

def _case(case_id: str, *table_records: tuple[str, dict[str, Any] | list[dict[str, Any]]]) -> dict[str, Any]:
    records: dict[str, list[dict[str, Any]]] = {}
    for table_name, value in table_records:
        rows = value if isinstance(value, list) else [value]
        records[table_name] = deepcopy(rows)
    return {"case_id": case_id, "records": records}


def inject_anomalies(dataset: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    interviews = dataset["interviews"]
    scorecards = dataset["scorecards"]
    panel_memberships = dataset["panel_interviewers"]
    applications = dataset["applications"]
    offers = dataset["offers"]

    interview = interviews[0]
    interview_members = [
        row for row in panel_memberships if row["panel_id"] == interview["panel_id"]
    ]
    interview_scorecards = [
        row for row in scorecards if row["interview_id"] == interview["interview_id"]
    ]
    missing_review_case = _case(
        "CASE-0001",
        ("interviews", interview),
        ("panel_interviewers", interview_members),
        ("scorecards", interview_scorecards[:1]),
    )

    other_application = next(
        row for row in applications
        if row["application_id"] != interview["application_id"]
        and all(row["application_id"] != item["application_id"] for item in interviews)
    )
    original_booking = deepcopy(interview)
    original_booking["status"] = "SCHEDULED"
    conflicting_interview = deepcopy(original_booking)
    conflicting_interview["interview_id"] = "ANOM-INT-DOUBLE-BOOKING"
    conflicting_interview["application_id"] = other_application["application_id"]
    conflicting_interview["scheduled_by"] = interview_members[0]["interviewer_id"]
    double_booking_case = _case(
        "CASE-0002",
        ("interviews", [original_booking, conflicting_interview]),
        ("panel_interviewers", interview_members),
    )

    outside_band_offer = deepcopy(offers[0])
    outside_band_offer["offer_id"] = "ANOM-OFFER-OUTSIDE-BAND"
    outside_band_offer["proposed_salary"] = outside_band_offer["band_max_snapshot"] + 10000
    outside_band_offer["exception_reason"] = None
    outside_band_case = _case("CASE-0003", ("offers", outside_band_offer))

    withdrawn_application = next(row for row in applications if row["current_stage"] == "WITHDRAWN")
    withdrawn_history = sorted(
        (
            row for row in dataset["application_stage_history"]
            if row["application_id"] == withdrawn_application["application_id"]
        ),
        key=lambda row: row["history_sequence"],
    )
    withdrawn_interview = deepcopy(interview)
    withdrawn_interview["interview_id"] = "ANOM-INT-WITHDRAWN-CANDIDATE"
    withdrawn_interview["application_id"] = withdrawn_application["application_id"]
    withdrawn_interview["status"] = "SCHEDULED"
    withdrawn_interview["cancellation_reason"] = None
    withdrawn_scheduled_case = _case(
        "CASE-0004",
        ("applications", withdrawn_application),
        ("application_stage_history", withdrawn_history),
        ("interviews", withdrawn_interview),
        ("panel_interviewers", interview_members),
    )

    evaluation_interview = interviews[0]
    evaluation_application = next(
        row for row in applications if row["application_id"] == evaluation_interview["application_id"]
    )
    evaluation_requisition = next(
        row for row in dataset["requisitions"]
        if row["requisition_id"] == evaluation_application["requisition_id"]
    )
    evaluation_scorecard = next(
        row for row in scorecards if row["interview_id"] == evaluation_interview["interview_id"]
    )
    irrelevant_department = (
        "FINANCE" if evaluation_requisition["department"].upper() != "FINANCE" else "ENGINEERING"
    )
    irrelevant_criterion = {
        "criterion_id": "CRIT-ANOM-IRRELEVANT",
        "criterion_code": "ANOMALY_IRRELEVANT_DEPT",
        "criterion_name": "Irrelevant department assessment",
        "description": "Fixture criterion scoped to a different department.",
        "maximum_rating": 5,
        "default_weight": Decimal("1.000"),
        "mandatory": True,
        "applicability_scope": "DEPARTMENT",
        "applicability_value": irrelevant_department,
        "active_status": "ACTIVE",
        "effective_from": date(2025, 1, 1),
        "effective_to": None,
    }
    irrelevant_scorecard_criterion = {
        "scorecard_criteria_id": "SC-ANOM-IRRELEVANT",
        "scorecard_id": evaluation_scorecard["scorecard_id"],
        "criterion_id": irrelevant_criterion["criterion_id"],
        "rating": 4,
        "comments": "Fixture row assigns a non-applicable criterion.",
        "criterion_name_snapshot": irrelevant_criterion["criterion_name"],
        "weight_snapshot": irrelevant_criterion["default_weight"],
        "maximum_rating_snapshot": 5,
        "mandatory_snapshot": True,
        "created_at": evaluation_scorecard["submitted_at"],
    }
    irrelevant_criterion_case = _case(
        "CASE-0005",
        ("applications", evaluation_application),
        ("requisitions", evaluation_requisition),
        ("interviews", evaluation_interview),
        ("scorecards", evaluation_scorecard),
        ("evaluation_criteria", irrelevant_criterion),
        ("scorecard_criteria", irrelevant_scorecard_criterion),
    )

    cases = [
        missing_review_case,
        double_booking_case,
        outside_band_case,
        withdrawn_scheduled_case,
        irrelevant_criterion_case,
    ]
    truth = [
        {
            "case_id": "CASE-0001",
            "issue_type": "MISSING_REQUIRED_REVIEW",
            "entity_type": "Interview",
            "entity_id": interview["interview_id"],
            "related_entity_ids": [interview["application_id"]],
            "expected_label": "MISSING_REQUIRED_REVIEW",
            "expected_action": "Flag for review",
            "severity": "HIGH",
            "description": "At least one assigned panel reviewer has not submitted a scorecard.",
        },
        {
            "case_id": "CASE-0002",
            "issue_type": "DOUBLE_BOOKING",
            "entity_type": "Interview",
            "entity_id": conflicting_interview["interview_id"],
            "related_entity_ids": [interview["interview_id"], other_application["application_id"]],
            "expected_label": "DOUBLE_BOOKING",
            "expected_action": "Reject or reschedule the conflicting booking",
            "severity": "HIGH",
            "description": "Two active interviews overlap for every interviewer assigned to the panel.",
        },
        {
            "case_id": "CASE-0003",
            "issue_type": "OFFER_OUTSIDE_BAND",
            "entity_type": "Offer",
            "entity_id": outside_band_offer["offer_id"],
            "related_entity_ids": [outside_band_offer["application_id"]],
            "expected_label": "OFFER_OUTSIDE_BAND",
            "expected_action": "Require compensation exception approval",
            "severity": "HIGH",
            "description": "The proposed salary exceeds the requisition snapshot band without an exception reason.",
        },
        {
            "case_id": "CASE-0004",
            "issue_type": "WITHDRAWN_CANDIDATE_SCHEDULED",
            "entity_type": "Interview",
            "entity_id": withdrawn_interview["interview_id"],
            "related_entity_ids": [withdrawn_application["application_id"]],
            "expected_label": "WITHDRAWN_CANDIDATE_SCHEDULED",
            "expected_action": "Cancel the interview and prevent further scheduling",
            "severity": "HIGH",
            "description": "A scheduled interview is linked to a withdrawn candidate application.",
        },
        {
            "case_id": "CASE-0005",
            "issue_type": "IRRELEVANT_EVALUATION_CRITERIA",
            "entity_type": "ScorecardCriteria",
            "entity_id": irrelevant_scorecard_criterion["scorecard_criteria_id"],
            "related_entity_ids": [
                evaluation_scorecard["scorecard_id"],
                evaluation_requisition["requisition_id"],
            ],
            "expected_label": "IRRELEVANT_EVALUATION_CRITERIA",
            "expected_action": "Exclude the criterion and flag the scorecard for review",
            "severity": "MEDIUM",
            "description": "A scorecard includes a criterion scoped to a different department.",
        },
    ]
    return cases, truth


def detect_anomalies(cases: list[dict[str, Any]]) -> dict[str, list[str]]:
    detected: dict[str, list[str]] = {}
    for case in cases:
        case_id = case["case_id"]
        records = case["records"]
        found: list[str] = []

        interviews = records.get("interviews", [])
        memberships = records.get("panel_interviewers", [])
        scorecards = records.get("scorecards", [])
        if interviews and memberships and interviews[0]["status"] == "COMPLETED":
            required_reviewers = {
                row["interviewer_id"]
                for row in memberships
                if row["panel_id"] == interviews[0]["panel_id"]
            }
            submitted_reviewers = {
                row["reviewer_id"]
                for row in scorecards
                if row["interview_id"] == interviews[0]["interview_id"]
                and row["completion_status"] == "SUBMITTED"
            }
            if required_reviewers - submitted_reviewers:
                found.append("MISSING_REQUIRED_REVIEW")

        for index, first in enumerate(interviews):
            for second in interviews[index + 1 :]:
                is_active = first["status"] in {"SCHEDULED", "CONFIRMED"} and second["status"] in {
                    "SCHEDULED",
                    "CONFIRMED",
                }
                if (
                    is_active
                    and first["start_at"] < second["end_at"]
                    and second["start_at"] < first["end_at"]
                ):
                    if first["panel_id"] == second["panel_id"]:
                        found.append("DOUBLE_BOOKING")
                        break

        for offer in records.get("offers", []):
            if (
                offer["proposed_salary"] < offer["band_min_snapshot"]
                or offer["proposed_salary"] > offer["band_max_snapshot"]
            ) and not offer.get("exception_reason"):
                found.append("OFFER_OUTSIDE_BAND")
                break

        applications = records.get("applications", [])
        applications_by_id = {row["application_id"]: row for row in applications}
        if any(
            interview["status"] in {"SCHEDULED", "CONFIRMED"}
            and applications_by_id.get(interview["application_id"], {}).get("current_stage") == "WITHDRAWN"
            for interview in interviews
        ):
            found.append("WITHDRAWN_CANDIDATE_SCHEDULED")

        requisitions = {
            row["requisition_id"]: row for row in records.get("requisitions", [])
        }
        applications_by_id.update(
            {
                row["application_id"]: row
                for row in records.get("applications", [])
            }
        )
        interviews_by_id = {row["interview_id"]: row for row in interviews}
        scorecards_by_id = {
            row["scorecard_id"]: row for row in records.get("scorecards", [])
        }
        criteria = {
            row["criterion_id"]: row for row in records.get("evaluation_criteria", [])
        }
        for scorecard_criterion in records.get("scorecard_criteria", []):
            criterion = criteria.get(scorecard_criterion["criterion_id"])
            scorecard = scorecards_by_id.get(scorecard_criterion["scorecard_id"])
            interview = interviews_by_id.get(scorecard["interview_id"]) if scorecard else None
            application = applications_by_id.get(interview["application_id"]) if interview else None
            requisition = requisitions.get(application["requisition_id"]) if application else None
            if not all((criterion, requisition)):
                continue
            scope = criterion["applicability_scope"]
            value = (criterion.get("applicability_value") or "").casefold()
            if scope == "DEPARTMENT" and value != requisition["department"].casefold():
                found.append("IRRELEVANT_EVALUATION_CRITERIA")
                break
            if scope == "JOB_FAMILY" and value != requisition["job_family"].casefold():
                found.append("IRRELEVANT_EVALUATION_CRITERIA")
                break
        detected[case_id] = sorted(set(found))
    return detected


def validate_anomaly_ground_truth(
    cases: list[dict[str, Any]], ground_truth: list[dict[str, Any]]
) -> list[str]:
    detected = detect_anomalies(cases)
    truth_by_case = {row["case_id"]: row["issue_type"] for row in ground_truth}
    errors: list[str] = []
    if set(detected) != set(truth_by_case):
        errors.append("Anomaly input cases and ground-truth case IDs do not match.")
    for case_id, expected in truth_by_case.items():
        if detected.get(case_id) != [expected]:
            errors.append(
                f"{case_id}: expected only {expected}, detected {detected.get(case_id, [])}."
            )
    return errors
