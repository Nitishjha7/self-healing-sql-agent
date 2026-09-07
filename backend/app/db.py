import os

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://agent:agent@localhost:5432/employees"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    budget INTEGER NOT NULL CHECK (budget > 0),
    location TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employees (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    department_id INTEGER NOT NULL REFERENCES departments(id),
    salary INTEGER NOT NULL CHECK (salary > 0),
    role TEXT NOT NULL
);
"""

# (name, budget, location)
DEPARTMENT_ROWS = [
    ("Engineering", 2500000, "Bangalore"),
    ("Marketing", 800000, "Mumbai"),
    ("HR", 400000, "Delhi"),
    ("Sales", 1200000, "Pune"),
]

# (name, department_name, salary, role)
EMPLOYEE_ROWS = [
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
    """LLM ko prompt me bhejne ke liye plain-text schema description.

    Isme deliberately do cheezein extra hain jo raw DDL me nahi hoti:
    example values (taaki LLM ko pata ho department kaise dikhte hain) aur
    join key ka explicit mention (taaki wo relationship guess na kare).
    """
    return (
        "Table: departments\n"
        "Columns:\n"
        "  id INTEGER PRIMARY KEY\n"
        "  name TEXT UNIQUE (values e.g. 'Engineering', 'Marketing', 'HR', 'Sales')\n"
        "  budget INTEGER (annual department budget)\n"
        "  location TEXT (city, e.g. 'Bangalore', 'Mumbai', 'Delhi', 'Pune')\n"
        "\n"
        "Table: employees\n"
        "Columns:\n"
        "  id INTEGER PRIMARY KEY\n"
        "  name TEXT\n"
        "  department_id INTEGER REFERENCES departments(id)\n"
        "  salary INTEGER (annual salary)\n"
        "  role TEXT (job title, e.g. 'Backend Engineer', 'Sales Manager')\n"
        "\n"
        "Relationship: employees.department_id -> departments.id\n"
        "The employees table has NO department name column — to filter or display a\n"
        "department name you MUST join to the departments table.\n"
    )


def _needs_rebuild(conn) -> bool:
    """Purana single-table schema detect karta hai.

    Pehle `employees` me ek TEXT `department` column tha. Agar wo mila, toh
    tables drop karke naye shape me rebuild karte hain. Ye demo-appropriate
    hai (data sirf seed hai) — production me Alembic migration hoti.
    """
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'employees' AND column_name = 'department'"
            )
        ).scalar()
    )


def init_db() -> None:
    """Tables banata hai (agar exist nahi karti) aur empty ho toh seed data daalta hai."""
    with engine.begin() as conn:
        if _needs_rebuild(conn):
            conn.execute(text("DROP TABLE IF EXISTS employees"))
            conn.execute(text("DROP TABLE IF EXISTS departments"))

        conn.execute(text(SCHEMA_SQL))

        if conn.execute(text("SELECT COUNT(*) FROM departments")).scalar() == 0:
            conn.execute(
                text(
                    "INSERT INTO departments (name, budget, location) "
                    "VALUES (:name, :budget, :location)"
                ),
                [
                    {"name": n, "budget": b, "location": loc}
                    for n, b, loc in DEPARTMENT_ROWS
                ],
            )

        if conn.execute(text("SELECT COUNT(*) FROM employees")).scalar() == 0:
            dept_ids = dict(
                conn.execute(text("SELECT name, id FROM departments")).fetchall()
            )
            conn.execute(
                text(
                    "INSERT INTO employees (name, department_id, salary, role) "
                    "VALUES (:name, :department_id, :salary, :role)"
                ),
                [
                    {
                        "name": n,
                        "department_id": dept_ids[d],
                        "salary": s,
                        "role": r,
                    }
                    for n, d, s, r in EMPLOYEE_ROWS
                ],
            )


def run_sql(query: str):
    """Read-only SQL execute karta hai aur rows + column names return karta hai."""
    with engine.connect() as conn:
        result = conn.execute(text(query))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        return rows


def get_schema_overview() -> dict:
    """Schema Explorer ke liye: columns, row counts, aur wahi text jo model ko jaata hai.

    Row counts live query se aate hain, columns hand-written list se. Ye jaan-boojh
    ke hai: is view ka poora point ye dikhana hai ki **model ko kya bataya jaata
    hai**, aur wo description bhi hand-written hai. `information_schema` se
    generate karne pe view aur prompt alag ho jaate, aur tab ye page kuch aur
    dikhata jo agent dekhta hi nahi.
    """
    tables = [
        {
            "name": "departments",
            "columns": [
                {"name": "id", "type": "SERIAL", "note": "primary key"},
                {"name": "name", "type": "TEXT", "note": "unique"},
                {"name": "budget", "type": "INTEGER", "note": "check > 0"},
                {"name": "location", "type": "TEXT", "note": "city"},
            ],
        },
        {
            "name": "employees",
            "columns": [
                {"name": "id", "type": "SERIAL", "note": "primary key"},
                {"name": "name", "type": "TEXT", "note": ""},
                {
                    "name": "department_id",
                    "type": "INTEGER",
                    "note": "FK -> departments.id",
                },
                {"name": "salary", "type": "INTEGER", "note": "check > 0"},
                {"name": "role", "type": "TEXT", "note": "job title"},
            ],
        },
    ]

    with engine.connect() as conn:
        for table in tables:
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table['name']}")  # noqa: S608 — fixed names
            ).scalar()
            table["rows"] = int(count)

    return {"tables": tables, "description": get_schema_description()}


def get_stats() -> dict:
    """Dashboard ke liye aggregates.

    Ye query hard-coded hai, agent se generate nahi hoti — dashboard ek fixed
    report hai, ek sawaal nahi. Agent se banwane ka matlab hota har page load pe
    ek LLM call, non-deterministic numbers, aur ek panel jo quota khatam hone pe
    khaali ho jaata.
    """
    with engine.connect() as conn:
        totals = conn.execute(
            text(
                "SELECT COUNT(*) AS headcount, "
                "       COALESCE(SUM(salary), 0) AS payroll, "
                "       COALESCE(AVG(salary), 0) AS avg_salary, "
                "       COALESCE(MAX(salary), 0) AS max_salary, "
                "       COALESCE(MIN(salary), 0) AS min_salary "
                "FROM employees"
            )
        ).mappings().one()

        by_dept = conn.execute(
            text(
                "SELECT d.name, d.location, d.budget, "
                "       COUNT(e.id) AS headcount, "
                "       COALESCE(SUM(e.salary), 0) AS payroll, "
                "       COALESCE(AVG(e.salary), 0) AS avg_salary "
                "FROM departments d "
                "LEFT JOIN employees e ON e.department_id = d.id "
                "GROUP BY d.id, d.name, d.location, d.budget "
                "ORDER BY d.name"
            )
        ).mappings().all()

        return {
            "headcount": int(totals["headcount"]),
            "department_count": len(by_dept),
            "payroll": int(totals["payroll"]),
            "avg_salary": round(float(totals["avg_salary"])),
            "max_salary": int(totals["max_salary"]),
            "min_salary": int(totals["min_salary"]),
            "departments": [
                {
                    "name": row["name"],
                    "location": row["location"],
                    "budget": int(row["budget"]),
                    "headcount": int(row["headcount"]),
                    "payroll": int(row["payroll"]),
                    "avg_salary": round(float(row["avg_salary"])),
                }
                for row in by_dept
            ],
        }


def run_write(query: str, commit: bool) -> int:
    """Data badalne wala statement chalata hai, affected row count deta hai.

    `run_sql` se alag jaan-boojh ke: `run_sql` contract se read-only hai aur uska
    caller maan ke chalta hai ki result set aayega. Write ke paas rows hoti hi
    nahi (`result.keys()` wahan error deta hai), aur dono ko ek function me mila
    dena wahi tareeka hai jisse ek "read-only" helper chupke se data badalne
    lagta hai.

    **`commit=False` pe statement phir bhi chalta hai** — Postgres use plan karta
    hai, saare constraints aur foreign keys enforce karta hai, aur batata hai
    kitni rows par asar padta — uske baad rollback ho jaata hai. Isi wajah se
    approval flow ek public deployment pe demo ho sakta hai bina visitors ko
    table khaali karne ki taakat diye. Report me ye kabhi chhupaya nahi jaata:
    user ko saaf bola jaata hai ki rollback hua.
    """
    with engine.connect() as conn:
        result = conn.execute(text(query))
        affected = result.rowcount
        if commit:
            conn.commit()
        else:
            conn.rollback()
        return affected


if __name__ == "__main__":
    init_db()
    print("Database initialized and seeded.")
