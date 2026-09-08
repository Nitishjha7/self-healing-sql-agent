"""Tests for the Power BI export.

The whole export is deterministic — no LLM, no database, no Power BI account.
What is tested here are the three things that do damage quietly when they go
wrong: credentials ending up in the file, the M script quoting breaking, and
duplicate query names overwriting one another.
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
        """Import mode would take a snapshot, and the Power BI dashboard would
        drift silently out of date with this database."""
        assert json.loads(build_pbids())["connections"][0]["mode"] == "DirectQuery"

    def test_never_contains_credentials(self, monkeypatch):
        """**The most important test in this file.**

        This file is downloaded by the user and lives on their disk. Putting a
        username and password in it would be the same mistake as putting a real
        API key in `.env.example`. Power BI asks for credentials itself.
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
        """In M a `"` is written as `""`. Without that, any quoted identifier
        would break the script — and the error would only appear when the user
        pasted it.
        """
        q = build_m_script("q", 'SELECT "name" FROM employees', 1)
        assert '""name""' in q["script"]

    def test_names_are_prefixed_so_duplicates_cannot_collide(self):
        """In Power BI two queries sharing a name silently overwrite each
        other."""
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
        """Skipped and empty widgets mean nothing in an export — shipping them as
        empty queries would produce a broken table in Power BI."""
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
        """A claim matching the docs matters as much as the code matching them."""
        note = build_export({"widgets": []})["note"].lower()
        assert "not a power bi service integration" in note
