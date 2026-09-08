"""Tests for the output guard.

The validator is entirely deterministic, so these tests are too — no LLM, no
database, no mocking. That is the whole point of the design: what the prompt asks
for is a request, this check is a guarantee.
"""

from app.validators import validate_answer


class TestCleanAnswers:
    def test_normal_answer_passes_untouched(self):
        answer = "The Engineering department has the highest average salary."
        assert validate_answer(answer) == (answer, [])

    def test_ordinary_words_are_not_flagged(self):
        """`salary`, `name`, `role`, `budget` and `location` are in the schema and
        also in ordinary English. Flagging them would break every correct answer
        — this one line is what keeps the validator usable.
        """
        answer = (
            "Her role is Sales Manager, her name is Neha, the salary is "
            "competitive, the budget is fixed and the location is Pune."
        )
        assert validate_answer(answer) == (answer, [])

    def test_the_word_select_alone_is_not_sql(self):
        """SQL detection needs `FROM` alongside `SELECT`, otherwise a sentence
        like "you can select any department" would be read as a leak.
        """
        answer = "You can select any department to see its headcount."
        assert validate_answer(answer) == (answer, [])


class TestSchemaLeakage:
    def test_qualified_identifier_is_stripped(self):
        answer, flags = validate_answer("The value of employees.salary is 95000.")
        assert flags == ["qualified_identifier"]
        assert "employees.salary" not in answer
        assert "salary" in answer

    def test_table_alias_is_stripped(self):
        answer, flags = validate_answer("Sorted by d.name and e.salary.")
        assert flags == ["qualified_identifier"]
        assert "d.name" not in answer
        assert "e.salary" not in answer

    def test_schema_only_column_is_rewritten(self):
        """`department_id` never occurs in ordinary English, so flagging it is
        safe — unlike words such as `salary`.
        """
        answer, flags = validate_answer("Grouped by department_id.")
        assert flags == ["schema_column_name"]
        assert "department_id" not in answer
        assert "department" in answer

    def test_both_kinds_are_reported(self):
        answer, flags = validate_answer(
            "Joined on employees.department_id and grouped by department_id."
        )
        assert set(flags) == {"qualified_identifier", "schema_column_name"}


class TestSqlLeakage:
    def test_sql_in_the_answer_replaces_it_entirely(self):
        """This replaces rather than redacts.

        The other leaks are token-level and can be removed cleanly. A whole query
        in the answer means the synthesizer did the wrong job entirely — cutting
        pieces out of it and showing the remainder would hand the user a partial
        answer that still looks trustworthy.
        """
        answer, flags = validate_answer(
            "SELECT name FROM employees WHERE salary > 80000 returned 4 rows."
        )
        assert flags == ["sql_in_answer"]
        assert "SELECT" not in answer
        assert "employees" not in answer

    def test_sql_leak_short_circuits_other_checks(self):
        """A SQL leak is the most serious case; the answer is replaced wholesale
        anyway, so reporting smaller leaks in that same text means nothing.
        """
        _, flags = validate_answer(
            "SELECT employees.salary FROM employees where department_id = 1"
        )
        assert flags == ["sql_in_answer"]
