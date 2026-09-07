"""Output guard ke tests.

Ye validator poori tarah deterministic hai, isliye iske tests bhi — koi LLM, koi
database, koi mocking nahi. Yahi is design ka poora point hai: prompt me likhi
gayi baat ek guzarish hai, ye check ek guarantee.
"""

from app.validators import validate_answer


class TestCleanAnswers:
    def test_normal_answer_passes_untouched(self):
        answer = "The Engineering department has the highest average salary."
        assert validate_answer(answer) == (answer, [])

    def test_ordinary_words_are_not_flagged(self):
        """`salary`, `name`, `role`, `budget`, `location` schema me bhi hain aur
        aam angrezi me bhi. Inhe flag karna har sahi jawab tod deta — yahi ek
        line is validator ko istemaal ke laayak rakhti hai.
        """
        answer = (
            "Her role is Sales Manager, her name is Neha, the salary is "
            "competitive, the budget is fixed and the location is Pune."
        )
        assert validate_answer(answer) == (answer, [])

    def test_the_word_select_alone_is_not_sql(self):
        """SQL detection ke liye `SELECT` ke saath `FROM` bhi chahiye, warna
        "you can select any department" jaisa vaakya bhi leak samjha jaata.
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
        """`department_id` aam angrezi me kabhi nahi aata, to ise flag karna safe
        hai — `salary` jaise shabdon ke ulat.
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
        """Yahan redact nahi karte, badal dete hain.

        Baaki leaks token-level hain aur nikaale ja sakte hain. Poori query answer
        me aa jaana matlab synthesizer ne kaam hi galat kiya — usme se tukde kaat
        kar bacha hua text dikhana user ko ek adhoora, bharosemand-dikhne wala
        jawab de deta.
        """
        answer, flags = validate_answer(
            "SELECT name FROM employees WHERE salary > 80000 returned 4 rows."
        )
        assert flags == ["sql_in_answer"]
        assert "SELECT" not in answer
        assert "employees" not in answer

    def test_sql_leak_short_circuits_other_checks(self):
        """SQL leak sabse gambhir hai; jawab waise bhi poora badal jaata hai, to
        usi text me chhote leaks alag se report karne ka koi matlab nahi.
        """
        _, flags = validate_answer(
            "SELECT employees.salary FROM employees where department_id = 1"
        )
        assert flags == ["sql_in_answer"]
