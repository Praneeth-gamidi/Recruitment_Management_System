# Recruitment Business Rules

These rules define the approved lifecycle and workflow behavior. Application
stage history, requisition opening, offer progression and decisions, scorecard
submission/revisions, and interview scheduling have transaction-oriented
service checks. The remaining workflows still require
callers to use the documented policies and are not all implemented as
application endpoints in this phase. The schema and enforcement boundaries
are in [database_design.md](./database_design.md); field constraints are in
[data_dictionary.md](./data_dictionary.md).

## Lifecycle transitions

Any state change not shown here is invalid. Stage/status changes are append-only
in the corresponding history table and also produce an AuditEvent.

| Entity | State / transition | Terminal states |
|---|---|---|
| Requisition | `DRAFT` -> `PENDING_APPROVAL` or `CANCELLED`; `PENDING_APPROVAL` -> `DRAFT` (rejected/returned for revision), `OPEN` (only after all required RequisitionApproval stages in the current cycle are approved), or `CANCELLED`; `OPEN` -> `ON_HOLD`, `FILLED`, `CLOSED`, or `CANCELLED`; `ON_HOLD` -> `OPEN` (only while all currently required requisition approvals remain approved; policy may require a new cycle), `CLOSED`, or `CANCELLED`; `FILLED` -> `CLOSED`. | `CLOSED`, `CANCELLED` |
| Application | `APPLIED` -> `SCREENING` -> `ASSESSMENT` -> `TECHNICAL_INTERVIEW` -> `MANAGERIAL_INTERVIEW` -> `HR_INTERVIEW` -> `OFFER` -> `HIRED`; from any nonterminal stage, `REJECTED` or `WITHDRAWN` is allowed. `ACTIVE` <-> `ON_HOLD` does not change stage; terminal status is `CLOSED`. | `HIRED`, `REJECTED`, `WITHDRAWN` |
| Interview | `SCHEDULED` -> `CONFIRMED`, `COMPLETED`, `CANCELLED`, or `NO_SHOW`; `CONFIRMED` -> `COMPLETED`, `CANCELLED`, or `NO_SHOW`. Reschedule preserves interview state and appends a reschedule history row. | `COMPLETED`, `CANCELLED`, `NO_SHOW` |
| Scorecard | `DRAFT` -> `SUBMITTED` -> `SUPERSEDED`; corrections create a new revision. A submitted scorecard is immutable. | `SUPERSEDED` |
| Offer | `DRAFT` -> `PENDING_APPROVAL`; `PENDING_APPROVAL` -> `APPROVED`, `RETURNED_FOR_REVISION`, `REJECTED`, or `WITHDRAWN`; `RETURNED_FOR_REVISION` -> `WITHDRAWN`; `APPROVED` -> `SENT` or `WITHDRAWN`; `SENT` -> `ACCEPTED`, `DECLINED`, `EXPIRED`, or `WITHDRAWN`. Revision creates a new offer version. | `ACCEPTED`, `DECLINED`, `EXPIRED`, `REJECTED`, `WITHDRAWN` |
| RequisitionApproval | `PENDING` -> one of `APPROVED`, `REJECTED`, or `RETURNED_FOR_REVISION`; decided row is immutable. A re-submission creates a new approval cycle and new approval rows, preserving prior decisions. | `APPROVED`, `REJECTED`, `RETURNED_FOR_REVISION` |
| Approval (offer) | `PENDING` -> one of `APPROVED`, `REJECTED`, or `RETURNED_FOR_REVISION`; decided row is immutable. Offer revision creates a new offer version and new approval rows. | `APPROVED`, `REJECTED`, `RETURNED_FOR_REVISION` |

## Workflow gates

- Requisition cannot transition to `OPEN` unless every approval stage required
  by its configured requisition policy has at least one `APPROVED`
  RequisitionApproval in the current `approval_cycle`; any pending, rejected,
  or returned decision blocks opening. The current cycle is the highest cycle
  for the latest submission. Resubmission begins a new cycle, so old decisions
  do not satisfy new approval requirements.
- Offer Approval is a separate workflow attached only to Offer. Requisition
  decisions cannot satisfy offer approvals, and offer decisions cannot
  satisfy requisition approvals.
- Applications cannot skip a defined stage, and terminal applications cannot
  progress or be scheduled for a new interview.
- Advancing past an interview stage requires the stage's required interview
  reviews and all applicable mandatory criteria to be submitted.
- An application reaches `HIRED` only after a linked offer is accepted and all
  required standard and exception approvals have been recorded.
- A scorecard is not a completed evaluation until submitted. Its overall
  score is calculated from stored ratings and weight snapshots:
  `sum(weight * rating) / sum(weight)`.
- Default recommendation thresholds are Strong Hire 4.00–5.00, Hire / Further
  Review 3.00–3.99, Borderline 2.00–2.99, and No Hire below 2.00.
  Thresholds are configurable and score rounding must be defined before
  implementation.

## Interview scheduling

- A proposed interval must have `start_at < end_at` and a positive whole-minute
  duration.
- Every active panel member must be effective for every local calendar date
  touched by the interview interval and have an `AVAILABLE` interval covering
  the entire interview.
- No interviewer may have another `SCHEDULED` or `CONFIRMED` interview
  overlapping the proposed interval, and the same candidate cannot be booked
  in overlapping active interviews. Overlap is
  `existing_start < new_end AND new_start < existing_end`; touching endpoints
  are permitted.
- The availability/conflict check and booking/rescheduling write are one
  transaction with locks or an equivalent serialization strategy, preventing
  concurrent double bookings.
- A reschedule appends the previous interval, new interval, actor, time, and
  reason; historical values are never overwritten.

## Compensation and approvals

- An `OPEN` requisition needs an approved positive compensation band with
  `min_salary <= max_salary`, an ISO currency, and one compensation period.
- An offer snapshots the requisition's band, currency, and period. Currency
  conversion is never implicit.
- An in-band offer requires the standard configured approvals. An out-of-band
  proposal may be retained with a reason and flagged for review, including as
  a deliberate anomaly; it requires an approved `COMPENSATION_EXCEPTION`
  before becoming approved, being sent, or being accepted.
- An offer cannot be accepted before being sent, before expiry, or before all
  required approvals. Changed offers are new versions; old proposals and
  approval records are retained.
- RequisitionApproval decisions are immutable; each cycle and configured
  approval stage is independently auditable. Offer Approval decisions are
  immutable and belong only to an offer; returned or reconsidered offers use
  a new offer version and new ordered Approval records.

## Data integrity and audit

- All FK-backed entities require existing parents. Operational/history
  deletion is restricted; close or deactivate records instead of cascading
  deletion.
- RequisitionApproval has a required FK to Requisition; offer Approval retains
  its required FK to Offer. The two approval workflows remain independent.
- Requisition skills and candidate skills use normalized Skill references;
  no comma-separated skill lists are used.
- Candidate/requisition pairs are unique within Application.
- Interview scorecards are unique by interview, reviewer, and revision number.
  A reviewer correction uses an explicit revision chain.
- AuditEvent records the entity type/ID, including either approval entity,
  optional related entity type/ID,
  actor, event time, previous/new state, and reason where required. Its
  polymorphic references are checked by the audit service because they are
  not physical foreign keys.
- Baseline records satisfy normal rules. Deliberate anomaly cases are injected
  separately and identified in a separate ground-truth/anomaly registry;
  ground-truth labels are never copied into operational input features.

## Synthetic anomaly fixtures

The starter generator keeps the clean 21-table baseline unchanged and creates
five isolated anomaly inputs. Expected labels and handling guidance are stored
separately from those inputs:

- `MISSING_REQUIRED_REVIEW`: one panel member has no submitted scorecard.
- `DOUBLE_BOOKING`: two interviews overlap for the same panel.
- `OFFER_OUTSIDE_BAND`: proposed compensation exceeds the offer's band snapshot
  without an exception reason.
- `WITHDRAWN_CANDIDATE_SCHEDULED`: a scheduled interview is linked to a
  withdrawn application.
- `IRRELEVANT_EVALUATION_CRITERIA`: a scorecard uses a criterion whose
  department/job-family scope does not match the requisition.

These are test/validation fixtures, not rows to load into the operational
database. The generator is deterministic with seed `20261022`; starter/full
record counts are configured in `src/generators/master_data_generator.py`.
