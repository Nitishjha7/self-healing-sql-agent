"""Tests for the data access layer — with no MCP subprocess and no database.

What is tested here is the **contract**: both routes (the direct driver and the
MCP tools) must look identical to the caller. Running a real stdio session is
integration, not unit — and that was verified live separately (see
`docs/CODE_NOTES.md`).

The most important test here is `test_mcp_error_becomes_an_exception`: the
self-healing loop runs on Postgres error text, and MCP delivers that error inside
a success payload. If this layer did not turn it back into an exception, then
switching MCP on would silently stop self-healing — no crash, the retry simply
never fires. Bugs of that kind are the most expensive ones.
"""

import json

import pytest

import app.data_access as da


class FakeClient:
    """Stands in for the MCP bridge — records the call, returns fixed text."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call(self, tool, args, timeout=30.0):
        self.calls.append((tool, args))
        return self.responses[tool]


@pytest.fixture
def no_mcp(monkeypatch):
    monkeypatch.setattr(da, "get_client", lambda: None)


@pytest.fixture
def with_mcp(monkeypatch):
    def _install(responses):
        client = FakeClient(responses)
        monkeypatch.setattr(da, "get_client", lambda: client)
        return client

    return _install


class TestMode:
    def test_reports_direct_when_no_client(self, no_mcp):
        assert da.mode() == "direct"

    def test_reports_mcp_when_client_present(self, with_mcp):
        with_mcp({})
        assert da.mode() == "mcp"


class TestDirectPath:
    def test_falls_through_to_the_driver(self, no_mcp, monkeypatch):
        monkeypatch.setattr(da.db, "run_sql", lambda q: [{"n": 1}])
        assert da.run_sql("SELECT 1") == [{"n": 1}]

    def test_write_passes_the_commit_flag_through(self, no_mcp, monkeypatch):
        seen = {}

        def fake(query, commit):
            seen["commit"] = commit
            return 3

        monkeypatch.setattr(da.db, "run_write", fake)
        assert da.run_write("DELETE FROM employees", commit=False) == 3
        assert seen["commit"] is False


class TestMcpPath:
    def test_rows_come_back_in_the_same_shape(self, with_mcp):
        with_mcp({"run_select": json.dumps({"ok": True, "rows": [{"n": 1}], "row_count": 1})})
        assert da.run_sql("SELECT 1") == [{"n": 1}]

    def test_schema_is_plain_text_not_json(self, with_mcp):
        """This is exactly where the first version broke.

        The bridge decoded every result as JSON, and `describe_schema` returns
        plain text. The transport should not know the payload shape of each tool
        — the caller knows that.
        """
        with_mcp({"describe_schema": "Table: employees\nColumns: ..."})
        assert da.get_schema_description().startswith("Table: employees")

    def test_mcp_error_becomes_an_exception(self, with_mcp):
        """**The most important test on the whole MCP path.**

        The server returns the error inside a successful tool result, because a
        transport-level exception would swallow the very message the agent needs.
        This layer turns it back into an exception, so that the `except` block in
        `execute_sql` behaves identically on both routes.
        """
        msg = 'column "emp_name" does not exist\nHINT: Perhaps you meant "employees.name"'
        with_mcp({"run_select": json.dumps({"ok": False, "error": msg})})

        with pytest.raises(da.DataAccessError) as exc:
            da.run_sql("SELECT emp_name FROM employees")

        # The HINT must survive — the retry prompt runs on exactly that.
        assert "HINT" in str(exc.value)
        assert "emp_name" in str(exc.value)

    def test_write_forwards_the_commit_flag(self, with_mcp):
        client = with_mcp(
            {"run_modify": json.dumps({"ok": True, "affected": 2, "committed": False})}
        )
        assert da.run_write("DELETE FROM employees", commit=False) == 2
        assert client.calls[0] == ("run_modify", {"query": "DELETE FROM employees", "commit": False})

    def test_write_failure_also_raises(self, with_mcp):
        with_mcp({"run_modify": json.dumps({"ok": False, "error": "permission denied"})})
        with pytest.raises(da.DataAccessError):
            da.run_write("DELETE FROM employees", commit=True)
