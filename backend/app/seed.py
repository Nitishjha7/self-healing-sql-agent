"""Realistic seed data — deterministically generated.

**Why 10 rows were not enough.** The old dataset had 10 employees and 4
departments, and three things broke because of it:

- **The dashboard looked empty.** A bar chart with four bars does not read as a
  chart.
- **There was no date column at all**, so the most natural dashboard question of
  all — "hiring trend" — could not even be asked.
- **Joins never went past two tables.** The hard part of real Text-to-SQL is the
  multi-hop join — a question like "which project has the most expensive people
  on it" touches three tables, and that is exactly where models make mistakes.

**It is random, but seeded random.** `random.Random(42)` is fixed, so every
machine generates exactly the same data. That matters for the eval: if the seed
drifted, no accuracy number could be compared with a previous run, and a claim
like "self-healing improved accuracy" would mean nothing.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

# Fixed seed. Changing it invalidates every previous eval number.
_rng = random.Random(42)

# (name, budget, location)
DEPARTMENTS = [
    ("Engineering", 9_800_000, "Bangalore"),
    ("Data Science", 4_200_000, "Bangalore"),
    ("Product", 3_100_000, "Mumbai"),
    ("Design", 1_900_000, "Mumbai"),
    ("Marketing", 2_600_000, "Delhi"),
    ("Sales", 5_400_000, "Pune"),
    ("Customer Success", 2_200_000, "Pune"),
    ("HR", 1_400_000, "Delhi"),
]

# Roles per department, with a salary band. The bands overlap and rise with
# seniority — a flat random salary would make the questions meaningless ("highest
# paid" would be pure coincidence).
_ROLES = {
    "Engineering": [
        ("Backend Engineer", 70_000, 130_000),
        ("Frontend Engineer", 65_000, 120_000),
        ("DevOps Engineer", 80_000, 140_000),
        ("QA Engineer", 55_000, 95_000),
        ("Engineering Manager", 150_000, 210_000),
    ],
    "Data Science": [
        ("Data Analyst", 60_000, 100_000),
        ("Data Scientist", 90_000, 160_000),
        ("ML Engineer", 100_000, 175_000),
        ("Analytics Manager", 145_000, 195_000),
    ],
    "Product": [
        ("Associate PM", 70_000, 105_000),
        ("Product Manager", 110_000, 165_000),
        ("Group Product Manager", 165_000, 225_000),
    ],
    "Design": [
        ("Product Designer", 65_000, 115_000),
        ("UX Researcher", 70_000, 120_000),
        ("Design Lead", 130_000, 180_000),
    ],
    "Marketing": [
        ("Marketing Executive", 40_000, 70_000),
        ("Content Strategist", 55_000, 95_000),
        ("Growth Manager", 95_000, 145_000),
    ],
    "Sales": [
        ("Sales Associate", 40_000, 70_000),
        ("Account Executive", 65_000, 115_000),
        ("Enterprise AE", 95_000, 160_000),
        ("Sales Manager", 130_000, 185_000),
    ],
    "Customer Success": [
        ("Support Specialist", 35_000, 60_000),
        ("CS Manager", 85_000, 130_000),
    ],
    "HR": [
        ("HR Executive", 40_000, 68_000),
        ("Recruiter", 50_000, 88_000),
        ("HR Manager", 95_000, 140_000),
    ],
}

# Headcount per department. Deliberately uneven: Engineering large, HR small — so
# that "which department has the most people" has an interesting answer rather
# than a tie.
_HEADCOUNT = {
    "Engineering": 46,
    "Data Science": 18,
    "Product": 12,
    "Design": 10,
    "Marketing": 15,
    "Sales": 34,
    "Customer Success": 16,
    "HR": 9,
}

_FIRST = """Aarav Vivaan Aditya Vihaan Arjun Sai Reyansh Krishna Ishaan Rudra
Ayaan Dhruv Kabir Ritvik Aryan Yash Om Advait Atharv Shaurya Ananya Diya Saanvi
Aadhya Anika Navya Myra Sara Pari Riya Ira Kiara Meera Aarohi Anvi Prisha Tara
Nitya Kavya Isha Rohan Karan Nikhil Varun Siddharth Manav Rahul Gaurav Ankit
Harsh Neha Priya Sneha Pooja Divya Shreya Tanvi Nisha Ritika Swati""".split()

_LAST = """Sharma Verma Gupta Iyer Mehta Nair Singh Kapoor Reddy Rao Desai Joshi
Malhotra Chopra Bose Banerjee Chatterjee Menon Pillai Shetty Bhat Kulkarni Patil
Agarwal Bansal Khanna Sethi Ahuja Trivedi Mishra""".split()

_PROJECTS = [
    ("Atlas Migration", "Engineering", 2023, 8),
    ("Realtime Pipeline", "Data Science", 2024, 5),
    ("Mobile Revamp", "Design", 2024, 4),
    ("Billing Platform", "Engineering", 2022, 9),
    ("Churn Model", "Data Science", 2025, 4),
    ("Partner Portal", "Product", 2024, 6),
    ("Campaign Engine", "Marketing", 2023, 3),
    ("CRM Rollout", "Sales", 2025, 7),
    ("Onboarding Redesign", "Customer Success", 2025, 3),
    ("Data Warehouse", "Data Science", 2022, 6),
]

_TODAY = date(2026, 1, 1)


def _name(used: set[str]) -> str:
    """A unique name. Duplicates would make questions like "who earns most" ambiguous."""
    for _ in range(500):
        candidate = f"{_rng.choice(_FIRST)} {_rng.choice(_LAST)}"
        if candidate not in used:
            used.add(candidate)
            return candidate
    # If the names run out, add a suffix — better than silently returning a duplicate.
    return f"{_rng.choice(_FIRST)} {_rng.choice(_LAST)} {len(used)}"


def build_employees() -> list[tuple]:
    """(name, department, salary, role, hire_date) — deterministic."""
    used: set[str] = set()
    rows = []

    for dept, count in _HEADCOUNT.items():
        roles = _ROLES[dept]
        for _ in range(count):
            # Manager-level roles are rare: the last role in each department is
            # the senior one, and only 10% of people get it. That makes "average
            # salary" and "highest paid" give different answers, which is what
            # makes them interesting questions.
            if _rng.random() < 0.10:
                role, low, high = roles[-1]
            else:
                role, low, high = _rng.choice(roles[:-1]) if len(roles) > 1 else roles[0]

            salary = _rng.randrange(low, high + 1, 500)

            # Hire dates spread over roughly the last 6 years, weighted towards
            # recent ones — the shape of a growing company. Without that, the
            # hiring-trend chart comes out flat.
            #
            # `abs(gauss)` mostly lands between 0 and 3, so the multiplier is what
            # actually sets the spread: 700 gives about 6 years. The first version
            # used 380 and only produced 3 — the comment said 6 while the data
            # showed 3.
            days_ago = int(abs(_rng.gauss(0, 1)) * 700) % (6 * 365)
            hire_date = _TODAY - timedelta(days=days_ago + 20)

            rows.append((_name(used), dept, salary, role, hire_date.isoformat()))

    return rows


def build_projects() -> list[tuple]:
    """(name, department, start_date, status) — the third table, for multi-hop joins."""
    rows = []
    for name, dept, year, month in _PROJECTS:
        start = date(year, month, 1)
        status = "completed" if start < _TODAY - timedelta(days=400) else "active"
        rows.append((name, dept, start.isoformat(), status))
    return rows
