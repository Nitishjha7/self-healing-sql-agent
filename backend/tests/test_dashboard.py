"""The seams of dashboard generation — without an LLM call.

What is tested here is **widget selection**, because that is the one part with a
rule rather than judgement. Planning the sub-questions is the LLM job and has no
"right answer" — testing it would pin down one particular phrasing of one model,
and break on the next model version without any real bug.
"""

import pytest

from app.dashboard import _title, choose_widget


class TestWidgetSelection:
    def test_single_value_is_a_kpi(self):
        """Charting a single number is decoration, not information."""
        assert choose_widget([{"count": 42}]) == "kpi"

    def test_few_categories_with_an_additive_number_is_a_donut(self):
        rows = [
            {"name": "Engineering", "headcount": 4},
            {"name": "Sales", "headcount": 2},
        ]
        assert choose_widget(rows) == "donut"

    def test_averages_never_become_a_donut(self):
        """**This test came out of a real bug.**

        The first version gave "average salary by department" a donut. A donut
        says "these are parts of a whole" — but averages do not add up; the sum of
        four departments’ average salaries represents nothing. That chart was
        telling a lie about the data.
        """
        rows = [
            {"department_name": "Engineering", "average_salary": 101750.0},
            {"department_name": "Sales", "average_salary": 73000.0},
        ]
        assert choose_widget(rows) == "bar"

    def test_rates_and_percentages_also_stay_bars(self):
        rows = [{"name": "Engineering", "pct_of_budget": 16.3}]
        assert choose_widget(rows) == "bar"

    def test_an_ambiguous_measure_falls_back_to_a_bar(self):
        """When the name is not conclusive, use a bar — it is always honest."""
        rows = [{"name": "Engineering", "salary": 101750}]
        assert choose_widget(rows) == "bar"

    def test_many_categories_become_a_bar(self):
        """Past six slices, arc length stops being readable and the legend
        becomes the chart — a bar is the honest choice there.
        """
        rows = [{"name": f"D{i}", "n": i} for i in range(8)]
        assert choose_widget(rows) == "bar"

    def test_wide_results_stay_a_table(self):
        """Do not plot what does not plot."""
        rows = [{"name": "Aarav", "role": "Engineer", "salary": 95000}]
        assert choose_widget(rows) == "table"

    def test_non_numeric_second_column_is_a_table(self):
        """Two columns is not enough — the second has to be a measure, or the
        chart has no magnitude to draw.
        """
        rows = [{"name": "Engineering", "location": "Bangalore"}]
        assert choose_widget(rows) == "table"

    def test_booleans_are_not_treated_as_numbers(self):
        """`bool` is a subclass of `int` in Python. Without this check a
        true/false column would be plotted as a magnitude.
        """
        rows = [{"name": "Engineering", "is_remote": True}]
        assert choose_widget(rows) == "table"

    def test_no_rows_is_empty(self):
        assert choose_widget([]) == "empty"


class TestTitle:
    @pytest.mark.parametrize(
        "request_text,expected_start",
        [
            ("Create a dashboard showing salary by department", "Salary by department"),
            ("show me headcount per location", "Headcount per location"),
            ("Build a report of budgets", "Budgets"),
        ],
    )
    def test_strips_the_request_boilerplate(self, request_text, expected_start):
        assert _title(request_text).startswith(expected_start)

    def test_falls_back_to_the_request_itself(self):
        """If stripping the prefixes leaves nothing, do not return an empty heading."""
        assert _title("salaries") == "Salaries"
