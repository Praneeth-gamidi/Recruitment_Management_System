from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import UniqueConstraint

from src.database.base import Base
from src import models
from src.generators.master_data_generator import TABLE_NAMES

APPLICATION_TRANSITIONS = {
    "APPLIED": {"SCREENING", "REJECTED", "WITHDRAWN"},
    "SCREENING": {"ASSESSMENT", "REJECTED", "WITHDRAWN"},
    "ASSESSMENT": {"TECHNICAL_INTERVIEW", "REJECTED", "WITHDRAWN"},
    "TECHNICAL_INTERVIEW": {"MANAGERIAL_INTERVIEW", "REJECTED", "WITHDRAWN"},
    "MANAGERIAL_INTERVIEW": {"HR_INTERVIEW", "REJECTED", "WITHDRAWN"},
    "HR_INTERVIEW": {"OFFER", "REJECTED", "WITHDRAWN"},
    "OFFER": {"HIRED", "REJECTED", "WITHDRAWN"},
    "HIRED": set(),
    "REJECTED": set(),
    "WITHDRAWN": set(),
}
TERMINAL_APPLICATION_STAGES = {"HIRED", "REJECTED", "WITHDRAWN"}


def validate_dataset(dataset: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _ = models
    metadata = dataset.get("metadata")
    if not isinstance(metadata, dict):
        errors.append("metadata: expected dataset metadata.")
    else:
        expected_counts = metadata.get("record_counts", {})
        for table_name in TABLE_NAMES:
            rows = dataset.get(table_name)
            actual_count = len(rows) if isinstance(rows, list) else 0
            if expected_counts.get(table_name) != actual_count:
                errors.append(f"metadata: record count mismatch for {table_name}.")
        for config_key in (
            "requisitions",
            "candidates",
            "applications",
            "interviews",
            "offers",
            "hiring_managers",
            "interviewers",
            "interview_panels",
            "skills",
            "evaluation_criteria",
        ):
            if metadata.get("configuration", {}).get(config_key) != len(dataset.get(config_key, [])):
                errors.append(f"metadata: configuration count mismatch for {config_key}.")
    for table_name in TABLE_NAMES:
        rows = dataset.get(table_name)
        if not isinstance(rows, list):
            errors.append(f"{table_name}: expected a list of records.")
            continue
        table = Base.metadata.tables[table_name]
        seen_unique: dict[tuple[str, ...], set[tuple[Any, ...]]] = defaultdict(set)
        constrained_unique_columns = {
            column.name
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
            for column in constraint.columns
        }
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"{table_name}[{index}]: expected a record object.")
                continue
            for column in table.columns:
                if not column.nullable and column.default is None and column.server_default is None:
                    if row.get(column.name) is None:
                        errors.append(f"{table_name}[{index}]: missing required field {column.name}.")
            for constraint in table.constraints:
                if isinstance(constraint, UniqueConstraint):
                    names = tuple(column.name for column in constraint.columns)
                    values = tuple(row.get(name) for name in names)
                    if all(value is not None for value in values):
                        if values in seen_unique[names]:
                            errors.append(f"{table_name}[{index}]: duplicate unique key {names}={values}.")
                        seen_unique[names].add(values)
            for column in table.columns:
                if column.unique and column.name not in constrained_unique_columns and row.get(column.name) is not None:
                    name = (column.name,)
                    value = (row[column.name],)
                    if value in seen_unique[name]:
                        errors.append(f"{table_name}[{index}]: duplicate unique key {name}={value}.")
                    seen_unique[name].add(value)

    referenced_columns = {
        (foreign_key.column.table.name, foreign_key.column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        for foreign_key in column.foreign_keys
    }
    referenced_values: dict[tuple[str, str], set[Any]] = {
        key: set() for key in referenced_columns
    }
    for table_name in TABLE_NAMES:
        table = Base.metadata.tables[table_name]
        if not isinstance(dataset.get(table_name), list):
            continue
        pk_names = tuple(column.name for column in table.primary_key.columns)
        pk_values: set[tuple[Any, ...]] = set()
        for index, row in enumerate(dataset[table_name]):
            key = tuple(row.get(name) for name in pk_names)
            if any(value is None for value in key):
                errors.append(f"{table_name}[{index}]: primary key {pk_names} is incomplete.")
            elif key in pk_values:
                errors.append(f"{table_name}[{index}]: duplicate primary key {key}.")
            pk_values.add(key)
            for column_name in table.columns.keys():
                reference_key = (table_name, column_name)
                if reference_key in referenced_values and row.get(column_name) is not None:
                    referenced_values[reference_key].add(row[column_name])

    for table_name in TABLE_NAMES:
        table = Base.metadata.tables[table_name]
        for index, row in enumerate(dataset.get(table_name, [])):
            for column in table.columns:
                for foreign_key in column.foreign_keys:
                    if row.get(column.name) is None and column.nullable:
                        continue
                    parent_table = foreign_key.column.table.name
                    parent_column = foreign_key.column.name
                    if row.get(column.name) not in referenced_values[(parent_table, parent_column)]:
                        errors.append(
                            f"{table_name}[{index}]: {column.name} references missing "
                            f"{parent_table}.{parent_column}={row.get(column.name)!r}."
                        )

    _validate_requisition_approvals(dataset, errors)
    _validate_application_lifecycles(dataset, errors)
    _validate_schedules(dataset, errors)
    _validate_scorecards(dataset, errors)
    _validate_offers(dataset, errors)
    _validate_audit_events(dataset, errors)
    return errors


def _validate_requisition_approvals(dataset: dict[str, Any], errors: list[str]) -> None:
    approvals_by_requisition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for approval in dataset.get("requisition_approvals", []):
        approvals_by_requisition[approval["requisition_id"]].append(approval)
    for requisition in dataset.get("requisitions", []):
        approvals = approvals_by_requisition[requisition["requisition_id"]]
        if requisition["status"] == "OPEN":
            cycles = [approval["approval_cycle"] for approval in approvals]
            latest_cycle = max(cycles, default=0)
            current_approvals = [approval for approval in approvals if approval["approval_cycle"] == latest_cycle]
            if latest_cycle == 0 or len(current_approvals) < 2:
                errors.append(f"Requisition {requisition['requisition_id']} lacks its required approval stages.")
            elif any(approval["decision"] != "APPROVED" for approval in current_approvals):
                errors.append(f"Open requisition {requisition['requisition_id']} has a non-approved current decision.")


def _validate_application_lifecycles(dataset: dict[str, Any], errors: list[str]) -> None:
    history_by_application: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for history in dataset.get("application_stage_history", []):
        history_by_application[history["application_id"]].append(history)
    for application in dataset.get("applications", []):
        application_id = application["application_id"]
        history = sorted(history_by_application[application_id], key=lambda row: row["history_sequence"])
        if not history:
            errors.append(f"Application {application_id} has no stage history.")
            continue
        previous_stage: str | None = None
        previous_status: str | None = None
        previous_time: datetime | None = None
        for sequence, event in enumerate(history, start=1):
            stage = event["new_stage"]
            if event["history_sequence"] != sequence:
                errors.append(f"Application {application_id} has a non-contiguous history sequence.")
            if event["previous_stage"] != previous_stage or event["previous_status"] != previous_status:
                errors.append(f"Application {application_id} history does not preserve the previous state.")
            if previous_stage is None:
                if stage != "APPLIED":
                    errors.append(f"Application {application_id} must begin at APPLIED.")
            elif stage not in APPLICATION_TRANSITIONS.get(previous_stage, set()):
                errors.append(f"Application {application_id} has invalid transition {previous_stage}->{stage}.")
            if previous_time is not None and event["occurred_at"] <= previous_time:
                errors.append(f"Application {application_id} history timestamps are not increasing.")
            expected_status = "CLOSED" if stage in TERMINAL_APPLICATION_STAGES else "ACTIVE"
            if event["new_status"] != expected_status:
                errors.append(f"Application {application_id} has inconsistent status for {stage}.")
            previous_stage, previous_status, previous_time = stage, expected_status, event["occurred_at"]
        if previous_stage != application["current_stage"] or previous_status != application["status"]:
            errors.append(f"Application {application_id} current state does not match its history.")


def _validate_schedules(dataset: dict[str, Any], errors: list[str]) -> None:
    panel_members: dict[str, set[str]] = defaultdict(set)
    for membership in dataset.get("panel_interviewers", []):
        panel_members[membership["panel_id"]].add(membership["interviewer_id"])
    availabilities: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for availability in dataset.get("availability", []):
        availabilities[availability["interviewer_id"]].append(availability)
    interviews = dataset.get("interviews", [])
    applications = {row["application_id"]: row for row in dataset.get("applications", [])}
    application_candidates = {
        row["application_id"]: row["candidate_id"] for row in dataset.get("applications", [])
    }
    for interview in interviews:
        application = applications[interview["application_id"]]
        if (
            interview["status"] in {"SCHEDULED", "CONFIRMED"}
            and application["current_stage"] in TERMINAL_APPLICATION_STAGES
        ):
            errors.append(
                f"Terminal application {application['application_id']} has a scheduled interview."
            )
        if interview["duration_minutes"] != int(
            (interview["end_at"] - interview["start_at"]).total_seconds() // 60
        ):
            errors.append(f"Interview {interview['interview_id']} duration does not match its interval.")
        if interview["status"] in {"SCHEDULED", "CONFIRMED", "COMPLETED"}:
            members = panel_members[interview["panel_id"]]
            if not members:
                errors.append(f"Interview {interview['interview_id']} has no panel members.")
            for interviewer_id in members:
                covered = any(
                    row["availability_status"] == "AVAILABLE"
                    and row["available_start"] <= interview["start_at"]
                    and row["available_end"] >= interview["end_at"]
                    for row in availabilities[interviewer_id]
                )
                if not covered:
                    errors.append(
                        f"Interviewer {interviewer_id} is unavailable for interview {interview['interview_id']}."
                    )

    bookings: list[tuple[str, datetime, datetime, str]] = []
    interviewer_by_panel = {panel_id: members for panel_id, members in panel_members.items()}
    for interview in interviews:
        if interview["status"] not in {"SCHEDULED", "CONFIRMED", "COMPLETED"}:
            continue
        participants = interviewer_by_panel[interview["panel_id"]]
        participants = set(participants) | {
            f"candidate:{application_candidates.get(interview['application_id'], interview['application_id'])}"
        }
        for participant in participants:
            for existing in bookings:
                if (
                    existing[0] == participant
                    and existing[1] < interview["end_at"]
                    and interview["start_at"] < existing[2]
                ):
                    errors.append(
                        f"Overlapping active interviews {existing[3]} and {interview['interview_id']} "
                        f"for {participant}."
                    )
            bookings.append((participant, interview["start_at"], interview["end_at"], interview["interview_id"]))

    interviews_by_id = {row["interview_id"]: row for row in interviews}
    for history in dataset.get("interview_reschedule_history", []):
        interview = interviews_by_id[history["interview_id"]]
        if (
            history["new_start_at"] != interview["start_at"]
            or history["new_end_at"] != interview["end_at"]
            or history["occurred_at"] >= history["new_start_at"]
        ):
            errors.append(f"Reschedule history for {history['interview_id']} does not match its final schedule.")


def _validate_scorecards(dataset: dict[str, Any], errors: list[str]) -> None:
    interviews = {row["interview_id"]: row for row in dataset.get("interviews", [])}
    applications = {row["application_id"]: row for row in dataset.get("applications", [])}
    requisitions = {row["requisition_id"]: row for row in dataset.get("requisitions", [])}
    criteria = {row["criterion_id"]: row for row in dataset.get("evaluation_criteria", [])}
    skills = {row["skill_id"]: row["skill_name"] for row in dataset.get("skills", [])}
    requirements_by_requisition: dict[str, set[str]] = defaultdict(set)
    for requirement in dataset.get("skill_requirements", []):
        skill_id = requirement["skill_id"]
        requirements_by_requisition[requirement["requisition_id"]].add(skill_id)
        if skill_id in skills:
            requirements_by_requisition[requirement["requisition_id"]].add(skills[skill_id])
    membership_by_panel: dict[str, set[str]] = defaultdict(set)
    for membership in dataset.get("panel_interviewers", []):
        membership_by_panel[membership["panel_id"]].add(membership["interviewer_id"])
    scorecards_by_interview: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for scorecard in dataset.get("scorecards", []):
        scorecards_by_interview[scorecard["interview_id"]].append(scorecard)
        interview = interviews[scorecard["interview_id"]]
        if scorecard["reviewer_id"] not in membership_by_panel[interview["panel_id"]]:
            errors.append(f"Scorecard {scorecard['scorecard_id']} reviewer is not a panel member.")
        if scorecard["completion_status"] != "SUBMITTED" or scorecard["submitted_at"] is None:
            errors.append(f"Baseline scorecard {scorecard['scorecard_id']} must be submitted.")
    for interview in dataset.get("interviews", []):
        reviewers = [row["reviewer_id"] for row in scorecards_by_interview[interview["interview_id"]]]
        if len(reviewers) != len(set(reviewers)):
            errors.append(f"Interview {interview['interview_id']} has duplicate reviewer scorecards.")
        if set(reviewers) != membership_by_panel[interview["panel_id"]]:
            errors.append(f"Interview {interview['interview_id']} lacks one or more panel reviews.")

    scorecards = {row["scorecard_id"]: row for row in dataset.get("scorecards", [])}
    for scored_criterion in dataset.get("scorecard_criteria", []):
        criterion = criteria[scored_criterion["criterion_id"]]
        scorecard = scorecards[scored_criterion["scorecard_id"]]
        interview = interviews[scorecard["interview_id"]]
        application = applications[interview["application_id"]]
        requisition = requisitions[application["requisition_id"]]
        scope = criterion["applicability_scope"]
        value = (criterion.get("applicability_value") or "").casefold()
        applicable_values = {
            "DEPARTMENT": {requisition["department"].casefold()},
            "JOB_FAMILY": {requisition["job_family"].casefold()},
            "SKILL": {item.casefold() for item in requirements_by_requisition[requisition["requisition_id"]]},
        }
        if scope != "ALL" and value not in applicable_values.get(scope, set()):
            errors.append(
                f"Scorecard {scorecard['scorecard_id']} includes out-of-scope criterion "
                f"{criterion['criterion_id']}."
            )
        if criterion["active_status"] != "ACTIVE":
            errors.append(f"Scorecard {scorecard['scorecard_id']} uses an inactive criterion.")
        if (
            criterion["effective_from"] > interview["start_at"].date()
            or (
                criterion["effective_to"] is not None
                and criterion["effective_to"] < interview["start_at"].date()
            )
        ):
            errors.append(f"Scorecard {scorecard['scorecard_id']} uses a criterion outside its effective dates.")


def _validate_offers(dataset: dict[str, Any], errors: list[str]) -> None:
    applications = {row["application_id"]: row for row in dataset.get("applications", [])}
    approvals_by_offer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for approval in dataset.get("approvals", []):
        approvals_by_offer[approval["offer_id"]].append(approval)
    for offer in dataset.get("offers", []):
        application = applications[offer["application_id"]]
        if application["current_stage"] not in {"OFFER", "HIRED"}:
            errors.append(f"Offer {offer['offer_id']} belongs to an application outside the offer stage.")
        if not offer["band_min_snapshot"] <= offer["proposed_salary"] <= offer["band_max_snapshot"]:
            errors.append(f"Baseline offer {offer['offer_id']} is outside its compensation band.")
        if offer["status"] == "ACCEPTED" and application["current_stage"] != "HIRED":
            errors.append(f"Accepted offer {offer['offer_id']} does not have a HIRED application.")
        if offer["status"] in {"SENT", "ACCEPTED", "DECLINED", "EXPIRED"}:
            approvals = approvals_by_offer[offer["offer_id"]]
            if not approvals or any(row["decision"] != "APPROVED" for row in approvals):
                errors.append(f"Offer {offer['offer_id']} lacks approved offer decisions.")


def _validate_audit_events(dataset: dict[str, Any], errors: list[str]) -> None:
    for event in dataset.get("audit_events", []):
        if event["actor_type"] == "USER" and (not event["actor_id"] or not event["actor_name_snapshot"]):
            errors.append(f"Audit event {event['audit_event_id']} is missing its user identity.")
        if bool(event["related_entity_type"]) != bool(event["related_entity_id"]):
            errors.append(f"Audit event {event['audit_event_id']} has an incomplete related entity reference.")
