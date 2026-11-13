# Recruitment Database Design Review

**Status:** Implemented with SQLAlchemy 2.x and PostgreSQL. The initial
Alembic revision is maintained in `migrations/versions/`; generated PostgreSQL
DDL is in `database/schema.sql`.

The schema retains the 11 requested core entities and ten supporting entities.
The ER diagram is at [er_diagram.md](./er_diagram.md); field specifications
are at [data_dictionary.md](./data_dictionary.md).

## Relationships and cardinalities

Cardinalities below describe the FK-backed proposed PostgreSQL schema. A
parent may have zero children unless otherwise stated; each child in an FK
relationship references exactly one parent.

| Parent | Child | Cardinality | Meaning / integrity rule |
|---|---|---|---|
| HiringManager | Requisition | 1 to 0..many | Every requisition has exactly one hiring manager. |
| Requisition | RequisitionApproval | 1 to 0..many | Each requisition approval record belongs to exactly one requisition; this is separate from offer approval. |
| RequisitionApproval | RequisitionApproval | 0..1 predecessor to 0..many successors | Optional self-reference identifies a reconsidered/retired record without altering its decision. |
| Requisition | SkillRequirement | 1 to 0..many | A requirement belongs to one requisition; `(requisition_id, skill_id)` is unique. |
| Skill | SkillRequirement | 1 to 0..many | A requirement references one canonical skill. |
| Requisition | Application | 1 to 0..many | Every application targets one requisition. |
| Candidate | Application | 1 to 0..many | Every application belongs to one candidate; one application per candidate/requisition pair. |
| Candidate | CandidateSkill | 1 to 0..many | Each row records one skill for one candidate. |
| Skill | CandidateSkill | 1 to 0..many | Each candidate-skill row references one canonical skill. |
| Application | Interview | 1 to 0..many | Each interview belongs to one application; multiple rounds are allowed. |
| InterviewPanel | Interview | 1 to 0..many | Each interview uses one panel; each panel may be reused across interviews. |
| InterviewPanel | PanelInterviewer | 1 to 0..many | Effective-dated bridge membership. |
| Interviewer | PanelInterviewer | 1 to 0..many | Effective-dated bridge membership; the panel member is not the interviewer entity. |
| Interviewer | Availability | 1 to 0..many | Availability is recorded per interviewer and time interval. |
| Interview | Scorecard | 1 to 0..many | Multiple independent reviewers and explicit revisions are supported. |
| Interviewer | Scorecard | 1 to 0..many | A reviewer is an interviewer assigned to that interview's panel. |
| Scorecard | ScorecardCriteria | 1 to 0..many | Each row is one scored criterion; submitted cards must contain all applicable mandatory criteria. |
| EvaluationCriterion | ScorecardCriteria | 1 to 0..many | Reusable definition, snapshotted on each scorecard line. |
| Application | Offer | 1 to 0..many | Historical offers are retained as separately versioned records. |
| Offer | Approval | 1 to 0..many | Each approval is a separate immutable decision in the approval sequence. |
| Offer | Offer | 0..1 predecessor to 0..many successors | Optional self-reference via `supersedes_offer_id`; a revised offer is a new version for the same application. |
| Scorecard | Scorecard | 0..1 predecessor to 0..many successors | Optional self-reference via `supersedes_scorecard_id`; revisions stay within one interview/reviewer chain. |
| Application | ApplicationStageHistory | 1 to 0..many | Initial state and every stage/status transition are recorded in a unique per-application sequence. |
| Interview | InterviewRescheduleHistory | 1 to 0..many | Each reschedule appends the prior and new interval and its reason in a unique per-interview sequence. |
| Any registered auditable entity | AuditEvent | logical 1 to 0..many | Polymorphic `entity_type/entity_id` and optional related pair; conceptual link only, not a physical FK. |

`AuditEvent` is intentionally not connected by ordinary FK lines in the ER
diagram: a generic audit row can target many tables, but a PostgreSQL FK cannot
refer to a table selected by a value. The dotted diagram relationships are
conceptual. The audit service must validate target types and existence and
restrict updates/deletes.

## Supporting entity rationale

| Supporting entity | Why it exists |
|---|---|
| RequisitionApproval | Dedicated FK-backed approval trail for opening requisitions, distinct from offer approvals; stores stage, approver, decision, comments, request and decision times. |
| Interviewer | Distinguishes a human reviewer/interviewer with the requested employee identity and active status from a panel membership record. |
| PanelInterviewer | Normalized many-to-many panel membership, including role and effective dates. It lets scheduling validate the panel roster on the interview date. |
| ScorecardCriteria | Stores one rating/comment per criterion per scorecard, instead of embedding scores in a single field or JSON array. Snapshot fields retain the rubric used. |
| ApplicationStageHistory | Preserves prior and next application stage/status, actor, time, and reason; it is not replaced when the current application row changes. |
| InterviewRescheduleHistory | Preserves every previous/new time interval, actor, timestamp, and reason when a meeting is moved. |
| AuditEvent | Cross-entity append-only audit mechanism for consequential changes not fully represented by specific history tables. Uses controlled polymorphic references. |
| Skill | Canonical skill catalog prevents spelling variants from splitting the same skill across candidates and requisitions. |
| CandidateSkill | Normalized candidate-to-skill bridge containing proficiency and experience; candidate skills are not stored as comma-separated text. |
| EvaluationCriterion | Reusable, effective-dated rubric definition with rating scale, weight, mandatory flag, and applicability. |

## Lifecycle states and permitted transitions

State names below are stored uppercase as documented in the dictionary.
Transitions are performed through one service layer; each change appends the
appropriate history and audit event. Any transition not explicitly listed is
invalid. A terminal state cannot be reopened; a new business record/version
must be created where supported.

### Requisition

| State | Permitted next state(s) | Terminal? |
|---|---|---:|
| `DRAFT` | `PENDING_APPROVAL`, `CANCELLED` | No |
| `PENDING_APPROVAL` | `DRAFT` (returned/rejected for revision), `OPEN` (all required requisition approvals approved), `CANCELLED` | No |
| `OPEN` | `ON_HOLD`, `FILLED`, `CLOSED`, `CANCELLED` | No |
| `ON_HOLD` | `OPEN`, `CLOSED`, `CANCELLED` | No |
| `FILLED` | `CLOSED` | No |
| `CLOSED` | None | Yes |
| `CANCELLED` | None | Yes |

`OPEN` requires a valid approved compensation band, active hiring manager, and
at least one `APPROVED` RequisitionApproval for every required stage in the
current `approval_cycle`. No pending, rejected, or returned-for-revision
decision may remain in that cycle. The current cycle is the highest cycle
number created for the latest requisition submission.
`RequisitionApproval` stores each approver decision and
timestamps; `AuditEvent` remains the general audit mechanism and separately
records consequential changes across requisition, requisition approval, offer,
and other entity types.

### RequisitionApproval

Each requisition approval record starts as `PENDING` and may transition once
to `APPROVED`, `REJECTED`, or `RETURNED_FOR_REVISION`. Decided rows are
immutable. Returning or rejecting a request prevents opening and sends the
requisition back to `DRAFT` (or to `CANCELLED` if abandoned). Resubmission
starts a new `approval_cycle`; prior decisions remain queryable but do not
count toward the current cycle. Within a cycle, `approval_sequence` orders
configured approval steps and `approval_stage` identifies the required step.
The approval policy defines the required stages and authorized approver roles
in sequence. Approver identities are
resolved through the organization's identity system rather than an FK to
Interviewer or HiringManager.

### Application

Pipeline stages are linear: `APPLIED` -> `SCREENING` -> `ASSESSMENT` ->
`TECHNICAL_INTERVIEW` -> `MANAGERIAL_INTERVIEW` -> `HR_INTERVIEW` -> `OFFER`
-> `HIRED`. No stage may be skipped. From any nonterminal stage,
`REJECTED` or `WITHDRAWN` may be entered. `HIRED`, `REJECTED`, and `WITHDRAWN`
are terminal; reopening requires a new application under the approved
reapplication policy.

Application status is `ACTIVE` while processing, may switch
`ACTIVE` <-> `ON_HOLD` without changing the pipeline stage, and becomes
`CLOSED` when the stage reaches `HIRED`, `REJECTED`, or `WITHDRAWN`. `CLOSED`
cannot return to an active state. Every stage or status change appends
ApplicationStageHistory; the initial event has null previous stage/status.

Advancement is gated by completion of the required review for the current
stage, including all applicable mandatory submitted scorecards before moving
past an interview stage. `OFFER` requires the configured selection reviews;
`HIRED` requires an accepted offer with required approvals. An application
that is rejected, withdrawn, or hired cannot be scheduled for a new interview.

### Interview

| State | Permitted next state(s) | Terminal? |
|---|---|---:|
| `SCHEDULED` | `CONFIRMED`, `COMPLETED`, `CANCELLED`, `NO_SHOW` | No |
| `CONFIRMED` | `COMPLETED`, `CANCELLED`, `NO_SHOW` | No |
| `COMPLETED` | None | Yes |
| `CANCELLED` | None | Yes |
| `NO_SHOW` | None | Yes |

Moving a `SCHEDULED` or `CONFIRMED` interview changes its current interval
only after validation and appends InterviewRescheduleHistory. A cancelled,
completed, or no-show interview cannot be rescheduled; create a new interview
if policy permits.

### Scorecard

`DRAFT` -> `SUBMITTED` -> `SUPERSEDED`. `SUPERSEDED` is terminal. A submitted
scorecard's ratings and rubric snapshots are immutable; its completion state
may move to `SUPERSEDED` only when audited as part of creating a new revision.
To correct it, create a new revision for the same
interview/reviewer with the next revision number and a `supersedes_scorecard_id`
to the prior revision. In the revision operation the prior submitted revision
is marked superseded and audited. Duplicate `(interview, reviewer, revision)`
records are prohibited. Drafts are not evaluations and cannot satisfy an
advancement gate.

### Offer

`DRAFT` -> `PENDING_APPROVAL`; from `PENDING_APPROVAL` -> `APPROVED`,
`RETURNED_FOR_REVISION`, `REJECTED`, or `WITHDRAWN`; from
`RETURNED_FOR_REVISION` -> `WITHDRAWN`; from `APPROVED` -> `SENT` or
`WITHDRAWN`; from `SENT` -> `ACCEPTED`, `DECLINED`, `EXPIRED`, or `WITHDRAWN`.
`ACCEPTED`, `DECLINED`, `EXPIRED`, `REJECTED`, and `WITHDRAWN` are terminal.
A returned offer is not edited into a new proposal: a revised proposal is a
new offer version that supersedes it and re-enters approval.

`ACCEPTED` requires `SENT`, unexpired offer, all required approvals, and
additional compensation-exception approval if the offer exceeds its band.

### Approval (Offer)

An approval decision is `PENDING` -> exactly one of `APPROVED`, `REJECTED`,
or `RETURNED_FOR_REVISION`. The three decided values are terminal and
immutable. The approval policy assigns an ordered `approval_sequence` and
`approval_stage` to each required approval row; `approval_type` distinguishes
standard and compensation-exception steps. A prior decision is never
overwritten. Offer workflow transitions require all configured standard
approvals; out-of-band offers additionally require an approved
`COMPENSATION_EXCEPTION`.

## Business and integrity constraints

1. **Keys and referential integrity:** every entity has an immutable PK;
   FKs reference valid parents; natural-key uniqueness and composite uniqueness
   are specified in the dictionary. Physical deletion is restricted, never
   cascaded through audit/history.
2. **Requisition compensation and approvals:** salary values use
   `NUMERIC(12,2)` and a declared ISO currency and period. An open requisition
   requires both bounds, positive `min_salary <= max_salary`, an approval
   timestamp, a valid active hiring manager, and every required stage in its
   current RequisitionApproval cycle approved. Pending, rejected, or returned
   decisions block opening. Currency conversion is not implicit.
3. **Application integrity:** duplicate candidate/requisition applications
   are rejected. Current stage/status must agree, all transitions must be in
   the matrix, and the stage-history chain must reconcile with current state.
   Required reviews are checked before advancing.
4. **Skills:** skills use Skill and CandidateSkill rows, not comma-separated
   fields. A requirement is unique per requisition/skill; proficiency is
   represented on an explicit five-point scale (`NOVICE`=1, `BEGINNER`=2,
   `INTERMEDIATE`=3, `ADVANCED`=4, `EXPERT`=5). Matching is case-insensitive
   on the canonical skill catalog.
5. **Panel membership and availability:** panel membership must be effective
   for every local calendar date touched by the full interview interval; each
   member must be active. Every active panel
   member must have a single `AVAILABLE` interval covering the entire
   interview. A booking is rejected if any member has an overlapping active
   interview, or the candidate has another overlapping active interview,
   using `existing_start < new_end AND new_start < existing_end`. Touching
   half-open intervals are allowed. Reschedule uses the same checks.
6. **Concurrent scheduling:** validation and insert/update must be one
   transaction with concurrency protection for all assigned interviewers.
   Lock the Interviewer parent rows for all panel members in deterministic ID
   order (and the relevant membership/availability rows), or use equivalent
   transaction-scoped advisory locks, before conflict check and write. Locking
   only existing interview rows is insufficient when a calendar has no booking
   yet. The unique time pair alone is insufficient to prevent concurrent
   overlaps.
7. **Interview intervals:** `start_at < end_at`; duration is a positive whole
   number of minutes equal to the interval. Only `SCHEDULED` and `CONFIRMED`
   interviews reserve time. Cancelled, completed, and no-show interviews
   remain in history but do not block future calendar slots.
8. **Scorecards:** reviewer must be an active panel interviewer for the
   interview; one scorecard per reviewer/revision; scores are integer 1–5;
   mandatory, applicable criteria cannot be missing at submission;
   inapplicable criteria are flagged. Overall score is computed from stored
   ratings and weight snapshots as `sum(weight * rating) / sum(weight)`.
   Recommendation is derived from configurable thresholds (defaults:
   Strong Hire 4.00–5.00; Hire / Further Review 3.00–3.99; Borderline
   2.00–2.99; No Hire below 2.00). No independently randomized outcome.
9. **Separate approval workflows:** RequisitionApproval governs requisition
   opening and has `requisition_id` as its FK; offer Approval governs offer
   progression and has `offer_id` as its FK. Their policies and records are
   independent. Each decision is immutable after it is made, with every stage
   represented by a separate ordered row. Required stages are policy-defined
   and sequential, and no offer approval can satisfy a requisition approval
   or vice versa.
10. **Offers and approvals:** offer must link to an eligible application and
   snapshot the requisition compensation bounds, currency, and period. An
   out-of-band proposal may be retained with a reason and flagged for review,
   including as a deliberate anomaly; it cannot progress to approved, sent, or
   accepted until its approval sequence includes the required approved
   exception. Offer acceptance is blocked until every approval requirement is
   met.
11. **History and audit:** stage and reschedule history is append-only;
    important changes also produce AuditEvent with actor, timestamp, previous
    and new state, reason, and related entity where applicable. Audit payloads
    must not contain credentials, secrets, or ground-truth labels.
12. **Synthetic anomaly handling:** valid baseline data is generated first.
    Deliberate anomaly cases are injected and labeled in a separate anomaly
    registry/ground-truth export; they do not justify weakening normal
    scheduling, review, or compensation rules. Ground truth is excluded from
    operational feature inputs.
13. **Data retention:** operational rows are closed or inactivated rather
    than physically deleted. Database/service retention policy must preserve
    historical records and follow the organization's legal retention rules.

## Index definitions and enforcement boundary

Primary keys and unique constraints create their own indexes. PostgreSQL does
not automatically index every referencing FK column, so the proposed schema
should also add indexes for common joins, filters, and time-window queries:

| Table | Non-unique indexes | Query purpose |
|---|---|---|
| Requisition | `(status, department)`, `(location, status)`, `(hiring_manager_id)`, `(closing_date)` | Open requisition lists, filtering, manager workload, and closing-date review. |
| RequisitionApproval | `(requisition_id, approval_cycle, decision)`, `(approver_id, decided_at)` | Resolve current-cycle gate completion, pending work, and approver workload. |
| Application | `(requisition_id, applied_at)`, `(current_stage, status)`, `(status, updated_at)` | Requisition pipeline, stage dashboards, and active/closed queues. |
| CandidateSkill | `(skill_id, proficiency_level)` | Candidate matching by requested skill and proficiency. |
| SkillRequirement | `(skill_id, requirement_type)` | Role requirements and skill matching. |
| PanelInterviewer | `(interviewer_id, effective_from, effective_to)`, `(panel_id, effective_from, effective_to)` | Resolve active roster at a scheduled time. |
| Availability | `(interviewer_id, available_start, available_end, availability_status)` | Full-interval availability lookup. |
| Interview | `(status, start_at, end_at)`, `(application_id, start_at)`, `(panel_id, start_at)` | Upcoming calendar, conflict checks, and application interview history. |
| Scorecard | `(interview_id, completion_status)`, `(reviewer_id, submitted_at)` | Interview review completion and reviewer workload. |
| ScorecardCriteria | `(criterion_id)` | Criterion-level evaluation analysis. |
| Offer | `(application_id, status)`, `(status, expires_at)` | Application offer history and pending/expiring offer queues. |
| Approval | `(offer_id, decision)`, `(approver_id, decided_at)` | Approval status and approver workload. |
| ApplicationStageHistory | Unique `(application_id, history_sequence)` | Ordered history lookup; unique constraint already supplies the index. |
| InterviewRescheduleHistory | Unique `(interview_id, reschedule_sequence)` | Ordered reschedule lookup; unique constraint already supplies the index. |
| AuditEvent | `(entity_type, entity_id, occurred_at)`, `(related_entity_type, related_entity_id, occurred_at)` | Polymorphic primary and related record audit lookup. |

Use ordinary B-tree indexes unless measured query plans justify another
method. All foreign keys use `ON DELETE RESTRICT`/`NO ACTION`; any additional
FK lookup indexes should be added where not covered by the indexes above.

Row-local conditions (for example salary bounds, date order, allowed state
values, rating range, and positive duration) should use `NOT NULL`, `CHECK`,
and `UNIQUE` constraints where expressible. Cross-table or time-dependent
rules (stage gates, panel membership effectiveness, full availability
coverage, overlapping bookings, approval sequences, and applicability of
criteria) require transactionally consistent service validation. The design
must not imply that a row-level CHECK alone can enforce those rules.

## Design assumptions and decisions for review

1. **PostgreSQL representation:** constrained `VARCHAR` values plus `CHECK`
   constraints are proposed for lifecycles rather than PostgreSQL enum types.
   This keeps future state additions migration-manageable while still
   validating values.
2. **Reviewer identity:** Scorecard reviewer is an Interviewer and must be an
   active member of the interview panel. If HR/other non-interviewer users
   must review scorecards, a shared organization-user entity should replace
   this assumption before expanding reviewer support.
3. **Approver/actor identity:** RequisitionApproval and offer Approval
   approvers, plus general actors, may be outside the interviewer and
   hiring-manager sets. Their stable identity (and name snapshot for offer
   Approval) is stored without a restrictive FK; integration to an
   organization identity directory is outside this schema.
4. **One application per candidate/requisition:** composite uniqueness rejects
   duplicate submissions to the same requisition. Reapplication is allowed
   only through a new requisition unless a separate reapplication workflow is
   approved.
5. **Offer revisions:** every revised offer is a new row with a new version
   and optional predecessor link; previous versions and their approvals remain
   unchanged.
6. **Scorecard revisions:** a revision is per reviewer and interview. Different
   reviewers create independent scorecards; a reviewer correction requires a
   new revision and an explicit predecessor link.
7. **Scorecard recommendation bands:** the thresholds in this document are
   defaults and are configurable; boundary values use two decimal places and
   inclusive lower/upper bounds. Implementation must define rounding before
   comparing.
8. **Availability coverage:** the availability table represents declared
   availability intervals; it is not a recurring-calendar rule engine. Every
   panel member must have full interval coverage before a booking is accepted.
9. **Audit polymorphism:** AuditEvent references are logically checked by the
   audit service and cannot be enforced with a normal FK. If strict database
   enforcement is required in future, use a shared entity registry with
   immutable IDs and a forward migration.
10. **Approval policy:** required requisition approval stages and approver
    roles are external policy configuration; stages are sequentially ordered
    by `approval_sequence`. Each requisition submission starts a new
    `approval_cycle`; decisions from prior cycles are retained but cannot satisfy
    the current cycle. Returned or
    rejected approval records are immutable; a renewed request is a new row
    linked by `supersedes_requisition_approval_id` when applicable.
    Offer approval policy is separately configured per offer version, with
    `approval_stage`, `approval_sequence`, and `approval_type` distinguishing
    standard and compensation-exception steps.
11. **Time zones:** scheduling values are `TIMESTAMPTZ` instants; clients must
    supply an offset or timezone and display in the user's configured zone.
    Duration calculation is based on instants, not wall-clock text.
12. **Schema ownership:** SQLAlchemy metadata and Alembic migrations are the
    change-controlled schema source. `database/schema.sql` is a generated
    reference/export and should not be applied directly to a managed database.

## Implementation notes

- The 21 entity tables, declared foreign keys, unique constraints, row-local
  checks, and listed B-tree indexes are represented in SQLAlchemy metadata and
  the initial Alembic migration.
- Current migration changes create tables and constraints only; they do not
  drop or rewrite existing business data.
- Requisition transition validation and the required-approval-stage gate are
  implemented in `src/services/requisition_service.py`. The caller must pass
  the current configured required stages; an empty policy is rejected.
- Application transitions append `ApplicationStageHistory` and `AuditEvent`;
  terminal stages close the application, and `HIRED` requires an accepted
  offer. Advancing beyond an interview stage requires its configured reviewers
  to submit scorecards. Approval decision services allow one decision from
  `PENDING`.
- Offer transitions are validated in `src/services/offer_service.py`, including
  configured standard approval stages and the compensation-exception gate for
  out-of-band offers.
- Scorecard submission verifies the reviewer is an effective panel member,
  checks the policy-provided required criteria, computes the weighted score,
  and only accepts a new revision that immediately supersedes its submitted
  predecessor.
- Interview scheduling checks timezone-aware positive whole-minute intervals,
  active effective panel memberships, a single covering `AVAILABLE` interval
  for every assigned interviewer, and candidate/interviewer overlap. The
  service locks panel, membership, interviewer, and candidate rows in one
  transaction. Panel membership overlap and time-interval conflicts are not
  encoded as row-level `CHECK` constraints.
- PostgreSQL-specific exclusion constraints are not installed. Overlap checks
  are performed by the transactional scheduling service; callers must commit
  or roll back the surrounding transaction.
- Lifecycle transitions, approval immutability, current-cycle business policy,
  rubric applicability/completeness, ID formats, and append-only history are
  service-level responsibilities in addition to the constraints that can be
  represented in the database.
- `AuditEvent` intentionally has no polymorphic foreign keys. Its JSON payload
  uses PostgreSQL `JSONB`; target existence/type and append-only policy require
  trusted audit-writing code.
- The database was initially empty; the initial revision creates the schema
  without dropping or rewriting existing business data.
