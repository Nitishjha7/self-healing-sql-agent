import os

from sqlalchemy import create_engine, text

from app.seed import DEPARTMENTS, build_employees, build_projects

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
    role TEXT NOT NULL,
    hire_date DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    department_id INTEGER NOT NULL REFERENCES departments(id),
    start_date DATE NOT NULL,
    status TEXT NOT NULL
);
"""


def get_schema_description() -> str:
    """The plain-text schema description that goes into the prompt.

    It deliberately carries two things raw DDL would not: example values (so the
    model knows what a department actually looks like) and an explicit mention of
    the join keys (so it does not have to guess the relationships).
    """
    return (
        "Table: departments\n"
        "Columns:\n"
        "  id INTEGER PRIMARY KEY\n"
        "  name TEXT UNIQUE (values: 'Engineering', 'Data Science', 'Product',\n"
        "       'Design', 'Marketing', 'Sales', 'Customer Success', 'HR')\n"
        "  budget INTEGER (annual department budget)\n"
        "  location TEXT (city: 'Bangalore', 'Mumbai', 'Delhi', 'Pune')\n"
        "\n"
        "Table: employees\n"
        "Columns:\n"
        "  id INTEGER PRIMARY KEY\n"
        "  name TEXT\n"
        "  department_id INTEGER REFERENCES departments(id)\n"
        "  salary INTEGER (annual salary)\n"
        "  role TEXT (job title, e.g. 'Backend Engineer', 'Data Scientist',\n"
        "       'Sales Manager', 'Product Designer')\n"
        "  hire_date DATE (when the employee joined; use for tenure and hiring trends)\n"
        "\n"
        "Table: projects\n"
        "Columns:\n"
        "  id INTEGER PRIMARY KEY\n"
        "  name TEXT\n"
        "  department_id INTEGER REFERENCES departments(id)\n"
        "  start_date DATE\n"
        "  status TEXT (values: 'active', 'completed')\n"
        "\n"
        "Relationships:\n"
        "  employees.department_id -> departments.id\n"
        "  projects.department_id  -> departments.id\n"
        "\n"
        "The employees table has NO department name column — to filter or display a\n"
        "department name you MUST join to the departments table. To relate employees\n"
        "to projects, join both through departments.\n"
        "Today's date is 2026-01-01; use it for any 'how long' or 'this year' question.\n"
    )


def _needs_rebuild(conn) -> bool:
    """Detect the older single-table schema.

    `employees` used to carry a TEXT `department` column. If that is still there,
    drop the tables and rebuild them in the new shape. This is demo-appropriate
    (the data is only seed data) — production would use an Alembic migration.
    """
    has_old_column = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'employees' AND column_name = 'department'"
        )
    ).scalar()
    if has_old_column:
        return True

    # One generation older still: two tables, but without `hire_date` and without
    # `projects`. That needs a rebuild too, otherwise the new schema description
    # would mention columns the table does not have — and the agent would fail
    # every date-related question for no visible reason.
    employees_exists = conn.execute(
        text("SELECT to_regclass('public.employees')")
    ).scalar()
    if not employees_exists:
        return False

    has_hire_date = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'employees' AND column_name = 'hire_date'"
        )
    ).scalar()
    return not has_hire_date


def init_db() -> None:
    """Create the tables if they do not exist, and seed them if they are empty."""
    with engine.begin() as conn:
        if _needs_rebuild(conn):
            # Order matters: projects and employees both reference departments,
            # so they have to be dropped first.
            conn.execute(text("DROP TABLE IF EXISTS projects"))
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
                    for n, b, loc in DEPARTMENTS
                ],
            )

        dept_ids = dict(
            conn.execute(text("SELECT name, id FROM departments")).fetchall()
        )

        if conn.execute(text("SELECT COUNT(*) FROM employees")).scalar() == 0:
            conn.execute(
                text(
                    "INSERT INTO employees (name, department_id, salary, role, hire_date) "
                    "VALUES (:name, :department_id, :salary, :role, :hire_date)"
                ),
                [
                    {
                        "name": n,
                        "department_id": dept_ids[d],
                        "salary": s,
                        "role": r,
                        "hire_date": hd,
                    }
                    for n, d, s, r, hd in build_employees()
                ],
            )

        if conn.execute(text("SELECT COUNT(*) FROM projects")).scalar() == 0:
            conn.execute(
                text(
                    "INSERT INTO projects (name, department_id, start_date, status) "
                    "VALUES (:name, :department_id, :start_date, :status)"
                ),
                [
                    {
                        "name": n,
                        "department_id": dept_ids[d],
                        "start_date": sd,
                        "status": st,
                    }
                    for n, d, sd, st in build_projects()
                ],
            )


def run_sql(query: str):
    """Execute read-only SQL and return the rows with their column names."""
    with engine.connect() as conn:
        result = conn.execute(text(query))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        return rows


def get_schema_overview() -> dict:
    """For the Schema Explorer: columns, row counts, and the exact text the model sees.

    Row counts come from a live query, the columns from a hand-written list. That
    is deliberate: the whole point of this view is to show **what the model is
    told**, and that description is hand-written too. Generating it from
    `information_schema` would let the view and the prompt drift apart, and then
    this page would be showing something the agent never sees.
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
                {"name": "hire_date", "type": "DATE", "note": "tenure, hiring trends"},
                {"name": "salary", "type": "INTEGER", "note": "check > 0"},
                {"name": "role", "type": "TEXT", "note": "job title"},
            ],
        },
        {
            "name": "projects",
            "columns": [
                {"name": "id", "type": "SERIAL", "note": "primary key"},
                {"name": "name", "type": "TEXT", "note": ""},
                {
                    "name": "department_id",
                    "type": "INTEGER",
                    "note": "FK -> departments.id",
                },
                {"name": "start_date", "type": "DATE", "note": ""},
                {"name": "status", "type": "TEXT", "note": "active / completed"},
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
    """Aggregates for the dashboard.

    This query is hard-coded rather than generated by the agent — the dashboard is
    a fixed report, not a question. Having the agent build it would mean an LLM
    call on every page load, non-deterministic numbers, and a panel that goes
    blank the moment the quota runs out.
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
    """Run a data-modifying statement and return the affected row count.

    Kept separate from `run_sql` on purpose: `run_sql` is read-only by contract and
    its caller assumes a result set comes back. A write has no rows at all
    (`result.keys()` raises there), and merging the two into one function is
    exactly how a "read-only" helper quietly starts modifying data.

    **With `commit=False` the statement still runs** — Postgres plans it, enforces
    every constraint and foreign key, and reports how many rows it would have
    touched — and is then rolled back. That is what makes the approval flow
    demonstrable on a public deployment without handing visitors the ability to
    empty a table. The report never hides this: the user is told plainly that the
    statement was rolled back.
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
