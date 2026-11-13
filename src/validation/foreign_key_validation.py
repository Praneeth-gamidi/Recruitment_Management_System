from __future__ import annotations


def validate_foreign_keys(rows: list[dict], parent_ids: set[str], child_key: str) -> list[str]:
    errors: list[str] = []
    for row in rows:
        ref = row.get(child_key)
        if ref and ref not in parent_ids:
            errors.append(f"Invalid foreign key {ref} in {child_key}")
    return errors
