from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from faker import Faker

from src.config import DEFAULT_SEED
from src.utils.id_generator import (
    generate_approval_id,
    generate_candidate_id,
    generate_event_id,
    generate_interview_id,
    generate_offer_id,
    generate_requisition_id,
    generate_scorecard_id,
)

STARTER_CONFIG: dict[str, int] = {
    "requisitions": 10,
    "candidates": 50,
    "applications": 80,
    "interviews": 20,
    "offers": 4,
    "hiring_managers": 5,
    "interviewers": 8,
    "interview_panels": 4,
    "skills": 15,
    "evaluation_criteria": 5,
}

FULL_CONFIG: dict[str, int] = {
    "requisitions": 200,
    "candidates": 5000,
    "applications": 8000,
    "interviews": 2000,
    "offers": 400,
    "hiring_managers": 20,
    "interviewers": 80,
    "interview_panels": 40,
    "skills": 30,
    "evaluation_criteria": 5,
}

TABLE_NAMES = (
    "hiring_managers",
    "requisitions",
    "requisition_approvals",
    "candidates",
    "applications",
    "skills",
    "skill_requirements",
    "candidate_skills",
    "interviewers",
    "interview_panels",
    "panel_interviewers",
    "availability",
    "interviews",
    "interview_reschedule_history",
    "evaluation_criteria",
    "scorecards",
    "scorecard_criteria",
    "offers",
    "approvals",
    "application_stage_history",
    "audit_events",
)

DEPARTMENTS = ("ENGINEERING", "DATA", "PRODUCT", "HR", "FINANCE")
EDUCATION_LEVELS = ("BACHELOR", "MASTER", "DOCTORATE", "ASSOCIATE")
SKILL_NAMES = (
    "python", "sql", "postgresql", "data analysis", "machine learning",
    "project management", "communication", "java", "cloud computing",
    "system design", "recruiting", "financial modeling", "react",
    "technical writing", "leadership", "docker", "security", "testing",
    "product strategy", "business analysis", "statistics", "kubernetes",
    "negotiation", "customer research", "excel", "typescript", "linux",
    "analytics", "design thinking", "mentoring",
)

CRITERIA = (
    ("TECHNICAL_DEPTH", "Technical depth", Decimal("1.500")),
    ("PROBLEM_SOLVING", "Problem solving", Decimal("1.250")),
    ("COMMUNICATION", "Communication", Decimal("1.000")),
    ("COLLABORATION", "Collaboration", Decimal("1.000")),
    ("ROLE_ALIGNMENT", "Role alignment", Decimal("1.250")),
)

BASE_DATE = date(2026, 1, 5)
BASE_DATETIME = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)


def build_config(scale: str = "starter", custom: dict[str, int] | None = None) -> dict[str, int]:
    configurations = {"starter": STARTER_CONFIG, "full": FULL_CONFIG}
    if scale not in configurations:
        raise ValueError(f"Unknown dataset scale: {scale!r}")

    config = configurations[scale].copy()
    if custom:
        unknown = set(custom) - set(config)
        if unknown:
            raise ValueError(f"Unknown dataset configuration keys: {', '.join(sorted(unknown))}")
        config.update(custom)

    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in config.values()):
        raise ValueError("Every dataset configuration value must be a positive integer.")
    if config["applications"] > config["candidates"] * config["requisitions"]:
        raise ValueError("Application count exceeds the number of unique candidate/requisition pairs.")
    if config["interviews"] > config["applications"]:
        raise ValueError("Interview count cannot exceed the application count.")
    if config["offers"] * 3 > config["interviews"]:
        raise ValueError("Each offer requires three lifecycle interviews; increase interviews or reduce offers.")
    if config["interview_panels"] < 3:
        raise ValueError("At least three interview panels are required for an offer lifecycle.")
    if config["interview_panels"] * 2 > config["interviewers"]:
        raise ValueError("Each interview panel requires two distinct interviewers.")
    if config["skills"] > len(SKILL_NAMES):
        raise ValueError(f"At most {len(SKILL_NAMES)} distinct starter skill definitions are available.")
    if config["evaluation_criteria"] > len(CRITERIA):
        raise ValueError(f"At most {len(CRITERIA)} distinct evaluation criteria are available.")
    return config


def _ts(day: date, hour: int = 9, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.utc)


def _audit(
    rows: list[dict[str, Any]],
    event_type: str,
    entity_type: str,
    entity_id: str,
    occurred_at: datetime,
    *,
    previous_state: str | None = None,
    new_state: str | None = None,
    actor_id: str | None = None,
    actor_name: str | None = None,
    reason: str | None = None,
    related_entity_type: str | None = None,
    related_entity_id: str | None = None,
) -> None:
    rows.append(
        {
            "audit_event_id": generate_event_id(len(rows) + 1),
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "related_entity_type": related_entity_type,
            "related_entity_id": related_entity_id,
            "previous_state": previous_state,
            "new_state": new_state,
            "actor_type": "SYSTEM" if actor_id is None else "USER",
            "actor_id": actor_id,
            "actor_name_snapshot": actor_name,
            "reason": reason,
            "occurred_at": occurred_at,
            "payload": None,
        }
    )


def generate_dataset(
    seed: int = DEFAULT_SEED,
    scale: str = "starter",
    custom: dict[str, int] | None = None,
) -> dict[str, Any]:
    config = build_config(scale, custom)
    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed)
    data: dict[str, Any] = {table_name: [] for table_name in TABLE_NAMES}
    audit_events = data["audit_events"]

    departments = list(DEPARTMENTS)
    for index in range(config["hiring_managers"]):
        department = departments[index % len(departments)]
        manager_id = f"HM-{index + 1:06d}"
        data["hiring_managers"].append(
            {
                "hiring_manager_id": manager_id,
                "employee_code": f"hm-{index + 1:06d}",
                "name": fake.name(),
                "email": f"hm{index + 1:06d}@example.com",
                "department": department.title(),
                "phone": fake.phone_number()[:32],
                "active_status": "ACTIVE",
                "created_at": BASE_DATETIME - timedelta(days=90),
                "updated_at": BASE_DATETIME - timedelta(days=90),
            }
        )

    for index in range(config["requisitions"]):
        requisition_id = generate_requisition_id(2026, index + 1)
        department = departments[index % len(departments)]
        manager = data["hiring_managers"][index % len(data["hiring_managers"])]
        req_opening = BASE_DATE - timedelta(days=14)
        created_at = _ts(req_opening - timedelta(days=20))
        min_salary = Decimal(85000 + (index % 10) * 5000)
        max_salary = min_salary + Decimal(50000)
        data["requisitions"].append(
            {
                "requisition_id": requisition_id,
                "hiring_manager_id": manager["hiring_manager_id"],
                "title": fake.job(),
                "description": f"Recruiting for the {department.title()} team.",
                "department": department.title(),
                "job_family": department.title(),
                "location": fake.city(),
                "employment_type": ("FULL_TIME", "CONTRACT", "PART_TIME")[index % 3],
                "work_mode": ("HYBRID", "REMOTE", "ONSITE")[index % 3],
                "headcount": 1 + index % 4,
                "status": "OPEN",
                "min_salary": min_salary,
                "max_salary": max_salary,
                "currency_code": "USD",
                "compensation_period": "YEAR",
                "opening_date": req_opening,
                "closing_date": BASE_DATE + timedelta(days=330),
                "approved_at": _ts(req_opening - timedelta(days=2)),
                "created_at": created_at,
                "updated_at": _ts(req_opening - timedelta(days=2)),
            }
        )
        for sequence in (1, 2):
            approver = data["hiring_managers"][(index + sequence) % len(data["hiring_managers"])]
            decision_at = _ts(req_opening - timedelta(days=4 - sequence), 11)
            data["requisition_approvals"].append(
                {
                    "requisition_approval_id": f"REQAPP-{index + 1:06d}-{sequence:02d}",
                    "requisition_id": requisition_id,
                    "approver_id": approver["hiring_manager_id"],
                    "approval_cycle": 1,
                    "approval_sequence": sequence,
                    "approval_stage": ("DEPARTMENT_HEAD", "FINANCE")[sequence - 1],
                    "decision": "APPROVED",
                    "comments": "Approved for recruitment.",
                    "requested_at": _ts(req_opening - timedelta(days=7)),
                    "decided_at": decision_at,
                    "supersedes_requisition_approval_id": None,
                }
            )
            _audit(
                audit_events,
                "APPROVAL_DECIDED",
                "RequisitionApproval",
                f"REQAPP-{index + 1:06d}-{sequence:02d}",
                decision_at,
                previous_state="PENDING",
                new_state="APPROVED",
                actor_id=approver["hiring_manager_id"],
                actor_name=approver["name"],
                reason="Requisition approval recorded.",
                related_entity_type="Requisition",
                related_entity_id=requisition_id,
            )
        _audit(
            audit_events,
            "STATUS_CHANGED",
            "Requisition",
            requisition_id,
            _ts(req_opening - timedelta(days=2)),
            previous_state="PENDING_APPROVAL",
            new_state="OPEN",
            actor_id=manager["hiring_manager_id"],
            actor_name=manager["name"],
            reason="All approval stages in the current cycle are approved.",
        )

    skills = SKILL_NAMES[: config["skills"]]
    for index, name in enumerate(skills, start=1):
        data["skills"].append(
            {
                "skill_id": f"SKILL-{index:04d}",
                "skill_name": name,
                "skill_category": ("TECHNICAL", "BUSINESS", "SOFT")[index % 3],
                "active_status": "ACTIVE",
                "created_at": BASE_DATETIME - timedelta(days=120),
            }
        )

    for index, requisition in enumerate(data["requisitions"]):
        for offset in range(min(3, len(skills))):
            skill_index = (index + offset) % len(skills)
            data["skill_requirements"].append(
                {
                    "skill_requirement_id": f"REQSKILL-{index + 1:06d}-{offset + 1:02d}",
                    "requisition_id": requisition["requisition_id"],
                    "skill_id": data["skills"][skill_index]["skill_id"],
                    "requirement_type": "MANDATORY" if offset == 0 else "PREFERRED",
                    "minimum_proficiency": min(5, 3 + offset),
                    "minimum_experience_months": offset * 12,
                    "weight": Decimal("1.000") + Decimal(offset) / Decimal("2"),
                    "created_at": requisition["created_at"],
                }
            )

    for index in range(config["candidates"]):
        candidate_id = generate_candidate_id(index + 1)
        first_name = fake.first_name()
        last_name = fake.last_name()
        created_at = _ts(BASE_DATE - timedelta(days=45 - (index % 40)))
        data["candidates"].append(
            {
                "candidate_id": candidate_id,
                "first_name": first_name,
                "last_name": last_name,
                "email": f"candidate{index + 1:06d}@example.com",
                "phone": fake.phone_number()[:32],
                "location": fake.city(),
                "education_level": EDUCATION_LEVELS[index % len(EDUCATION_LEVELS)],
                "education_summary": f"{EDUCATION_LEVELS[index % len(EDUCATION_LEVELS)].title()} degree",
                "total_experience_months": 12 * (1 + index % 15),
                "profile_created_at": created_at,
                "created_at": created_at,
                "updated_at": created_at,
            }
        )
        selected_skills = rng.sample(range(len(skills)), k=min(3, len(skills)))
        for skill_index in selected_skills:
            data["candidate_skills"].append(
                {
                    "candidate_skill_id": f"CANDSKILL-{index + 1:06d}-{skill_index + 1:04d}",
                    "candidate_id": candidate_id,
                    "skill_id": data["skills"][skill_index]["skill_id"],
                    "proficiency_level": ("BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT")[
                        (index + skill_index) % 4
                    ],
                    "experience_months": (index + skill_index) % 72,
                    "last_used_on": BASE_DATE - timedelta(days=(index + skill_index) % 365),
                    "created_at": created_at,
                }
            )

    criteria_count = config["evaluation_criteria"]
    for index, (code, name, weight) in enumerate(CRITERIA[:criteria_count], start=1):
        data["evaluation_criteria"].append(
            {
                "criterion_id": f"CRIT-{index:04d}",
                "criterion_code": code,
                "criterion_name": name,
                "description": f"Evaluate the candidate's {name.lower()}.",
                "maximum_rating": 5,
                "default_weight": weight,
                "mandatory": True,
                "applicability_scope": "ALL",
                "applicability_value": None,
                "active_status": "ACTIVE",
                "effective_from": date(2025, 1, 1),
                "effective_to": None,
            }
        )

    manager_ids = [row["hiring_manager_id"] for row in data["hiring_managers"]]
    interviewer_count = config["interviewers"]
    for index in range(interviewer_count):
        department = departments[index % len(departments)]
        interviewer_id = f"INTV-{index + 1:06d}"
        data["interviewers"].append(
            {
                "interviewer_id": interviewer_id,
                "employee_code": f"intv-{index + 1:06d}",
                "name": fake.name(),
                "email": f"interviewer{index + 1:06d}@example.com",
                "department": department.title(),
                "designation": ("Engineer", "Manager", "Recruiter")[index % 3],
                "active_status": "ACTIVE",
                "created_at": BASE_DATETIME - timedelta(days=90),
                "updated_at": BASE_DATETIME - timedelta(days=90),
            }
        )

    panel_count = config["interview_panels"]
    for panel_index in range(panel_count):
        panel_id = f"PANEL-{panel_index + 1:04d}"
        data["interview_panels"].append(
            {
                "panel_id": panel_id,
                "panel_name": f"{DEPARTMENTS[panel_index % len(DEPARTMENTS)].title()} panel {panel_index + 1}",
                "panel_type": ("TECHNICAL", "MANAGERIAL", "HR", "GENERAL")[panel_index % 4],
                "active_status": "ACTIVE",
                "created_at": BASE_DATETIME - timedelta(days=60),
                "updated_at": BASE_DATETIME - timedelta(days=60),
            }
        )
        for member_offset in (0, 1):
            interviewer_index = panel_index * 2 + member_offset
            interviewer = data["interviewers"][interviewer_index]
            data["panel_interviewers"].append(
                {
                    "panel_interviewer_id": f"PM-{panel_index + 1:04d}-{member_offset + 1:02d}",
                    "panel_id": panel_id,
                    "interviewer_id": interviewer["interviewer_id"],
                    "role_in_panel": "LEAD" if member_offset == 0 else "INTERVIEWER",
                    "effective_from": date(2025, 1, 1),
                    "effective_to": None,
                    "created_at": BASE_DATETIME - timedelta(days=60),
                }
            )

    candidate_requisition_pairs = [
        (candidate, requisition)
        for candidate in data["candidates"]
        for requisition in data["requisitions"]
    ]
    rng.shuffle(candidate_requisition_pairs)
    offers_count = config["offers"]
    offer_pairs = candidate_requisition_pairs[:offers_count]
    remaining_pairs = candidate_requisition_pairs[offers_count:]
    rng.shuffle(remaining_pairs)
    application_pairs = offer_pairs + remaining_pairs[: config["applications"] - offers_count]

    applications_by_id: dict[str, dict[str, Any]] = {}
    for index, (candidate, requisition) in enumerate(application_pairs):
        application_id = f"APP-{candidate['candidate_id']}-{requisition['requisition_id']}"
        if index < offers_count:
            target_stage = "HIRED" if index == 0 else "OFFER"
        elif index < offers_count + config["interviews"] - 3 * offers_count:
            target_stage = "TECHNICAL_INTERVIEW"
        else:
            target_stage = rng.choice(
                ("APPLIED", "SCREENING", "ASSESSMENT", "REJECTED", "WITHDRAWN")
            )
        target_status = "CLOSED" if target_stage in {"HIRED", "REJECTED", "WITHDRAWN"} else "ACTIVE"
        if target_stage in {"REJECTED", "WITHDRAWN"}:
            previous_stage = rng.choice(("APPLIED", "SCREENING", "ASSESSMENT"))
            stage_path = ["APPLIED"]
            if previous_stage in {"SCREENING", "ASSESSMENT"}:
                stage_path.append("SCREENING")
            if previous_stage == "ASSESSMENT":
                stage_path.append("ASSESSMENT")
            stage_path.append(target_stage)
        else:
            stage_path = ["APPLIED"]
            stage_order = (
                "APPLIED",
                "SCREENING",
                "ASSESSMENT",
                "TECHNICAL_INTERVIEW",
                "MANAGERIAL_INTERVIEW",
                "HR_INTERVIEW",
                "OFFER",
                "HIRED",
            )
            stage_path.extend(stage for stage in stage_order[1:] if stage_order.index(stage) <= stage_order.index(target_stage))

        applied_at = _ts(BASE_DATE + timedelta(days=index % 30), 9 + index % 8)
        data["applications"].append(
            {
                "application_id": application_id,
                "candidate_id": candidate["candidate_id"],
                "requisition_id": requisition["requisition_id"],
                "applied_at": applied_at,
                "current_stage": target_stage,
                "status": target_status,
                "source_channel": ("CAREER_SITE", "REFERRAL", "JOB_BOARD", "AGENCY", "DIRECT", "OTHER")[
                    index % 6
                ],
                "source_detail": None if index % 3 == 0 else ("Employee referral" if index % 6 == 1 else None),
                "created_at": applied_at,
                "updated_at": applied_at + timedelta(days=max(1, len(stage_path) - 1)),
            }
        )
        applications_by_id[application_id] = data["applications"][-1]

        previous_stage: str | None = None
        previous_status: str | None = None
        for sequence, stage in enumerate(stage_path, start=1):
            history_time = applied_at + timedelta(days=sequence - 1, hours=sequence)
            new_status = "CLOSED" if stage in {"HIRED", "REJECTED", "WITHDRAWN"} else "ACTIVE"
            history_id = f"STAGE-{index + 1:06d}-{sequence:02d}"
            data["application_stage_history"].append(
                {
                    "stage_history_id": history_id,
                    "application_id": application_id,
                    "history_sequence": sequence,
                    "previous_stage": previous_stage,
                    "new_stage": stage,
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "actor_id": manager_ids[index % len(manager_ids)],
                    "actor_name_snapshot": data["hiring_managers"][index % len(data["hiring_managers"])]["name"],
                    "reason": "Application created." if sequence == 1 else f"Application moved to {stage.lower()}.",
                    "occurred_at": history_time,
                }
            )
            _audit(
                audit_events,
                "STAGE_CHANGED",
                "Application",
                application_id,
                history_time,
                previous_state=previous_stage,
                new_state=stage,
                actor_id=manager_ids[index % len(manager_ids)],
                actor_name=data["hiring_managers"][index % len(data["hiring_managers"])]["name"],
                reason="Application created." if sequence == 1 else f"Application moved to {stage.lower()}.",
            )
            previous_stage, previous_status = stage, new_status

    for index, application in enumerate(data["applications"][: offers_count]):
        requisition = next(row for row in data["requisitions"] if row["requisition_id"] == application["requisition_id"])
        status = (
            "ACCEPTED"
            if index == 0
            else ("SENT", "PENDING_APPROVAL", "DECLINED")[(index - 1) % 3]
        )
        offer_id = generate_offer_id(2026, index + 1)
        sent_at = None
        expires_at = None
        accepted_at = None
        declined_at = None
        if status in {"SENT", "ACCEPTED", "DECLINED"}:
            sent_at = _ts(BASE_DATE + timedelta(days=70 + index), 14)
            expires_at = sent_at + timedelta(days=14)
        if status == "ACCEPTED":
            accepted_at = sent_at + timedelta(days=2)
        elif status == "DECLINED":
            declined_at = sent_at + timedelta(days=3)
        salary = requisition["min_salary"] + Decimal(10000 + (index % 40) * 1000)
        offer = {
            "offer_id": offer_id,
            "application_id": application["application_id"],
            "supersedes_offer_id": None,
            "offer_version": 1,
            "proposed_salary": salary,
            "band_min_snapshot": requisition["min_salary"],
            "band_max_snapshot": requisition["max_salary"],
            "currency_code": requisition["currency_code"],
            "compensation_period": requisition["compensation_period"],
            "status": status,
            "exception_reason": None,
            "offer_date": BASE_DATE + timedelta(days=70 + index) if sent_at else None,
            "joining_date": (BASE_DATE + timedelta(days=60 + index)) if accepted_at else None,
            "expires_at": expires_at,
            "sent_at": sent_at,
            "accepted_at": accepted_at,
            "declined_at": declined_at,
            "created_by": manager_ids[index % len(manager_ids)],
            "created_at": _ts(BASE_DATE + timedelta(days=68 + index), 12),
            "updated_at": accepted_at or declined_at or sent_at or _ts(BASE_DATE + timedelta(days=68 + index), 12),
        }
        data["offers"].append(offer)
        if status != "DRAFT":
            approver = data["hiring_managers"][(index + 2) % len(data["hiring_managers"])]
            decision = "PENDING" if status == "PENDING_APPROVAL" else "APPROVED"
            decision_at = None if decision == "PENDING" else _ts(BASE_DATE + timedelta(days=69 + index), 13)
            approval_id = generate_approval_id(index + 1)
            data["approvals"].append(
                {
                    "approval_id": approval_id,
                    "offer_id": offer_id,
                    "approval_sequence": 1,
                    "approval_stage": "COMPENSATION",
                    "approval_type": "STANDARD",
                    "approver_id": approver["hiring_manager_id"],
                    "approver_name_snapshot": approver["name"],
                    "approver_role": "Finance approver",
                    "decision": decision,
                    "comments": None if decision == "PENDING" else "Offer compensation is within the approved band.",
                    "decided_at": decision_at,
                    "created_at": _ts(BASE_DATE + timedelta(days=68 + index), 12),
                }
            )
            if decision_at:
                _audit(
                    audit_events,
                    "APPROVAL_DECIDED",
                    "Approval",
                    approval_id,
                    decision_at,
                    previous_state="PENDING",
                    new_state="APPROVED",
                    actor_id=approver["hiring_manager_id"],
                    actor_name=approver["name"],
                    reason="Offer approval recorded.",
                    related_entity_type="Offer",
                    related_entity_id=offer_id,
                )
        _audit(
            audit_events,
            "STATUS_CHANGED",
            "Offer",
            offer_id,
            offer["updated_at"],
            previous_state="DRAFT",
            new_state=status,
            actor_id=manager_ids[index % len(manager_ids)],
            actor_name=data["hiring_managers"][index % len(manager_ids)]["name"],
            reason="Synthetic offer lifecycle transition.",
            related_entity_type="Application",
            related_entity_id=application["application_id"],
        )

    interview_specs: list[tuple[dict[str, Any], int, str]] = []
    for index, application in enumerate(data["applications"][:offers_count]):
        for round_number, interview_type in enumerate(("TECHNICAL", "MANAGERIAL", "HR"), start=1):
            interview_specs.append((application, round_number, interview_type))
    for application in data["applications"][offers_count : offers_count + config["interviews"] - 3 * offers_count]:
        interview_specs.append((application, 1, "TECHNICAL"))

    panel_interviewers: dict[str, list[str]] = {}
    for membership in data["panel_interviewers"]:
        panel_interviewers.setdefault(membership["panel_id"], []).append(membership["interviewer_id"])
    booked_slots: dict[tuple[date, int], set[str]] = {}
    scheduled_dates: set[tuple[str, date]] = set()
    interviewer_by_id = {row["interviewer_id"]: row for row in data["interviewers"]}
    for index, (application, round_number, interview_type) in enumerate(interview_specs):
        preferred_panel = index % panel_count
        candidate_resource = f"candidate:{application['candidate_id']}"
        scheduled_slot: tuple[date, int, int] | None = None
        for day_offset in range(3650):
            interview_date = BASE_DATE + timedelta(days=35 + day_offset)
            for start_hour in range(9, 17):
                for panel_offset in range(panel_count):
                    panel_index = (preferred_panel + panel_offset) % panel_count
                    panel_id = f"PANEL-{panel_index + 1:04d}"
                    panel_members = panel_interviewers[panel_id]
                    resources = set(panel_members) | {candidate_resource}
                    if not resources.intersection(booked_slots.get((interview_date, start_hour), set())):
                        scheduled_slot = (interview_date, start_hour, panel_index)
                        booked_slots.setdefault((interview_date, start_hour), set()).update(resources)
                        break
                if scheduled_slot is not None:
                    break
            if scheduled_slot is not None:
                break
        if scheduled_slot is None:
            raise RuntimeError(f"No conflict-free interview slot found for {application['application_id']}.")
        interview_date, start_hour, panel_index = scheduled_slot
        start_at = _ts(interview_date, start_hour)
        end_at = start_at + timedelta(minutes=60)
        panel_id = f"PANEL-{panel_index + 1:04d}"
        interview_id = generate_interview_id(2026, index + 1)
        panel_members = panel_interviewers[panel_id]
        data["interviews"].append(
            {
                "interview_id": interview_id,
                "application_id": application["application_id"],
                "panel_id": panel_id,
                "interview_round": round_number,
                "interview_type": interview_type,
                "start_at": start_at,
                "end_at": end_at,
                "duration_minutes": 60,
                "status": "COMPLETED",
                "location": "Remote",
                "cancellation_reason": None,
                "scheduled_by": panel_members[0],
                "created_at": start_at - timedelta(days=7),
                "updated_at": end_at,
            }
        )
        for interviewer_id in panel_members:
            scheduled_dates.add((interviewer_id, interview_date))
        for reviewer_index, reviewer_id in enumerate(panel_members):
            reviewer = interviewer_by_id[reviewer_id]
            scorecard_id = f"{generate_scorecard_id(interview_id, 1)}-{reviewer_id}"
            raw_scores = [Decimal(rng.randint(3, 5)) for _ in range(criteria_count)]
            weights = [row["default_weight"] for row in data["evaluation_criteria"]]
            overall_score = sum(score * weight for score, weight in zip(raw_scores, weights)) / sum(weights)
            overall_score = overall_score.quantize(Decimal("0.001"))
            recommendation = (
                "STRONG_HIRE" if overall_score >= 4 else "HIRE_FURTHER_REVIEW" if overall_score >= 3 else "NO_HIRE"
            )
            submitted_at = start_at + timedelta(hours=2 + reviewer_index)
            data["scorecards"].append(
                {
                    "scorecard_id": scorecard_id,
                    "interview_id": interview_id,
                    "reviewer_id": reviewer_id,
                    "supersedes_scorecard_id": None,
                    "revision_no": 1,
                    "recommendation": recommendation,
                    "overall_score": overall_score,
                    "completion_status": "SUBMITTED",
                    "submitted_at": submitted_at,
                    "created_at": start_at + timedelta(minutes=15 + reviewer_index),
                }
            )
            for criterion_index, (criterion, rating) in enumerate(zip(data["evaluation_criteria"], raw_scores), start=1):
                data["scorecard_criteria"].append(
                    {
                        "scorecard_criteria_id": f"SC-{index + 1:06d}-{reviewer_index + 1:02d}-{criterion_index:02d}",
                        "scorecard_id": scorecard_id,
                        "criterion_id": criterion["criterion_id"],
                        "rating": int(rating),
                        "comments": "Evidence-based rating recorded.",
                        "criterion_name_snapshot": criterion["criterion_name"],
                        "weight_snapshot": criterion["default_weight"],
                        "maximum_rating_snapshot": 5,
                        "mandatory_snapshot": True,
                        "created_at": submitted_at,
                    }
                )
        _audit(
            audit_events,
            "STATUS_CHANGED",
            "Interview",
            interview_id,
            end_at,
            previous_state="SCHEDULED",
            new_state="COMPLETED",
            actor_id=panel_members[0],
            actor_name=interviewer_by_id[panel_members[0]]["name"],
            reason="Interview completed as scheduled.",
            related_entity_type="Application",
            related_entity_id=application["application_id"],
        )
        if index % 7 == 0:
            previous_start = start_at - timedelta(days=1)
            data["interview_reschedule_history"].append(
                {
                    "reschedule_history_id": f"RESCHED-{index + 1:06d}-01",
                    "interview_id": interview_id,
                    "reschedule_sequence": 1,
                    "previous_start_at": previous_start,
                    "previous_end_at": previous_start + timedelta(minutes=60),
                    "new_start_at": start_at,
                    "new_end_at": end_at,
                    "actor_id": application["candidate_id"],
                    "actor_name_snapshot": next(
                        candidate["first_name"] + " " + candidate["last_name"]
                        for candidate in data["candidates"]
                        if candidate["candidate_id"] == application["candidate_id"]
                    ),
                    "reason": "Candidate requested a scheduling change.",
                    "occurred_at": start_at - timedelta(days=2),
                }
            )

    interviews_by_application: dict[str, list[dict[str, Any]]] = {}
    for interview in data["interviews"]:
        interviews_by_application.setdefault(interview["application_id"], []).append(interview)
    history_by_application: dict[str, list[dict[str, Any]]] = {}
    for history in data["application_stage_history"]:
        history_by_application.setdefault(history["application_id"], []).append(history)
    for application_id, application_interviews in interviews_by_application.items():
        application_interviews.sort(key=lambda row: row["interview_round"])
        histories = history_by_application[application_id]
        for interview in application_interviews:
            stage = f"{interview['interview_type']}_INTERVIEW"
            stage_history = next(row for row in histories if row["new_stage"] == stage)
            stage_history["occurred_at"] = interview["end_at"] + timedelta(minutes=1)
            stage_history["reason"] = f"{stage.title().replace('_', ' ')} completed."
            for event in audit_events:
                if (
                    event["entity_type"] == "Application"
                    and event["entity_id"] == application_id
                    and event["event_type"] == "STAGE_CHANGED"
                    and event["new_state"] == stage
                ):
                    event["occurred_at"] = stage_history["occurred_at"]
                    event["reason"] = stage_history["reason"]

        application = applications_by_id[application_id]
        latest_history = max(histories, key=lambda row: row["history_sequence"])
        latest_interview_end = application_interviews[-1]["end_at"]
        if application["current_stage"] in {"OFFER", "HIRED"}:
            offer_history = next(row for row in histories if row["new_stage"] == "OFFER")
            offer_history["occurred_at"] = latest_interview_end + timedelta(days=1)
            offer_history["reason"] = "Offer stage entered after required interviews."
            for event in audit_events:
                if (
                    event["entity_type"] == "Application"
                    and event["entity_id"] == application_id
                    and event["event_type"] == "STAGE_CHANGED"
                    and event["new_state"] == "OFFER"
                ):
                    event["occurred_at"] = offer_history["occurred_at"]
                    event["reason"] = offer_history["reason"]
        if application["current_stage"] == "OFFER":
            latest_history["occurred_at"] = latest_interview_end + timedelta(days=1)
        elif application["current_stage"] == "HIRED":
            offer = next(row for row in data["offers"] if row["application_id"] == application_id)
            offer_created_at = latest_interview_end + timedelta(days=2)
            sent_at = latest_interview_end + timedelta(days=4)
            offer["created_at"] = offer_created_at
            offer["sent_at"] = sent_at
            offer["expires_at"] = sent_at + timedelta(days=14)
            offer["offer_date"] = sent_at.date()
            offer["accepted_at"] = sent_at + timedelta(days=2)
            offer["joining_date"] = offer["accepted_at"].date() + timedelta(days=30)
            offer["updated_at"] = offer["accepted_at"]
            latest_history["occurred_at"] = offer["accepted_at"]
        application["updated_at"] = latest_history["occurred_at"]
        for event in audit_events:
            if (
                event["entity_type"] == "Application"
                and event["entity_id"] == application_id
                and event["event_type"] == "STAGE_CHANGED"
                and event["new_state"] == latest_history["new_stage"]
            ):
                event["occurred_at"] = latest_history["occurred_at"]
                event["reason"] = latest_history["reason"]

    for offer in data["offers"]:
        application_interviews = interviews_by_application[offer["application_id"]]
        latest_interview_end = max(row["end_at"] for row in application_interviews)
        status = offer["status"]
        offer["created_at"] = latest_interview_end + timedelta(days=2)
        offer["updated_at"] = offer["created_at"]
        if status in {"SENT", "ACCEPTED", "DECLINED"}:
            offer["sent_at"] = latest_interview_end + timedelta(days=4)
            offer["expires_at"] = offer["sent_at"] + timedelta(days=14)
            offer["offer_date"] = offer["sent_at"].date()
            offer["updated_at"] = offer["sent_at"]
        if status == "ACCEPTED":
            offer["accepted_at"] = offer["sent_at"] + timedelta(days=2)
            offer["joining_date"] = offer["accepted_at"].date() + timedelta(days=30)
            offer["updated_at"] = offer["accepted_at"]
        elif status == "DECLINED":
            offer["declined_at"] = offer["sent_at"] + timedelta(days=3)
            offer["updated_at"] = offer["declined_at"]
        approval = next((row for row in data["approvals"] if row["offer_id"] == offer["offer_id"]), None)
        if approval:
            approval["created_at"] = offer["created_at"]
            if approval["decision"] == "APPROVED":
                approval["decided_at"] = latest_interview_end + timedelta(days=3)
                for event in audit_events:
                    if event["entity_type"] == "Approval" and event["entity_id"] == approval["approval_id"]:
                        event["occurred_at"] = approval["decided_at"]
        for event in audit_events:
            if event["entity_type"] == "Offer" and event["entity_id"] == offer["offer_id"]:
                event["occurred_at"] = offer["updated_at"]

    for interviewer_id, interview_date in sorted(scheduled_dates):
        data["availability"].append(
            {
                "availability_id": f"AV-{interviewer_id}-{interview_date:%Y%m%d}",
                "interviewer_id": interviewer_id,
                "available_start": _ts(interview_date, 9),
                "available_end": _ts(interview_date, 17),
                "availability_status": "AVAILABLE",
                "created_at": _ts(interview_date - timedelta(days=14), 9),
            }
        )

    metadata = {
        "dataset_name": "recruitment_management_starter" if scale == "starter" else "recruitment_management_full",
        "seed": seed,
        "scale": scale,
        "generated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "configuration": config,
        "record_counts": {table_name: len(data[table_name]) for table_name in TABLE_NAMES},
    }
    data["metadata"] = metadata
    return data
