from __future__ import annotations

from faker import Faker

fake = Faker()


def generate_candidates(count: int) -> list[dict]:
    return [{
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "email": f"{fake.user_name()}@example.com",
        "location": fake.city(),
        "education": fake.random_element(elements=["Bachelor's", "Master's", "PhD"]),
        "experience_years": fake.random_int(min=1, max=15),
    } for _ in range(count)]
