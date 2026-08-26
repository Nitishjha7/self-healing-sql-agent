import os

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://agent:agent@localhost:5432/employees"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS employees (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT NOT NULL,
    salary INTEGER NOT NULL CHECK (salary > 0),
    role TEXT NOT NULL
);
"""

SEED_ROWS = [
    ("Aarav Sharma", "Engineering", 95000, "Backend Engineer"),
    ("Priya Verma", "Engineering", 87000, "Frontend Engineer"),
    ("Rohan Gupta", "Engineering", 120000, "Engineering Manager"),
    ("Sneha Iyer", "Marketing", 65000, "Marketing Executive"),
    ("Karan Mehta", "Marketing", 72000, "Marketing Manager"),
    ("Anjali Nair", "HR", 60000, "HR Executive"),
    ("Vikram Singh", "HR", 78000, "HR Manager"),
    ("Neha Kapoor", "Sales", 55000, "Sales Associate"),
    ("Arjun Reddy", "Sales", 91000, "Sales Manager"),
    ("Divya Rao", "Engineering", 105000, "DevOps Engineer"),
]


def get_schema_description() -> str:
    """LLM ko prompt me bhejne ke liye plain-text schema description."""
    return (
        "Table: employees\n"
        "Columns:\n"
        "  id INTEGER PRIMARY KEY\n"
        "  name TEXT\n"
        "  department TEXT (values e.g. 'Engineering', 'Marketing', 'HR', 'Sales')\n"
        "  salary INTEGER\n"
        "  role TEXT\n"
    )


def init_db() -> None:
    """Table banata hai (agar exist nahi karti) aur empty ho toh seed data daalta hai."""
    with engine.begin() as conn:
        conn.execute(text(SCHEMA_SQL))
        count = conn.execute(text("SELECT COUNT(*) FROM employees")).scalar()
        if count == 0:
            conn.execute(
                text(
                    "INSERT INTO employees (name, department, salary, role) "
                    "VALUES (:name, :department, :salary, :role)"
                ),
                [
                    {"name": n, "department": d, "salary": s, "role": r}
                    for n, d, s, r in SEED_ROWS
                ],
            )


def run_sql(query: str):
    """Read-only SQL execute karta hai aur rows + column names return karta hai."""
    with engine.connect() as conn:
        result = conn.execute(text(query))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        return rows


if __name__ == "__main__":
    init_db()
    print("Database initialized and seeded.")
