"""Realistic seed data — deterministically generated.

**Kyun 10 rows kaafi nahi the.** Purana dataset 10 employees aur 4 departments ka
tha, aur usse teen cheezein toot rahi thi:

- **Dashboard khaali dikhta tha.** Chaar bars ka bar chart chart nahi lagta.
- **Koi date column hi nahi tha**, matlab "hiring trend" jaisa sabse natural
  dashboard sawaal poochha hi nahi ja sakta tha.
- **Joins do table se aage nahi jaate the.** Real Text-to-SQL ki dikkat multi-hop
  join me hai — "kis project pe sabse mehnge log lage hain" jaisa sawaal teen
  tables chhoota hai, aur wahi jagah hai jahan model galtiyan karta hai.

**Random hai, par seeded random hai.** `random.Random(42)` fixed hai, to har
machine par bilkul wahi data banta hai. Ye eval ke liye zaroori hai: agar seed
badalta rehta to accuracy ka har number pichhle run se compare karne layak hi na
rehta, aur "self-healing se accuracy badhi" jaisa daawa bemaani ho jaata.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

# Fixed seed. Isko badalna matlab har purana eval number bekaar ho jaana.
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

# Har department ke roles, salary band ke saath. Bands overlap karte hain aur
# seniority ke saath badhte hain — flat random salary se questions bemaani ho
# jaate ("highest paid" ka jawab shudh sanyog hota).
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

# Headcount har department ka. Jaan-boojh ke asamaan: Engineering bada, HR chhota
# — taaki "which department has the most people" ka jawab dilchasp ho, sabka
# ek jaisa na ho.
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
    """Unique naam. Duplicates se "who earns most" jaise sawaal ambiguous ho jaate."""
    for _ in range(500):
        candidate = f"{_rng.choice(_FIRST)} {_rng.choice(_LAST)}"
        if candidate not in used:
            used.add(candidate)
            return candidate
    # Naam khatam ho jaayein to suffix — chup-chaap duplicate dene se behtar.
    return f"{_rng.choice(_FIRST)} {_rng.choice(_LAST)} {len(used)}"


def build_employees() -> list[tuple]:
    """(name, department, salary, role, hire_date) — deterministic."""
    used: set[str] = set()
    rows = []

    for dept, count in _HEADCOUNT.items():
        roles = _ROLES[dept]
        for _ in range(count):
            # Manager-level roles kam hote hain: aakhri role har department me
            # senior hai, aur wo sirf 10% logon ko milta hai. Isse "average
            # salary" aur "highest paid" alag jawab dete hain, jo unhe interesting
            # banata hai.
            if _rng.random() < 0.10:
                role, low, high = roles[-1]
            else:
                role, low, high = _rng.choice(roles[:-1]) if len(roles) > 1 else roles[0]

            salary = _rng.randrange(low, high + 1, 500)

            # Hire dates pichhle ~6 saal me faili hui, haal ke saalon me zyada —
            # ek badhti hui company jaisa. Iske bina hiring-trend chart flat aata.
            #
            # `abs(gauss)` zyadatar 0-3 ke beech rehta hai, isliye multiplier hi
            # asli spread tay karta hai: 700 se lagbhag 6 saal milte hain. Pehla
            # version 380 tha aur sirf 3 saal deta tha — comment 6 kehta tha,
            # data 3 dikhata tha.
            days_ago = int(abs(_rng.gauss(0, 1)) * 700) % (6 * 365)
            hire_date = _TODAY - timedelta(days=days_ago + 20)

            rows.append((_name(used), dept, salary, role, hire_date.isoformat()))

    return rows


def build_projects() -> list[tuple]:
    """(name, department, start_date, status) — teesri table, multi-hop joins ke liye."""
    rows = []
    for name, dept, year, month in _PROJECTS:
        start = date(year, month, 1)
        status = "completed" if start < _TODAY - timedelta(days=400) else "active"
        rows.append((name, dept, start.isoformat(), status))
    return rows
