# Recruitment Management System Architecture

The system is organized around the recruitment lifecycle: requisitions, candidates, applications, interviews, scorecards, offers, and approvals.

## Components
- Data generation: synthetic but realistic records and edge-case injection.
- Business rules: stage transitions, scheduling validation, evaluation, and compensation guardrails.
- Validation: PK/FK, lifecycle, scheduling, scorecard, and offer checks.
- Metrics and analytics: conversion, conflict, acceptance, and operational KPIs.
- API layer: FastAPI endpoints for requisitions, candidates, applications, interviews, offers, approvals, and analytics.
- Dashboard: Streamlit overview for operational insights.
