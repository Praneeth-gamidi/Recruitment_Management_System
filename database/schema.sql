-- Generated from SQLAlchemy metadata by scripts/export_schema.py.

-- Apply only through the reviewed Alembic migration workflow.

CREATE TABLE audit_events (
	audit_event_id VARCHAR(80) NOT NULL, 
	event_type VARCHAR(40) NOT NULL, 
	entity_type VARCHAR(40) NOT NULL, 
	entity_id VARCHAR(160) NOT NULL, 
	related_entity_type VARCHAR(40), 
	related_entity_id VARCHAR(160), 
	previous_state TEXT, 
	new_state TEXT, 
	actor_type VARCHAR(24) DEFAULT 'USER' NOT NULL, 
	actor_id VARCHAR(80), 
	actor_name_snapshot VARCHAR(200), 
	reason TEXT, 
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	payload JSONB, 
	CONSTRAINT pk_audit_events PRIMARY KEY (audit_event_id), 
	CONSTRAINT ck_audit_events_related_entity_pair CHECK ((related_entity_type IS NULL AND related_entity_id IS NULL) OR (related_entity_type IS NOT NULL AND related_entity_id IS NOT NULL)), 
	CONSTRAINT ck_audit_events_actor_type CHECK (actor_type IN ('USER', 'SYSTEM', 'SERVICE')), 
	CONSTRAINT ck_audit_events_user_actor_identity CHECK (actor_type <> 'USER' OR (actor_id IS NOT NULL AND actor_name_snapshot IS NOT NULL))
);

CREATE INDEX ix_audit_events_related_time ON audit_events (related_entity_type, related_entity_id, occurred_at);

CREATE INDEX ix_audit_events_entity_time ON audit_events (entity_type, entity_id, occurred_at);

CREATE TABLE candidates (
	candidate_id VARCHAR(80) NOT NULL, 
	first_name VARCHAR(100) NOT NULL, 
	last_name VARCHAR(100) NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	phone VARCHAR(32), 
	location VARCHAR(160), 
	education_level VARCHAR(24), 
	education_summary VARCHAR(500), 
	total_experience_months INTEGER DEFAULT '0' NOT NULL, 
	profile_created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_candidates PRIMARY KEY (candidate_id), 
	CONSTRAINT ck_candidates_education_level CHECK (education_level IS NULL OR education_level IN ('SECONDARY', 'ASSOCIATE', 'BACHELOR', 'MASTER', 'DOCTORATE', 'OTHER')), 
	CONSTRAINT ck_candidates_email_normalized CHECK (email = lower(email)), 
	CONSTRAINT ck_candidates_experience_nonnegative CHECK (total_experience_months >= 0), 
	CONSTRAINT uq_candidates_email UNIQUE (email)
);

CREATE TABLE evaluation_criteria (
	criterion_id VARCHAR(80) NOT NULL, 
	criterion_code VARCHAR(60) NOT NULL, 
	criterion_name VARCHAR(120) NOT NULL, 
	description TEXT NOT NULL, 
	maximum_rating SMALLINT DEFAULT '5' NOT NULL, 
	default_weight NUMERIC(6, 3) DEFAULT '1.000' NOT NULL, 
	mandatory BOOLEAN DEFAULT 'true' NOT NULL, 
	applicability_scope VARCHAR(16) DEFAULT 'ALL' NOT NULL, 
	applicability_value VARCHAR(120), 
	active_status VARCHAR(12) DEFAULT 'ACTIVE' NOT NULL, 
	effective_from DATE NOT NULL, 
	effective_to DATE, 
	CONSTRAINT pk_evaluation_criteria PRIMARY KEY (criterion_id), 
	CONSTRAINT ck_evaluation_criteria_maximum_rating CHECK (maximum_rating = 5), 
	CONSTRAINT ck_evaluation_criteria_weight_positive CHECK (default_weight > 0), 
	CONSTRAINT ck_evaluation_criteria_criterion_code_normalized CHECK (criterion_code = upper(criterion_code)), 
	CONSTRAINT ck_evaluation_criteria_applicability_scope CHECK (applicability_scope IN ('ALL', 'DEPARTMENT', 'JOB_FAMILY', 'SKILL')), 
	CONSTRAINT ck_evaluation_criteria_applicability_value CHECK ((applicability_scope = 'ALL' AND applicability_value IS NULL) OR (applicability_scope <> 'ALL' AND applicability_value IS NOT NULL)), 
	CONSTRAINT ck_evaluation_criteria_active_status CHECK (active_status IN ('ACTIVE', 'INACTIVE')), 
	CONSTRAINT ck_evaluation_criteria_effective_dates CHECK (effective_to IS NULL OR effective_from <= effective_to), 
	CONSTRAINT uq_evaluation_criteria_criterion_code UNIQUE (criterion_code)
);

CREATE TABLE hiring_managers (
	hiring_manager_id VARCHAR(80) NOT NULL, 
	employee_code VARCHAR(40) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	department VARCHAR(100) NOT NULL, 
	phone VARCHAR(32), 
	active_status VARCHAR(16) DEFAULT 'ACTIVE' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_hiring_managers PRIMARY KEY (hiring_manager_id), 
	CONSTRAINT ck_hiring_managers_active_status CHECK (active_status IN ('ACTIVE', 'INACTIVE')), 
	CONSTRAINT ck_hiring_managers_employee_code_normalized CHECK (employee_code = lower(employee_code)), 
	CONSTRAINT ck_hiring_managers_email_normalized CHECK (email = lower(email)), 
	CONSTRAINT uq_hiring_managers_employee_code UNIQUE (employee_code), 
	CONSTRAINT uq_hiring_managers_email UNIQUE (email)
);

CREATE TABLE interview_panels (
	panel_id VARCHAR(80) NOT NULL, 
	panel_name VARCHAR(120) NOT NULL, 
	panel_type VARCHAR(24) DEFAULT 'GENERAL' NOT NULL, 
	active_status VARCHAR(12) DEFAULT 'ACTIVE' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_interview_panels PRIMARY KEY (panel_id), 
	CONSTRAINT ck_interview_panels_panel_type CHECK (panel_type IN ('TECHNICAL', 'MANAGERIAL', 'HR', 'GENERAL')), 
	CONSTRAINT ck_interview_panels_active_status CHECK (active_status IN ('ACTIVE', 'INACTIVE'))
);

CREATE TABLE interviewers (
	interviewer_id VARCHAR(80) NOT NULL, 
	employee_code VARCHAR(40) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	department VARCHAR(100) NOT NULL, 
	designation VARCHAR(100) NOT NULL, 
	active_status VARCHAR(12) DEFAULT 'ACTIVE' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_interviewers PRIMARY KEY (interviewer_id), 
	CONSTRAINT ck_interviewers_active_status CHECK (active_status IN ('ACTIVE', 'INACTIVE')), 
	CONSTRAINT ck_interviewers_employee_code_normalized CHECK (employee_code = lower(employee_code)), 
	CONSTRAINT ck_interviewers_email_normalized CHECK (email = lower(email)), 
	CONSTRAINT uq_interviewers_employee_code UNIQUE (employee_code), 
	CONSTRAINT uq_interviewers_email UNIQUE (email)
);

CREATE TABLE skills (
	skill_id VARCHAR(80) NOT NULL, 
	skill_name VARCHAR(100) NOT NULL, 
	skill_category VARCHAR(40), 
	active_status VARCHAR(12) DEFAULT 'ACTIVE' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_skills PRIMARY KEY (skill_id), 
	CONSTRAINT ck_skills_active_status CHECK (active_status IN ('ACTIVE', 'INACTIVE')), 
	CONSTRAINT ck_skills_skill_name_normalized CHECK (skill_name = lower(skill_name)), 
	CONSTRAINT uq_skills_skill_name UNIQUE (skill_name)
);

CREATE TABLE availability (
	availability_id VARCHAR(80) NOT NULL, 
	interviewer_id VARCHAR(80) NOT NULL, 
	available_start TIMESTAMP WITH TIME ZONE NOT NULL, 
	available_end TIMESTAMP WITH TIME ZONE NOT NULL, 
	availability_status VARCHAR(16) DEFAULT 'AVAILABLE' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_availability PRIMARY KEY (availability_id), 
	CONSTRAINT uq_availability_interviewer_id UNIQUE (interviewer_id, available_start, available_end), 
	CONSTRAINT ck_availability_interval CHECK (available_start < available_end), 
	CONSTRAINT ck_availability_availability_status CHECK (availability_status IN ('AVAILABLE', 'UNAVAILABLE', 'BLOCKED')), 
	CONSTRAINT fk_availability_interviewer_id_interviewers FOREIGN KEY(interviewer_id) REFERENCES interviewers (interviewer_id) ON DELETE RESTRICT
);

CREATE INDEX ix_availability_interviewer_window ON availability (interviewer_id, available_start, available_end, availability_status);

CREATE TABLE candidate_skills (
	candidate_skill_id VARCHAR(80) NOT NULL, 
	candidate_id VARCHAR(80) NOT NULL, 
	skill_id VARCHAR(80) NOT NULL, 
	proficiency_level VARCHAR(16) NOT NULL, 
	experience_months INTEGER DEFAULT '0' NOT NULL, 
	last_used_on DATE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_candidate_skills PRIMARY KEY (candidate_skill_id), 
	CONSTRAINT uq_candidate_skills_candidate_id UNIQUE (candidate_id, skill_id), 
	CONSTRAINT ck_candidate_skills_proficiency_level CHECK (proficiency_level IN ('NOVICE', 'BEGINNER', 'INTERMEDIATE', 'ADVANCED', 'EXPERT')), 
	CONSTRAINT ck_candidate_skills_experience_nonnegative CHECK (experience_months >= 0), 
	CONSTRAINT fk_candidate_skills_candidate_id_candidates FOREIGN KEY(candidate_id) REFERENCES candidates (candidate_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_candidate_skills_skill_id_skills FOREIGN KEY(skill_id) REFERENCES skills (skill_id) ON DELETE RESTRICT
);

CREATE INDEX ix_candidate_skills_skill_proficiency ON candidate_skills (skill_id, proficiency_level);

CREATE TABLE panel_interviewers (
	panel_interviewer_id VARCHAR(80) NOT NULL, 
	panel_id VARCHAR(80) NOT NULL, 
	interviewer_id VARCHAR(80) NOT NULL, 
	role_in_panel VARCHAR(40) DEFAULT 'INTERVIEWER' NOT NULL, 
	effective_from DATE NOT NULL, 
	effective_to DATE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_panel_interviewers PRIMARY KEY (panel_interviewer_id), 
	CONSTRAINT uq_panel_interviewers_panel_id UNIQUE (panel_id, interviewer_id, effective_from), 
	CONSTRAINT ck_panel_interviewers_role_in_panel CHECK (role_in_panel IN ('LEAD', 'INTERVIEWER', 'OBSERVER', 'SPECIALIST')), 
	CONSTRAINT ck_panel_interviewers_effective_dates CHECK (effective_to IS NULL OR effective_from <= effective_to), 
	CONSTRAINT fk_panel_interviewers_panel_id_interview_panels FOREIGN KEY(panel_id) REFERENCES interview_panels (panel_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_panel_interviewers_interviewer_id_interviewers FOREIGN KEY(interviewer_id) REFERENCES interviewers (interviewer_id) ON DELETE RESTRICT
);

CREATE INDEX ix_panel_interviewers_interviewer_effective ON panel_interviewers (interviewer_id, effective_from, effective_to);

CREATE INDEX ix_panel_interviewers_panel_effective ON panel_interviewers (panel_id, effective_from, effective_to);

CREATE TABLE requisitions (
	requisition_id VARCHAR(80) NOT NULL, 
	hiring_manager_id VARCHAR(80) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	description TEXT, 
	department VARCHAR(100) NOT NULL, 
	job_family VARCHAR(100) NOT NULL, 
	location VARCHAR(160) NOT NULL, 
	employment_type VARCHAR(20) NOT NULL, 
	work_mode VARCHAR(16) NOT NULL, 
	headcount SMALLINT NOT NULL, 
	status VARCHAR(24) DEFAULT 'DRAFT' NOT NULL, 
	min_salary NUMERIC(12, 2), 
	max_salary NUMERIC(12, 2), 
	currency_code CHAR(3), 
	compensation_period VARCHAR(12), 
	opening_date DATE NOT NULL, 
	closing_date DATE, 
	approved_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_requisitions PRIMARY KEY (requisition_id), 
	CONSTRAINT ck_requisitions_employment_type CHECK (employment_type IN ('FULL_TIME', 'PART_TIME', 'CONTRACT', 'TEMPORARY', 'INTERN')), 
	CONSTRAINT ck_requisitions_work_mode CHECK (work_mode IN ('ONSITE', 'HYBRID', 'REMOTE')), 
	CONSTRAINT ck_requisitions_status CHECK (status IN ('DRAFT', 'PENDING_APPROVAL', 'OPEN', 'ON_HOLD', 'FILLED', 'CLOSED', 'CANCELLED')), 
	CONSTRAINT ck_requisitions_headcount_positive CHECK (headcount > 0), 
	CONSTRAINT ck_requisitions_min_salary_nonnegative CHECK (min_salary IS NULL OR min_salary >= 0), 
	CONSTRAINT ck_requisitions_max_salary_positive CHECK (max_salary IS NULL OR max_salary > 0), 
	CONSTRAINT ck_requisitions_salary_range CHECK (min_salary IS NULL OR max_salary IS NULL OR min_salary <= max_salary), 
	CONSTRAINT ck_requisitions_compensation_period CHECK (compensation_period IS NULL OR compensation_period IN ('YEAR', 'MONTH', 'HOUR')), 
	CONSTRAINT ck_requisitions_date_range CHECK (closing_date IS NULL OR opening_date <= closing_date), 
	CONSTRAINT fk_requisitions_hiring_manager_id_hiring_managers FOREIGN KEY(hiring_manager_id) REFERENCES hiring_managers (hiring_manager_id) ON DELETE RESTRICT
);

CREATE INDEX ix_requisitions_hiring_manager_id ON requisitions (hiring_manager_id);

CREATE INDEX ix_requisitions_status_department ON requisitions (status, department);

CREATE INDEX ix_requisitions_location_status ON requisitions (location, status);

CREATE INDEX ix_requisitions_closing_date ON requisitions (closing_date);

CREATE TABLE applications (
	application_id VARCHAR(160) NOT NULL, 
	candidate_id VARCHAR(80) NOT NULL, 
	requisition_id VARCHAR(80) NOT NULL, 
	applied_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	current_stage VARCHAR(32) DEFAULT 'APPLIED' NOT NULL, 
	status VARCHAR(12) DEFAULT 'ACTIVE' NOT NULL, 
	source_channel VARCHAR(32) DEFAULT 'CAREER_SITE' NOT NULL, 
	source_detail VARCHAR(200), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_applications PRIMARY KEY (application_id), 
	CONSTRAINT uq_applications_candidate_id UNIQUE (candidate_id, requisition_id), 
	CONSTRAINT ck_applications_current_stage CHECK (current_stage IN ('APPLIED', 'SCREENING', 'ASSESSMENT', 'TECHNICAL_INTERVIEW', 'MANAGERIAL_INTERVIEW', 'HR_INTERVIEW', 'OFFER', 'HIRED', 'REJECTED', 'WITHDRAWN')), 
	CONSTRAINT ck_applications_status CHECK (status IN ('ACTIVE', 'ON_HOLD', 'CLOSED')), 
	CONSTRAINT ck_applications_stage_status_consistency CHECK ((current_stage IN ('HIRED', 'REJECTED', 'WITHDRAWN') AND status = 'CLOSED') OR (current_stage NOT IN ('HIRED', 'REJECTED', 'WITHDRAWN') AND status IN ('ACTIVE', 'ON_HOLD'))), 
	CONSTRAINT ck_applications_source_channel CHECK (source_channel IN ('CAREER_SITE', 'REFERRAL', 'JOB_BOARD', 'AGENCY', 'DIRECT', 'OTHER')), 
	CONSTRAINT fk_applications_candidate_id_candidates FOREIGN KEY(candidate_id) REFERENCES candidates (candidate_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_applications_requisition_id_requisitions FOREIGN KEY(requisition_id) REFERENCES requisitions (requisition_id) ON DELETE RESTRICT
);

CREATE INDEX ix_applications_status_updated ON applications (status, updated_at);

CREATE INDEX ix_applications_stage_status ON applications (current_stage, status);

CREATE INDEX ix_applications_requisition_applied ON applications (requisition_id, applied_at);

CREATE TABLE requisition_approvals (
	requisition_approval_id VARCHAR(80) NOT NULL, 
	requisition_id VARCHAR(80) NOT NULL, 
	approver_id VARCHAR(80) NOT NULL, 
	approval_cycle INTEGER DEFAULT '1' NOT NULL, 
	approval_sequence SMALLINT NOT NULL, 
	approval_stage VARCHAR(80) NOT NULL, 
	decision VARCHAR(24) DEFAULT 'PENDING' NOT NULL, 
	comments TEXT, 
	requested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	supersedes_requisition_approval_id VARCHAR(80), 
	CONSTRAINT pk_requisition_approvals PRIMARY KEY (requisition_approval_id), 
	CONSTRAINT uq_requisition_approvals_requisition_id UNIQUE (requisition_id, approval_cycle, approval_sequence), 
	CONSTRAINT ck_requisition_approvals_approval_cycle_positive CHECK (approval_cycle >= 1), 
	CONSTRAINT ck_requisition_approvals_approval_sequence_positive CHECK (approval_sequence >= 1), 
	CONSTRAINT ck_requisition_approvals_decision CHECK (decision IN ('PENDING', 'APPROVED', 'REJECTED', 'RETURNED_FOR_REVISION')), 
	CONSTRAINT ck_requisition_approvals_decision_timestamp CHECK ((decision = 'PENDING' AND decided_at IS NULL) OR (decision <> 'PENDING' AND decided_at IS NOT NULL)), 
	CONSTRAINT ck_requisition_approvals_decision_comment_required CHECK (decision NOT IN ('REJECTED', 'RETURNED_FOR_REVISION') OR (comments IS NOT NULL AND length(trim(comments)) > 0)), 
	CONSTRAINT fk_requisition_approvals_requisition_id_requisitions FOREIGN KEY(requisition_id) REFERENCES requisitions (requisition_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_requisition_approvals_supersedes_requisition_approva_3416 FOREIGN KEY(supersedes_requisition_approval_id) REFERENCES requisition_approvals (requisition_approval_id) ON DELETE RESTRICT
);

CREATE INDEX ix_requisition_approvals_approver_decided ON requisition_approvals (approver_id, decided_at);

CREATE INDEX ix_requisition_approvals_cycle_decision ON requisition_approvals (requisition_id, approval_cycle, decision);

CREATE INDEX ix_requisition_approvals_supersedes_id ON requisition_approvals (supersedes_requisition_approval_id);

CREATE TABLE skill_requirements (
	skill_requirement_id VARCHAR(80) NOT NULL, 
	requisition_id VARCHAR(80) NOT NULL, 
	skill_id VARCHAR(80) NOT NULL, 
	requirement_type VARCHAR(12) DEFAULT 'MANDATORY' NOT NULL, 
	minimum_proficiency SMALLINT DEFAULT '1' NOT NULL, 
	minimum_experience_months INTEGER DEFAULT '0' NOT NULL, 
	weight NUMERIC(6, 3) DEFAULT '1.000' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_skill_requirements PRIMARY KEY (skill_requirement_id), 
	CONSTRAINT uq_skill_requirements_requisition_id UNIQUE (requisition_id, skill_id), 
	CONSTRAINT ck_skill_requirements_requirement_type CHECK (requirement_type IN ('MANDATORY', 'PREFERRED')), 
	CONSTRAINT ck_skill_requirements_minimum_proficiency CHECK (minimum_proficiency BETWEEN 1 AND 5), 
	CONSTRAINT ck_skill_requirements_minimum_experience_nonnegative CHECK (minimum_experience_months >= 0), 
	CONSTRAINT ck_skill_requirements_weight_positive CHECK (weight > 0), 
	CONSTRAINT fk_skill_requirements_requisition_id_requisitions FOREIGN KEY(requisition_id) REFERENCES requisitions (requisition_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_skill_requirements_skill_id_skills FOREIGN KEY(skill_id) REFERENCES skills (skill_id) ON DELETE RESTRICT
);

CREATE INDEX ix_skill_requirements_skill_type ON skill_requirements (skill_id, requirement_type);

CREATE TABLE application_stage_history (
	stage_history_id VARCHAR(80) NOT NULL, 
	application_id VARCHAR(160) NOT NULL, 
	history_sequence INTEGER NOT NULL, 
	previous_stage VARCHAR(32), 
	new_stage VARCHAR(32) NOT NULL, 
	previous_status VARCHAR(12), 
	new_status VARCHAR(12) NOT NULL, 
	actor_id VARCHAR(80) NOT NULL, 
	actor_name_snapshot VARCHAR(200) NOT NULL, 
	reason TEXT NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_application_stage_history PRIMARY KEY (stage_history_id), 
	CONSTRAINT uq_application_stage_history_application_id UNIQUE (application_id, history_sequence), 
	CONSTRAINT ck_application_stage_history_history_sequence_positive CHECK (history_sequence >= 1), 
	CONSTRAINT ck_application_stage_history_previous_stage CHECK (previous_stage IS NULL OR previous_stage IN ('APPLIED', 'SCREENING', 'ASSESSMENT', 'TECHNICAL_INTERVIEW', 'MANAGERIAL_INTERVIEW', 'HR_INTERVIEW', 'OFFER', 'HIRED', 'REJECTED', 'WITHDRAWN')), 
	CONSTRAINT ck_application_stage_history_new_stage CHECK (new_stage IN ('APPLIED', 'SCREENING', 'ASSESSMENT', 'TECHNICAL_INTERVIEW', 'MANAGERIAL_INTERVIEW', 'HR_INTERVIEW', 'OFFER', 'HIRED', 'REJECTED', 'WITHDRAWN')), 
	CONSTRAINT ck_application_stage_history_previous_status CHECK (previous_status IS NULL OR previous_status IN ('ACTIVE', 'ON_HOLD', 'CLOSED')), 
	CONSTRAINT ck_application_stage_history_new_status CHECK (new_status IN ('ACTIVE', 'ON_HOLD', 'CLOSED')), 
	CONSTRAINT ck_application_stage_history_reason_nonempty CHECK (length(trim(reason)) > 0), 
	CONSTRAINT fk_application_stage_history_application_id_applications FOREIGN KEY(application_id) REFERENCES applications (application_id) ON DELETE RESTRICT
);

CREATE TABLE interviews (
	interview_id VARCHAR(80) NOT NULL, 
	application_id VARCHAR(160) NOT NULL, 
	panel_id VARCHAR(80) NOT NULL, 
	interview_round SMALLINT NOT NULL, 
	interview_type VARCHAR(24) NOT NULL, 
	start_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	end_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	duration_minutes SMALLINT NOT NULL, 
	status VARCHAR(16) DEFAULT 'SCHEDULED' NOT NULL, 
	location VARCHAR(200), 
	cancellation_reason TEXT, 
	scheduled_by VARCHAR(80), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_interviews PRIMARY KEY (interview_id), 
	CONSTRAINT ck_interviews_round_positive CHECK (interview_round >= 1), 
	CONSTRAINT ck_interviews_interview_type CHECK (interview_type IN ('SCREENING', 'ASSESSMENT', 'TECHNICAL', 'MANAGERIAL', 'HR', 'OTHER')), 
	CONSTRAINT ck_interviews_interval CHECK (start_at < end_at), 
	CONSTRAINT ck_interviews_duration_positive CHECK (duration_minutes > 0), 
	CONSTRAINT ck_interviews_status CHECK (status IN ('SCHEDULED', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'NO_SHOW')), 
	CONSTRAINT ck_interviews_cancellation_reason_required CHECK (status <> 'CANCELLED' OR (cancellation_reason IS NOT NULL AND length(trim(cancellation_reason)) > 0)), 
	CONSTRAINT fk_interviews_application_id_applications FOREIGN KEY(application_id) REFERENCES applications (application_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_interviews_panel_id_interview_panels FOREIGN KEY(panel_id) REFERENCES interview_panels (panel_id) ON DELETE RESTRICT
);

CREATE INDEX ix_interviews_status_window ON interviews (status, start_at, end_at);

CREATE INDEX ix_interviews_panel_start ON interviews (panel_id, start_at);

CREATE INDEX ix_interviews_application_start ON interviews (application_id, start_at);

CREATE TABLE offers (
	offer_id VARCHAR(80) NOT NULL, 
	application_id VARCHAR(160) NOT NULL, 
	supersedes_offer_id VARCHAR(80), 
	offer_version INTEGER DEFAULT '1' NOT NULL, 
	proposed_salary NUMERIC(12, 2) NOT NULL, 
	band_min_snapshot NUMERIC(12, 2) NOT NULL, 
	band_max_snapshot NUMERIC(12, 2) NOT NULL, 
	currency_code CHAR(3) NOT NULL, 
	compensation_period VARCHAR(12) NOT NULL, 
	status VARCHAR(24) DEFAULT 'DRAFT' NOT NULL, 
	exception_reason TEXT, 
	offer_date DATE, 
	joining_date DATE, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	sent_at TIMESTAMP WITH TIME ZONE, 
	accepted_at TIMESTAMP WITH TIME ZONE, 
	declined_at TIMESTAMP WITH TIME ZONE, 
	created_by VARCHAR(80) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_offers PRIMARY KEY (offer_id), 
	CONSTRAINT uq_offers_application_id UNIQUE (application_id, offer_version), 
	CONSTRAINT ck_offers_version_positive CHECK (offer_version >= 1), 
	CONSTRAINT ck_offers_salary_positive CHECK (proposed_salary > 0), 
	CONSTRAINT ck_offers_band_range CHECK (band_min_snapshot > 0 AND band_min_snapshot <= band_max_snapshot), 
	CONSTRAINT ck_offers_compensation_period CHECK (compensation_period IN ('YEAR', 'MONTH', 'HOUR')), 
	CONSTRAINT ck_offers_status CHECK (status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'SENT', 'ACCEPTED', 'DECLINED', 'RETURNED_FOR_REVISION', 'REJECTED', 'EXPIRED', 'WITHDRAWN')), 
	CONSTRAINT ck_offers_exception_reason CHECK (proposed_salary BETWEEN band_min_snapshot AND band_max_snapshot OR (exception_reason IS NOT NULL AND length(trim(exception_reason)) > 0)), 
	CONSTRAINT ck_offers_expiry CHECK (expires_at IS NULL OR sent_at IS NULL OR expires_at > sent_at), 
	CONSTRAINT ck_offers_sent_timestamp CHECK ((status NOT IN ('SENT', 'ACCEPTED', 'DECLINED', 'EXPIRED') OR sent_at IS NOT NULL)), 
	CONSTRAINT ck_offers_accepted_timestamp CHECK ((status = 'ACCEPTED' AND accepted_at IS NOT NULL AND accepted_at >= sent_at) OR (status <> 'ACCEPTED' AND accepted_at IS NULL)), 
	CONSTRAINT ck_offers_declined_timestamp CHECK ((status = 'DECLINED' AND declined_at IS NOT NULL AND declined_at >= sent_at) OR (status <> 'DECLINED' AND declined_at IS NULL)), 
	CONSTRAINT fk_offers_application_id_applications FOREIGN KEY(application_id) REFERENCES applications (application_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_offers_supersedes_offer_id_offers FOREIGN KEY(supersedes_offer_id) REFERENCES offers (offer_id) ON DELETE RESTRICT
);

CREATE INDEX ix_offers_application_status ON offers (application_id, status);

CREATE INDEX ix_offers_status_expiry ON offers (status, expires_at);

CREATE INDEX ix_offers_supersedes_offer_id ON offers (supersedes_offer_id);

CREATE TABLE approvals (
	approval_id VARCHAR(80) NOT NULL, 
	offer_id VARCHAR(80) NOT NULL, 
	approval_sequence SMALLINT NOT NULL, 
	approval_stage VARCHAR(80) NOT NULL, 
	approval_type VARCHAR(28) DEFAULT 'STANDARD' NOT NULL, 
	approver_id VARCHAR(80) NOT NULL, 
	approver_name_snapshot VARCHAR(200) NOT NULL, 
	approver_role VARCHAR(80) NOT NULL, 
	decision VARCHAR(24) DEFAULT 'PENDING' NOT NULL, 
	comments TEXT, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_approvals PRIMARY KEY (approval_id), 
	CONSTRAINT uq_approvals_offer_id UNIQUE (offer_id, approval_sequence), 
	CONSTRAINT ck_approvals_approval_sequence_positive CHECK (approval_sequence >= 1), 
	CONSTRAINT ck_approvals_approval_type CHECK (approval_type IN ('STANDARD', 'COMPENSATION_EXCEPTION')), 
	CONSTRAINT ck_approvals_decision CHECK (decision IN ('PENDING', 'APPROVED', 'REJECTED', 'RETURNED_FOR_REVISION')), 
	CONSTRAINT ck_approvals_decision_timestamp CHECK ((decision = 'PENDING' AND decided_at IS NULL) OR (decision <> 'PENDING' AND decided_at IS NOT NULL)), 
	CONSTRAINT ck_approvals_decision_comment_required CHECK (decision NOT IN ('REJECTED', 'RETURNED_FOR_REVISION') OR (comments IS NOT NULL AND length(trim(comments)) > 0)), 
	CONSTRAINT fk_approvals_offer_id_offers FOREIGN KEY(offer_id) REFERENCES offers (offer_id) ON DELETE RESTRICT
);

CREATE INDEX ix_approvals_offer_decision ON approvals (offer_id, decision);

CREATE INDEX ix_approvals_approver_decided ON approvals (approver_id, decided_at);

CREATE TABLE interview_reschedule_history (
	reschedule_history_id VARCHAR(80) NOT NULL, 
	interview_id VARCHAR(80) NOT NULL, 
	reschedule_sequence INTEGER NOT NULL, 
	previous_start_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	previous_end_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	new_start_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	new_end_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	actor_id VARCHAR(80) NOT NULL, 
	actor_name_snapshot VARCHAR(200) NOT NULL, 
	reason TEXT NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_interview_reschedule_history PRIMARY KEY (reschedule_history_id), 
	CONSTRAINT uq_interview_reschedule_history_interview_id UNIQUE (interview_id, reschedule_sequence), 
	CONSTRAINT ck_interview_reschedule_history_reschedule_sequence_positive CHECK (reschedule_sequence >= 1), 
	CONSTRAINT ck_interview_reschedule_history_previous_interval CHECK (previous_start_at < previous_end_at), 
	CONSTRAINT ck_interview_reschedule_history_new_interval CHECK (new_start_at < new_end_at), 
	CONSTRAINT ck_interview_reschedule_history_reason_nonempty CHECK (length(trim(reason)) > 0), 
	CONSTRAINT fk_interview_reschedule_history_interview_id_interviews FOREIGN KEY(interview_id) REFERENCES interviews (interview_id) ON DELETE RESTRICT
);

CREATE TABLE scorecards (
	scorecard_id VARCHAR(120) NOT NULL, 
	interview_id VARCHAR(80) NOT NULL, 
	reviewer_id VARCHAR(80) NOT NULL, 
	supersedes_scorecard_id VARCHAR(120), 
	revision_no INTEGER DEFAULT '1' NOT NULL, 
	recommendation VARCHAR(24), 
	overall_score NUMERIC(5, 3), 
	completion_status VARCHAR(12) DEFAULT 'DRAFT' NOT NULL, 
	submitted_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_scorecards PRIMARY KEY (scorecard_id), 
	CONSTRAINT uq_scorecards_interview_id UNIQUE (interview_id, reviewer_id, revision_no), 
	CONSTRAINT ck_scorecards_revision_positive CHECK (revision_no >= 1), 
	CONSTRAINT ck_scorecards_recommendation CHECK (recommendation IS NULL OR recommendation IN ('STRONG_HIRE', 'HIRE_FURTHER_REVIEW', 'BORDERLINE', 'NO_HIRE')), 
	CONSTRAINT ck_scorecards_overall_score CHECK (overall_score IS NULL OR overall_score BETWEEN 1 AND 5), 
	CONSTRAINT ck_scorecards_completion_status CHECK (completion_status IN ('DRAFT', 'SUBMITTED', 'SUPERSEDED')), 
	CONSTRAINT ck_scorecards_submitted_timestamp CHECK ((completion_status = 'DRAFT' AND submitted_at IS NULL) OR (completion_status IN ('SUBMITTED', 'SUPERSEDED') AND submitted_at IS NOT NULL)), 
	CONSTRAINT fk_scorecards_interview_id_interviews FOREIGN KEY(interview_id) REFERENCES interviews (interview_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_scorecards_reviewer_id_interviewers FOREIGN KEY(reviewer_id) REFERENCES interviewers (interviewer_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_scorecards_supersedes_scorecard_id_scorecards FOREIGN KEY(supersedes_scorecard_id) REFERENCES scorecards (scorecard_id) ON DELETE RESTRICT
);

CREATE INDEX ix_scorecards_interview_status ON scorecards (interview_id, completion_status);

CREATE INDEX ix_scorecards_reviewer_submitted ON scorecards (reviewer_id, submitted_at);

CREATE INDEX ix_scorecards_supersedes_id ON scorecards (supersedes_scorecard_id);

CREATE TABLE scorecard_criteria (
	scorecard_criteria_id VARCHAR(80) NOT NULL, 
	scorecard_id VARCHAR(120) NOT NULL, 
	criterion_id VARCHAR(80) NOT NULL, 
	rating SMALLINT NOT NULL, 
	comments TEXT, 
	criterion_name_snapshot VARCHAR(120) NOT NULL, 
	weight_snapshot NUMERIC(6, 3) NOT NULL, 
	maximum_rating_snapshot SMALLINT DEFAULT '5' NOT NULL, 
	mandatory_snapshot BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_scorecard_criteria PRIMARY KEY (scorecard_criteria_id), 
	CONSTRAINT uq_scorecard_criteria_scorecard_id UNIQUE (scorecard_id, criterion_id), 
	CONSTRAINT ck_scorecard_criteria_rating_range CHECK (rating BETWEEN 1 AND maximum_rating_snapshot), 
	CONSTRAINT ck_scorecard_criteria_weight_positive CHECK (weight_snapshot > 0), 
	CONSTRAINT ck_scorecard_criteria_maximum_rating CHECK (maximum_rating_snapshot = 5), 
	CONSTRAINT fk_scorecard_criteria_scorecard_id_scorecards FOREIGN KEY(scorecard_id) REFERENCES scorecards (scorecard_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_scorecard_criteria_criterion_id_evaluation_criteria FOREIGN KEY(criterion_id) REFERENCES evaluation_criteria (criterion_id) ON DELETE RESTRICT
);

CREATE INDEX ix_scorecard_criteria_criterion_id ON scorecard_criteria (criterion_id);
