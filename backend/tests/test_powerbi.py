"""Power BI export ke tests.

Poora export deterministic hai — koi LLM, koi database, koi Power BI account. Jo
yahan test hota hai wo teen cheezein hain jo galat hone par chup-chaap nuksaan
karti hain: credentials file me chale jaana, M script ka quoting toot jaana, aur
duplicate query names ka ek doosre ko overwrite kar dena.
"""

import json

from app.powerbi import build_export, build_m_script, build_pbids


class TestPbids:
    def test_is_valid_json_with_a_postgres_connection(self):
        parsed = json.loads(build_pbids())
        conn = parsed["connections"][0]
        assert conn["details"]["protocol"] == "postgresql"
        assert "server" in conn["details"]["address"]

    def test_uses_directquery_not_import(self):
        """Import mode ek snapshot bana deta, aur Power BI wala dashboard is
        database se chupchaap purana hota jaata."""
        assert json.loads(build_pbids())["connections"][0]["mode"] == "DirectQuery"

    def test_never_contains_credentials(self, monkeypatch):
        """**Sabse zaroori test yahan.**

        Ye file user ko download hoti hai aur uske disk par rehti hai. Usme
        username/password daalna wahi galti hai jo `.env.example` me asli API key
        daalna thi. Power BI credentials khud maangta hai.
        """
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql://secretuser:secretpass@db.example.com:5432/prod"
        )
        text = build_pbids()
        assert "secretuser" not in text
        assert "secretpass" not in text
        assert "db.example.com:5432" in text


class TestMScript:
    def test_embeds_the_generated_sql(self):
        q = build_m_script("Headcount by department", "SELECT 1", 1)
        assert "SELECT 1" in q["script"]
        assert q["script"].startswith("let")

    def test_escapes_double_quotes(self):
        """M me `"` ko `""` likha jaata hai. Bina iske koi bhi quoted identifier
        script ko tod deta — aur error tab dikhta jab user paste karta.
        """
        q = build_m_script("q", 'SELECT "name" FROM employees', 1)
        assert '""name""' in q["script"]

    def test_names_are_prefixed_so_duplicates_cannot_collide(self):
        """Power BI me do queries ka ek naam hone par ek doosre ko chup-chaap
        overwrite kar deta hai."""
        a = build_m_script("Total headcount", "SELECT 1", 1)
        b = build_m_script("Total headcount", "SELECT 2", 2)
        assert a["name"] != b["name"]
        assert a["name"].startswith("Q1_")
        assert b["name"].startswith("Q2_")

    def test_name_survives_punctuation(self):
        q = build_m_script("What's the budget, per department?", "SELECT 1", 1)
        assert q["name"].isidentifier()


class TestExport:
    def test_skips_widgets_without_sql(self):
        """Skipped aur khaali widgets ka export me matlab nahi — unhe khaali
        query ki tarah bhejna Power BI me ek toota hua table bana deta."""
        dashboard = {
            "title": "Test",
            "widgets": [
                {"question": "a", "sql": "SELECT 1"},
                {"question": "b", "type": "skipped", "sql": ""},
                {"question": "c", "type": "empty"},
            ],
        }
        export = build_export(dashboard)
        assert len(export["queries"]) == 1
        assert export["queries"][0]["question"] == "a"

    def test_says_plainly_that_it_is_an_export_not_an_integration(self):
        """Claim ka doc ke saath match karna utna hi zaroori hai jitna code ka."""
        note = build_export({"widgets": []})["note"].lower()
        assert "not a power bi service integration" in note
