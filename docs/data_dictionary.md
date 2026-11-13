# Implemented PostgreSQL Data Dictionary

This dictionary describes the SQLAlchemy/Alembic PostgreSQL schema. Unless
noted otherwise, IDs are immutable
`VARCHAR(80)` primary keys, text values are trimmed, identity emails and
canonical skill names are normalized to lowercase before storage,
timestamps are `TIMESTAMPTZ` stored and compared as instants, and `created_at`
defaults to `CURRENT_TIMESTAMP`. Row-local rules are enforced by database
constraints where expressible; cross-table and historical rules are enforced
by transactionally consistent services. `—` means no default or
uniqueness rule.

The PostgreSQL DDL is generated from SQLAlchemy metadata into
`../database/schema.sql`. Rules requiring approval policy configuration,
immutable decision history, rubric applicability, full interview availability,
or overlap protection remain service-level checks and are identified in
[database_design.md](./database_design.md).

The ID generator must use deterministic ordering and these formats where
applicable: requisition `REQ-2026-000001`; candidate `CAND-000001`;
application `APP-CAND-000001-REQ-2026-000001`; interview `INT-2026-000001`;
scorecard `SCORE-INT-2026-000001-REV-000001`; offer `OFF-2026-000001`.
Other IDs use stable entity prefixes and zero-padded counters (for example
`HM-000001`, `REQAPP-000001`, `INTV-000001`, `PANEL-000001`, `SKILL-000001`,
`STAGE-000001`, `RESCHED-000001`, and `AUDIT-000001`).

## Core entities

### HiringManager

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| hiring_manager_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `HM-NNNNNN` convention. |
| employee_code | VARCHAR(40) | Yes | — | — | Yes | — | Non-empty; normalized case-insensitively. |
| name | VARCHAR(200) | Yes | — | — | — | — | Non-empty. |
| email | VARCHAR(320) | Yes | — | — | Yes | — | Valid email; normalized case-insensitively. |
| department | VARCHAR(100) | Yes | — | — | — | — | Non-empty organization department. |
| phone | VARCHAR(32) | No | — | NULL | — | — | E.164 preferred; do not use as identity. |
| active_status | VARCHAR(16) | Yes | — | `ACTIVE`, `INACTIVE`; default `ACTIVE` | — | — | Inactive managers cannot own newly opened requisitions. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| updated_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Updated on changes; must be >= `created_at`. |

### Requisition

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| requisition_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `REQ-YYYY-NNNNNN`. |
| hiring_manager_id | VARCHAR(80) | Yes | FK → HiringManager | — | — | — | Parent manager must exist and be active when requisition opens. |
| title | VARCHAR(200) | Yes | — | — | — | — | Non-empty. |
| description | TEXT | No | — | NULL | — | — | Plain text; no candidate PII. |
| department | VARCHAR(100) | Yes | — | — | — | — | Non-empty. |
| job_family | VARCHAR(100) | Yes | — | — | — | — | Non-empty; normalized family used for role-specific criterion applicability. |
| location | VARCHAR(160) | Yes | — | — | — | — | Non-empty location or explicitly configured remote location. |
| employment_type | VARCHAR(20) | Yes | — | `FULL_TIME`, `PART_TIME`, `CONTRACT`, `TEMPORARY`, `INTERN` | — | — | Must be one of the enumerated values. |
| work_mode | VARCHAR(16) | Yes | — | `ONSITE`, `HYBRID`, `REMOTE` | — | — | Must be one of the enumerated values. |
| headcount | SMALLINT | Yes | — | — | — | positions | Greater than zero. |
| status | VARCHAR(24) | Yes | — | `DRAFT`, `PENDING_APPROVAL`, `OPEN`, `ON_HOLD`, `FILLED`, `CLOSED`, `CANCELLED`; default `DRAFT` | — | — | Only documented lifecycle transitions are permitted. |
| min_salary | NUMERIC(12,2) | No | — | NULL until compensation band is approved | — | currency units per compensation period | Non-negative while draft; positive and <= `max_salary` before opening. |
| max_salary | NUMERIC(12,2) | No | — | NULL until compensation band is approved | — | currency units per compensation period | Positive and >= `min_salary`; required before opening. |
| currency_code | CHAR(3) | No | — | NULL until band approval | — | ISO 4217 | Required before opening; uppercase recognized ISO currency. |
| compensation_period | VARCHAR(12) | No | — | NULL until band approval; then `YEAR`, `MONTH`, `HOUR` | — | — | Required before opening; band amounts use this same period. |
| opening_date | DATE | Yes | — | — | — | calendar date | Must be <= `closing_date` when the latter is set. |
| closing_date | DATE | No | — | NULL | — | calendar date | Must be >= `opening_date`. |
| approved_at | TIMESTAMPTZ | No | — | NULL | — | instant | Set when approved; required for `OPEN` and later states. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| updated_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Updated on changes; must be >= `created_at`. |

### RequisitionApproval

This entity records the requisition-opening workflow only. It is not the offer
`Approval` entity.

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| requisition_approval_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `REQAPP-NNNNNN`. |
| requisition_id | VARCHAR(80) | Yes | FK → Requisition | — | — | — | Requisition must exist; deletion is restricted. |
| approver_id | VARCHAR(80) | Yes | — | — | — | — | Stable organization identity; no FK because approvers are not limited to hiring managers/interviewers. |
| approval_cycle | INTEGER | Yes | — | `1` | — | cycle number | >= 1; each requisition submission for approval has a new cycle. The current cycle is the highest cycle number created for the latest submission. |
| approval_sequence | SMALLINT | Yes | — | — | — | sequence number | >= 1; identifies ordered approval step within a cycle. |
| approval_stage | VARCHAR(80) | Yes | — | — | — | — | Must match a stage in the configured requisition approval policy. |
| decision | VARCHAR(24) | Yes | — | `PENDING`, `APPROVED`, `REJECTED`, `RETURNED_FOR_REVISION`; default `PENDING` | — | — | May transition once from `PENDING` to a decided value; decided value is immutable. |
| comments | TEXT | No | — | NULL | — | — | Required when decision is `REJECTED` or `RETURNED_FOR_REVISION`; reason must be meaningful. |
| requested_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Must be set when the approval step is requested; immutable. |
| decided_at | TIMESTAMPTZ | No | — | NULL | — | instant | Null iff `PENDING`; required for a decided state and must be >= `requested_at`. |
| supersedes_requisition_approval_id | VARCHAR(80) | No | FK → RequisitionApproval | NULL | — | — | Optional link to a prior request being reconsidered; both rows must refer to the same requisition and stage. Prior decisions are never overwritten. |
| — requisition_id, approval_cycle, approval_sequence — | — | — | UQ (composite) | — | Yes | — | One record per ordered approval step per requisition submission cycle. |

### Candidate

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| candidate_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `CAND-NNNNNN`. |
| first_name | VARCHAR(100) | Yes | — | — | — | — | Non-empty. |
| last_name | VARCHAR(100) | Yes | — | — | — | — | Non-empty. |
| email | VARCHAR(320) | Yes | — | — | Yes | — | Valid, normalized case-insensitively; synthetic data must use a reserved example domain. |
| phone | VARCHAR(32) | No | — | NULL | — | — | Optional; E.164 preferred. |
| location | VARCHAR(160) | No | — | NULL | — | — | Free-text city/region; not a precise address. |
| education_level | VARCHAR(24) | No | — | NULL; `SECONDARY`, `ASSOCIATE`, `BACHELOR`, `MASTER`, `DOCTORATE`, `OTHER` | — | — | If present, one enumerated value. |
| education_summary | VARCHAR(500) | No | — | NULL | — | — | Optional summary; no unsupported credentials. |
| total_experience_months | INTEGER | Yes | — | `0` | — | months | >= 0; source of candidate's overall experience. |
| profile_created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Must not be in the future. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| updated_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Updated on changes; must be >= `created_at`. |

### Application

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| application_id | VARCHAR(160) | Yes | PK | — | Yes | — | Immutable; derived from the exact candidate and requisition IDs. |
| candidate_id | VARCHAR(80) | Yes | FK → Candidate | — | — | — | Candidate must exist. |
| requisition_id | VARCHAR(80) | Yes | FK → Requisition | — | — | — | Requisition must exist and be accepting applications at submission. |
| applied_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Must not be in the future. |
| current_stage | VARCHAR(32) | Yes | — | `APPLIED` | — | — | One of `APPLIED`, `SCREENING`, `ASSESSMENT`, `TECHNICAL_INTERVIEW`, `MANAGERIAL_INTERVIEW`, `HR_INTERVIEW`, `OFFER`, `HIRED`, `REJECTED`, `WITHDRAWN`. |
| status | VARCHAR(12) | Yes | — | `ACTIVE`; `ACTIVE`, `ON_HOLD`, `CLOSED` | — | — | `CLOSED` iff stage is terminal (`HIRED`, `REJECTED`, `WITHDRAWN`); otherwise `ACTIVE` or `ON_HOLD`. |
| source_channel | VARCHAR(32) | Yes | — | `CAREER_SITE`; `CAREER_SITE`, `REFERRAL`, `JOB_BOARD`, `AGENCY`, `DIRECT`, `OTHER` | — | — | Enumerated; do not store untrusted free-form data here. |
| source_detail | VARCHAR(200) | No | — | NULL | — | — | Optional attribution detail; no sensitive data. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| updated_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Updated on changes; must be >= `created_at`. |
| — candidate_id, requisition_id — | — | — | UQ (composite) | — | Yes | — | One application per candidate/requisition pair; reapplication requires a distinct requisition. |

### Skill

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| skill_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `SKILL-NNNNNN`. |
| skill_name | VARCHAR(100) | Yes | — | — | Yes | — | Trimmed and normalized case-insensitively. |
| skill_category | VARCHAR(40) | No | — | NULL | — | — | Optional category, e.g. technical, language, or domain. |
| active_status | VARCHAR(12) | Yes | — | `ACTIVE`, `INACTIVE`; default `ACTIVE` | — | — | Inactive skills remain available for historical references. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |

### SkillRequirement

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| skill_requirement_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `SKREQ-NNNNNN`. |
| requisition_id | VARCHAR(80) | Yes | FK → Requisition | — | — | — | Parent requisition must exist. |
| skill_id | VARCHAR(80) | Yes | FK → Skill | — | — | — | Skill must exist. |
| requirement_type | VARCHAR(12) | Yes | — | `MANDATORY`, `PREFERRED` | — | — | One enumerated value. |
| minimum_proficiency | SMALLINT | Yes | — | `1` | — | 1–5 scale | Between 1 and 5 inclusive. |
| minimum_experience_months | INTEGER | Yes | — | `0` | — | months | >= 0. |
| weight | NUMERIC(6,3) | Yes | — | `1.000` | — | relative weight | > 0; used only where a weighted skill score is calculated. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| — requisition_id, skill_id — | — | — | UQ (composite) | — | Yes | — | A skill is specified once per requisition. |

### CandidateSkill

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| candidate_skill_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `CANSKILL-NNNNNN`. |
| candidate_id | VARCHAR(80) | Yes | FK → Candidate | — | — | — | Candidate must exist. |
| skill_id | VARCHAR(80) | Yes | FK → Skill | — | — | — | Skill must exist. |
| proficiency_level | VARCHAR(16) | Yes | — | `NOVICE`, `BEGINNER`, `INTERMEDIATE`, `ADVANCED`, `EXPERT` | — | 1–5 scale | Ordered 1 through 5 respectively; compared with SkillRequirement.minimum_proficiency. |
| experience_months | INTEGER | Yes | — | `0` | — | months | >= 0. |
| last_used_on | DATE | No | — | NULL | — | calendar date | Cannot be in the future. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| — candidate_id, skill_id — | — | — | UQ (composite) | — | Yes | — | One current proficiency record per candidate/skill. |

### InterviewPanel

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| panel_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `PANEL-NNNNNN`. |
| panel_name | VARCHAR(120) | Yes | — | — | — | — | Non-empty. |
| panel_type | VARCHAR(24) | Yes | — | `TECHNICAL`, `MANAGERIAL`, `HR`, `GENERAL` | — | — | Enumerated. |
| active_status | VARCHAR(12) | Yes | — | `ACTIVE`, `INACTIVE`; default `ACTIVE` | — | — | Inactive panel cannot receive new interviews. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| updated_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Updated on changes. |

### Interviewer

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| interviewer_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `INTV-NNNNNN`. |
| employee_code | VARCHAR(40) | Yes | — | — | Yes | — | Non-empty; normalized case-insensitively. |
| name | VARCHAR(200) | Yes | — | — | — | — | Non-empty. |
| email | VARCHAR(320) | Yes | — | — | Yes | — | Valid email; normalized case-insensitively. |
| department | VARCHAR(100) | Yes | — | — | — | — | Non-empty. |
| designation | VARCHAR(100) | Yes | — | — | — | — | Non-empty job title. |
| active_status | VARCHAR(12) | Yes | — | `ACTIVE`, `INACTIVE`; default `ACTIVE` | — | — | Inactive interviewers cannot be newly assigned or booked. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| updated_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Updated on changes. |

### PanelInterviewer

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| panel_interviewer_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `PANELMEM-NNNNNN`. |
| panel_id | VARCHAR(80) | Yes | FK → InterviewPanel | — | — | — | Panel must exist. |
| interviewer_id | VARCHAR(80) | Yes | FK → Interviewer | — | — | — | Interviewer must exist and be active during membership. |
| role_in_panel | VARCHAR(40) | Yes | — | `LEAD`, `INTERVIEWER`, `OBSERVER`, `SPECIALIST` | — | — | Enumerated. |
| effective_from | DATE | Yes | — | — | — | calendar date | <= `effective_to` when end is set. |
| effective_to | DATE | No | — | NULL means current membership | — | calendar date | >= `effective_from`; membership must cover every local calendar date touched by the interview interval. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| — panel_id, interviewer_id, effective_from — | — | — | UQ (composite) | — | Yes | — | Prevent duplicate memberships starting on the same date; overlapping membership intervals must be rejected by service validation. |

### Availability

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| availability_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `AVAIL-NNNNNN`. |
| interviewer_id | VARCHAR(80) | Yes | FK → Interviewer | — | — | — | Interviewer must exist. |
| available_start | TIMESTAMPTZ | Yes | — | — | — | instant | Must be earlier than `available_end`. |
| available_end | TIMESTAMPTZ | Yes | — | — | — | instant | Must be later than `available_start`. |
| availability_status | VARCHAR(16) | Yes | — | `AVAILABLE`, `UNAVAILABLE`, `BLOCKED` | — | — | Only `AVAILABLE` intervals satisfy a booking. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| — interviewer_id, available_start, available_end — | — | — | UQ (composite) | — | Yes | — | Exact duplicate interval prohibited; ambiguous overlapping intervals for one interviewer must be rejected/serialized by scheduling service. |

### Interview

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| interview_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `INT-YYYY-NNNNNN`. |
| application_id | VARCHAR(160) | Yes | FK → Application | — | — | — | Application must exist and not be withdrawn, rejected, or hired when scheduling. |
| panel_id | VARCHAR(80) | Yes | FK → InterviewPanel | — | — | — | Active panel must exist and have at least one active, effective member. |
| interview_round | SMALLINT | Yes | — | — | — | round number | >= 1; round label is derived/displayed by the application. |
| interview_type | VARCHAR(24) | Yes | — | `SCREENING`, `ASSESSMENT`, `TECHNICAL`, `MANAGERIAL`, `HR`, `OTHER` | — | — | Must be appropriate for the application stage. |
| start_at | TIMESTAMPTZ | Yes | — | — | — | instant | Must be earlier than `end_at`; availability and conflicts use half-open interval `[start_at,end_at)`. |
| end_at | TIMESTAMPTZ | Yes | — | — | — | instant | Must be later than `start_at`. |
| duration_minutes | SMALLINT | Yes | — | — | — | minutes | > 0 and exactly equal to `(end_at - start_at)` in whole minutes. |
| status | VARCHAR(16) | Yes | — | `SCHEDULED`, `CONFIRMED`, `COMPLETED`, `CANCELLED`, `NO_SHOW`; default `SCHEDULED` | — | — | Only active scheduled states block calendars; reschedule is represented in history and does not erase the old time. |
| location | VARCHAR(200) | No | — | NULL | — | — | Required for onsite; valid meeting URI or location when supplied. |
| cancellation_reason | TEXT | No | — | NULL | — | — | Required when status becomes `CANCELLED`. |
| scheduled_by | VARCHAR(80) | No | — | NULL | — | — | Actor identity; no FK because actors may be outside the interviewer roster. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| updated_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Updated on changes. |
| — panel_id, start_at, end_at — | — | — | — | — | — | — | Pairwise interviewer conflicts are prevented transactionally by the scheduling service; database locks/constraints must protect concurrent bookings. |

### EvaluationCriterion

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| criterion_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `CRIT-NNNNNN`. |
| criterion_code | VARCHAR(60) | Yes | — | — | Yes | — | Stable machine-readable code, normalized uppercase. |
| criterion_name | VARCHAR(120) | Yes | — | — | — | — | Non-empty. |
| description | TEXT | Yes | — | — | — | — | Defines the observable evaluation standard. |
| maximum_rating | SMALLINT | Yes | — | `5` | — | rating points | Current rating scale must be 1–5; maximum is 5. |
| default_weight | NUMERIC(6,3) | Yes | — | `1.000` | — | relative weight | > 0. |
| mandatory | BOOLEAN | Yes | — | `TRUE` or `FALSE` | — | — | Mandatory active criteria must be present in a submitted scorecard when applicable. |
| applicability_scope | VARCHAR(16) | Yes | — | `ALL`, `DEPARTMENT`, `JOB_FAMILY`, `SKILL` | — | — | `ALL` has null applicability value; other scopes require a value. |
| applicability_value | VARCHAR(120) | No | — | NULL | — | — | Must agree with applicability scope; used to flag irrelevant criteria. |
| active_status | VARCHAR(12) | Yes | — | `ACTIVE`, `INACTIVE`; default `ACTIVE` | — | — | Inactive criteria remain resolvable from historical scorecards. |
| effective_from | DATE | Yes | — | — | — | calendar date | <= `effective_to` when set. |
| effective_to | DATE | No | — | NULL | — | calendar date | >= `effective_from`; do not rewrite criteria used by submitted records. |

### Scorecard

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| scorecard_id | VARCHAR(120) | Yes | PK | — | Yes | — | Immutable; `SCORE-{interview_id}-REV-{revision_no:06d}`. |
| interview_id | VARCHAR(80) | Yes | FK → Interview | — | — | — | Interview must exist. |
| reviewer_id | VARCHAR(80) | Yes | FK → Interviewer | — | — | — | Reviewer must be an active interviewer assigned to the interview panel. |
| supersedes_scorecard_id | VARCHAR(120) | No | FK → Scorecard | NULL | — | — | If set, references the preceding revision for the same interview/reviewer. |
| revision_no | INTEGER | Yes | — | `1` | — | revision number | >= 1; starts at 1 and increments by exactly one per reviewer/interview revision chain. |
| recommendation | VARCHAR(24) | No | — | NULL until submitted; `STRONG_HIRE`, `HIRE_FURTHER_REVIEW`, `BORDERLINE`, `NO_HIRE` | — | — | On submission, must match configured weighted-score thresholds. |
| overall_score | NUMERIC(5,3) | No | — | NULL until calculated | — | points, 1–5 | Derived from criterion rating × weight snapshots; between 1 and 5 when submitted. |
| completion_status | VARCHAR(12) | Yes | — | `DRAFT`, `SUBMITTED`, `SUPERSEDED`; default `DRAFT` | — | — | Ratings and rubric snapshots are immutable after submission; only status may transition to `SUPERSEDED` when an explicit revision is created, and that transition is audited. |
| submitted_at | TIMESTAMPTZ | No | — | NULL | — | instant | Required iff status is `SUBMITTED` or `SUPERSEDED`; set once on submission. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| — interview_id, reviewer_id, revision_no — | — | — | UQ (composite) | — | Yes | — | Prevents duplicate same-revision scorecards; a correction requires an explicit next revision and supersedes link. |

### ScorecardCriteria

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| scorecard_criteria_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `SCORECRIT-NNNNNN`. |
| scorecard_id | VARCHAR(120) | Yes | FK → Scorecard | — | — | — | Parent scorecard must exist and be editable while draft. |
| criterion_id | VARCHAR(80) | Yes | FK → EvaluationCriterion | — | — | — | Definition must exist; applicability checked against role/skill. |
| rating | SMALLINT | Yes | — | — | — | 1–5 points | Must be integer >= 1 and <= the snapshotted maximum rating. |
| comments | TEXT | No | — | NULL | — | — | Optional; must not contain prohibited sensitive information. |
| criterion_name_snapshot | VARCHAR(120) | Yes | — | — | — | — | Copy of criterion label at evaluation time; preserves historical meaning. |
| weight_snapshot | NUMERIC(6,3) | Yes | — | — | — | relative weight | > 0; copy of criterion weight at evaluation time. |
| maximum_rating_snapshot | SMALLINT | Yes | — | — | — | rating points | Must be 5 under the current rubric; rating cannot exceed it. |
| mandatory_snapshot | BOOLEAN | Yes | — | — | — | — | Copy of mandatory flag at evaluation time. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| — scorecard_id, criterion_id — | — | — | UQ (composite) | — | Yes | — | A criterion appears at most once in one scorecard revision. |

### Offer

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| offer_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `OFF-YYYY-NNNNNN`. |
| application_id | VARCHAR(160) | Yes | FK → Application | — | — | — | Application must exist and satisfy selection requirements. |
| supersedes_offer_id | VARCHAR(80) | No | FK → Offer | NULL | — | — | If set, previous offer must belong to the same application; do not overwrite a sent offer. |
| offer_version | INTEGER | Yes | — | `1` | — | version number | >= 1; increments within the application offer chain. |
| proposed_salary | NUMERIC(12,2) | Yes | — | — | — | currency units per period | > 0; an out-of-band value may be retained and flagged, but cannot progress to approved/sent/accepted without approved exception approval. |
| band_min_snapshot | NUMERIC(12,2) | Yes | — | — | — | currency units per period | Copy of approved requisition minimum at offer creation; <= maximum snapshot. |
| band_max_snapshot | NUMERIC(12,2) | Yes | — | — | — | currency units per period | Copy of approved requisition maximum at offer creation; >= minimum snapshot. |
| currency_code | CHAR(3) | Yes | — | — | — | ISO 4217 | Must match requisition currency; no implicit currency conversion. |
| compensation_period | VARCHAR(12) | Yes | — | `YEAR`, `MONTH`, `HOUR` | — | — | Must match requisition band period. |
| status | VARCHAR(24) | Yes | — | `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, `SENT`, `ACCEPTED`, `DECLINED`, `RETURNED_FOR_REVISION`, `REJECTED`, `EXPIRED`, `WITHDRAWN` | — | — | Lifecycle transitions only; `APPROVED`, `SENT`, and `ACCEPTED` require all standard approvals and approved exception approval for out-of-band proposals; `ACCEPTED` also requires a sent offer. |
| exception_reason | TEXT | No | — | NULL | — | — | Required whenever proposed salary is outside the snapshotted band, including a flagged pending anomaly. |
| offer_date | DATE | No | — | NULL | — | calendar date | Required before `SENT`; not before creation date. |
| joining_date | DATE | No | — | NULL | — | calendar date | Required before `SENT`; must be after acceptance/offer date as policy specifies. |
| expires_at | TIMESTAMPTZ | No | — | NULL | — | instant | Must be after sent time; acceptance after expiry is invalid absent explicit extension history. |
| sent_at | TIMESTAMPTZ | No | — | NULL | — | instant | Required for `SENT`, `ACCEPTED`, `DECLINED`, or `EXPIRED`. |
| accepted_at | TIMESTAMPTZ | No | — | NULL | — | instant | Required iff `ACCEPTED`; >= `sent_at`. |
| declined_at | TIMESTAMPTZ | No | — | NULL | — | instant | Required iff `DECLINED`; >= `sent_at`. |
| created_by | VARCHAR(80) | Yes | — | — | — | — | Actor identity; audited, not necessarily a hiring manager. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once at insert. |
| updated_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Updated on changes; state changes also emit AuditEvent. |
| — application_id, offer_version — | — | — | UQ (composite) | — | Yes | — | One immutable offer record per application version. |

### Approval

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| approval_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `APPROVAL-NNNNNN`. |
| offer_id | VARCHAR(80) | Yes | FK → Offer | — | — | — | Offer must exist. |
| approval_sequence | SMALLINT | Yes | — | — | — | sequence number | >= 1; immutable ordering for approval trail. |
| approval_stage | VARCHAR(80) | Yes | — | — | — | — | Must match a configured offer approval step; independent of requisition approval stages. |
| approval_type | VARCHAR(28) | Yes | — | `STANDARD`, `COMPENSATION_EXCEPTION` | — | — | Out-of-band offer requires a separately approved `COMPENSATION_EXCEPTION`. |
| approver_id | VARCHAR(80) | Yes | — | — | — | — | Stable identity from the organization identity system; no FK because approvers need not be interviewers. |
| approver_name_snapshot | VARCHAR(200) | Yes | — | — | — | — | Name captured at decision time for audit. |
| approver_role | VARCHAR(80) | Yes | — | — | — | — | Required role/policy authority for this approval type. |
| decision | VARCHAR(24) | Yes | — | `PENDING`, `APPROVED`, `REJECTED`, `RETURNED_FOR_REVISION` | — | — | Pending has null decision time; final decisions have a timestamp. |
| comments | TEXT | No | — | NULL | — | — | Optional decision reason; rejection/return requires an explanation. |
| decided_at | TIMESTAMPTZ | No | — | NULL | — | instant | Null iff pending; otherwise required. |
| created_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Set once; a decided approval row is immutable. |
| — offer_id, approval_sequence — | — | — | UQ (composite) | — | Yes | — | One ordered approval step per offer. Offer revisions get new offer rows and separate approval rows. |

Offer `Approval` records are independent of `RequisitionApproval`: every
record references exactly one offer, never a requisition. A decision transitions
once from `PENDING` to a final value and is then immutable. A return/rejection
does not overwrite a decision; workflow policy sends the offer to its
appropriate terminal/revision path, with a revised proposal represented by a
new offer version and new approval rows.

## Historical and audit entities

### ApplicationStageHistory

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| stage_history_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `STAGE-NNNNNN`. |
| application_id | VARCHAR(160) | Yes | FK → Application | — | — | — | Application must exist; history is retained if application is closed. |
| history_sequence | INTEGER | Yes | — | — | — | sequence number | Positive, monotonically increasing within one application; allocated transactionally. |
| previous_stage | VARCHAR(32) | No | — | NULL only for initial event | — | — | Must equal the preceding recorded state. |
| new_stage | VARCHAR(32) | Yes | — | Application stage values | — | — | Must be a permitted transition from previous stage. |
| previous_status | VARCHAR(12) | No | — | NULL only for initial event | — | — | Application status values. |
| new_status | VARCHAR(12) | Yes | — | `ACTIVE`, `ON_HOLD`, `CLOSED` | — | — | Must be consistent with new stage and terminal-state rules. |
| actor_id | VARCHAR(80) | Yes | — | — | — | — | Stable actor identity; not assumed to be a Candidate or Interviewer. |
| actor_name_snapshot | VARCHAR(200) | Yes | — | — | — | — | Name as recorded at event time. |
| reason | TEXT | Yes | — | — | — | — | Non-empty reason for transition, hold, resume, rejection, or withdrawal. |
| occurred_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Event time; ordering is determined by the per-application sequence, not timestamp equality. |
| — application_id, history_sequence — | — | — | UQ (composite) | — | Yes | — | Enforces unique deterministic order within an application history chain. |

### InterviewRescheduleHistory

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| reschedule_history_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `RESCHED-NNNNNN`. |
| interview_id | VARCHAR(80) | Yes | FK → Interview | — | — | — | Interview must exist. |
| reschedule_sequence | INTEGER | Yes | — | — | — | sequence number | Positive, monotonically increasing within one interview; allocated transactionally. |
| previous_start_at | TIMESTAMPTZ | Yes | — | — | — | instant | Must be the interview's immediately previous scheduled start. |
| previous_end_at | TIMESTAMPTZ | Yes | — | — | — | instant | Must be after previous start. |
| new_start_at | TIMESTAMPTZ | Yes | — | — | — | instant | Must be before new end and pass availability/conflict checks. |
| new_end_at | TIMESTAMPTZ | Yes | — | — | — | instant | Must be after new start; duration rules still apply. |
| actor_id | VARCHAR(80) | Yes | — | — | — | — | Stable actor identity. |
| actor_name_snapshot | VARCHAR(200) | Yes | — | — | — | — | Name as recorded at reschedule time. |
| reason | TEXT | Yes | — | — | — | — | Non-empty reason. |
| occurred_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Immutable event time; reschedules append rows rather than editing prior rows. |
| — interview_id, reschedule_sequence — | — | — | UQ (composite) | — | Yes | — | Enforces unique deterministic order for one interview. |

### AuditEvent

| Field | PostgreSQL type | Required | Key | Allowed values / default | Unique | Unit | Validation |
|---|---|---:|---|---|---|---|---|
| audit_event_id | VARCHAR(80) | Yes | PK | — | Yes | — | Immutable; `AUDIT-NNNNNN`. |
| event_type | VARCHAR(40) | Yes | — | Controlled vocabulary such as `STATE_CHANGE`, `CREATE`, `UPDATE`, `DELETE_ATTEMPT`, `APPROVAL_DECISION` | — | — | Unknown event types rejected by audit service. |
| entity_type | VARCHAR(40) | Yes | — | Registered table/entity name | — | — | Must be in the audit service's allowlist. |
| entity_id | VARCHAR(160) | Yes | — | — | — | — | ID of the primary affected record; polymorphic reference, not a physical FK. |
| related_entity_type | VARCHAR(40) | No | — | NULL or registered entity name | — | — | Must be null together with related_entity_id or supplied together. |
| related_entity_id | VARCHAR(160) | No | — | NULL | — | — | ID of an optional related record; polymorphic reference, not a physical FK. |
| previous_state | TEXT | No | — | NULL | — | — | State before change; null for create/non-state events. |
| new_state | TEXT | No | — | NULL | — | — | State after change; null for events without a resulting state. |
| actor_type | VARCHAR(24) | Yes | — | `USER`, `SYSTEM`, `SERVICE` | — | — | Identifies actor category. |
| actor_id | VARCHAR(80) | No | — | NULL for anonymous system process only | — | — | Required for `USER`; stable identity, not a polymorphic FK. |
| actor_name_snapshot | VARCHAR(200) | No | — | NULL for anonymous system process only | — | — | Snapshot where actor is identifiable. |
| reason | TEXT | No | — | NULL | — | — | Required for consequential state changes, overrides, and exceptions. |
| occurred_at | TIMESTAMPTZ | Yes | — | `CURRENT_TIMESTAMP` | — | instant | Append-only; set by trusted service/database clock. |
| payload | JSONB | No | — | NULL | — | JSON object | Supplemental non-secret event details; never include credentials or ground-truth labels. |

## Referencing and deletion policy

All declared FK relationships use `ON DELETE RESTRICT` (or `NO ACTION`) for
operational and historical records. Business records are closed or marked
inactive rather than physically deleted. History and audit records are
append-only. No cascade may erase approvals, stage history, reschedule history,
or audit events. Polymorphic AuditEvent targets are verified by the audit
service because they cannot be protected by a normal multi-table FK.

For relationships, lifecycle transitions, cross-field checks, and constraints
that cannot be expressed as a PostgreSQL row-level constraint, see
[database_design.md](./database_design.md).
