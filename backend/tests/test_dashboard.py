"""Dashboard generation ke seams — bina LLM call ke.

Yahan jo test hota hai wo **widget selection** hai, kyunki wahi ek hissa hai jisme
judgement nahi, rule hai. Sub-questions banane wala hissa LLM ka kaam hai aur usme
"sahi jawab" hota hi nahi — uska test likhna model ke ek particular phrasing ko
pin kar dena hota, jo agle model version pe bina kisi asli bug ke toot jaata.
"""

import pytest

from app.dashboard import _title, choose_widget


class TestWidgetSelection:
    def test_single_value_is_a_kpi(self):
        """Ek number ko chart me dikhana decoration hai, information nahi."""
        assert choose_widget([{"count": 42}]) == "kpi"

    def test_few_categories_with_an_additive_number_is_a_donut(self):
        rows = [
            {"name": "Engineering", "headcount": 4},
            {"name": "Sales", "headcount": 2},
        ]
        assert choose_widget(rows) == "donut"

    def test_averages_never_become_a_donut(self):
        """**Ye ek asli bug se aaya test hai.**

        Pehla version "average salary by department" ko donut de deta tha. Donut
        kehta hai "ye hisse ek poore ke hain" — par averages jodte nahi; chaar
        departments ke average salary ka yog kisi cheez ko represent nahi karta.
        Wo chart data ke baare me ek jhooth bol raha tha.
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
        """Naam se pata na chale to bar — wo hamesha imaandaar rehta hai."""
        rows = [{"name": "Engineering", "salary": 101750}]
        assert choose_widget(rows) == "bar"

    def test_many_categories_become_a_bar(self):
        """Chhe se zyada slices par arc lambai se padhna band ho jaata hai aur
        legend hi chart ban jaata hai — wahan bar imaandaar hai.
        """
        rows = [{"name": f"D{i}", "n": i} for i in range(8)]
        assert choose_widget(rows) == "bar"

    def test_wide_results_stay_a_table(self):
        """Jo plot nahi hota use plot mat karo."""
        rows = [{"name": "Aarav", "role": "Engineer", "salary": 95000}]
        assert choose_widget(rows) == "table"

    def test_non_numeric_second_column_is_a_table(self):
        """Do columns kaafi nahi — doosra measure hona chahiye, warna chart ka
        koi magnitude hi nahi hota.
        """
        rows = [{"name": "Engineering", "location": "Bangalore"}]
        assert choose_widget(rows) == "table"

    def test_booleans_are_not_treated_as_numbers(self):
        """Python me `bool` `int` ka subclass hai. Bina is check ke ek true/false
        column magnitude ki tarah plot ho jaata.
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
        """Prefix strip ke baad kuch na bache to khaali heading nahi deni."""
        assert _title("salaries") == "Salaries"
