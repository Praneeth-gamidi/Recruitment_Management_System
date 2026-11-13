INSERT INTO requisitions (id, title, department, location, status)
VALUES ('REQ-2026-000001', 'Senior Python Engineer', 'Engineering', 'New York', 'Open');

INSERT INTO candidates (id, first_name, last_name, email)
VALUES ('CAND-000001', 'Jane', 'Doe', 'jane.doe@example.com');

INSERT INTO applications (id, candidate_id, requisition_id, status)
VALUES ('APP-CAND-000001-REQ-2026-000001', 'CAND-000001', 'REQ-2026-000001', 'Applied');
