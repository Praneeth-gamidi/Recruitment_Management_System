from __future__ import annotations


def validate_primary_keys(records: list[dict]) -> list[str]:
    errors: list[str] = []
    seen = set()
    for record in records:
        rec_id = record.get("id")
        if not rec_id:
            errors.append("Missing primary key")
            continue
        if rec_id in seen:
            errors.append(f"Duplicate primary key: {rec_id}")
        seen.add(rec_id)
    return errors
