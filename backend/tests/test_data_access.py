"""Data access layer ke tests — bina MCP subprocess aur bina database ke.

Jo yahan test hota hai wo **contract** hai: dono raaste (direct driver aur MCP
tools) caller ko bilkul ek jaisa dikhein. Asli stdio session chalana integration
hai, unit nahi — aur wo alag se live verify hui hai (dekho `docs/CODE_NOTES.md`).

Sabse zaroori test yahan `test_mcp_error_becomes_an_exception` hai: self-healing
loop Postgres ke error text par chalta hai, aur MCP wo error ek success payload
ke andar bhejta hai. Agar ye layer usko wapas exception me na badle, to MCP on
karte hi self-healing chup-chaap kaam karna band kar deta — koi crash nahi, bas
retry kabhi trigger hi nahi hota. Us tarah ke bug sabse mehnge hote hain.
"""

import json

import pytest

import app.data_access as da


class FakeClient:
    """MCP bridge ki jagah — call record karta hai, tay-shuda text lautata hai."""

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
        """Ye wahi jagah hai jahan pehla version toota tha.

        Bridge har result ko JSON maan ke decode karta tha, aur `describe_schema`
        plain text deta hai. Transport ko har tool ka payload shape nahi pata
        hona chahiye — wo caller jaanta hai.
        """
        with_mcp({"describe_schema": "Table: employees\nColumns: ..."})
        assert da.get_schema_description().startswith("Table: employees")

    def test_mcp_error_becomes_an_exception(self, with_mcp):
        """**Poore MCP path ka sabse zaroori test.**

        Server error ko ek successful tool result ke andar bhejta hai, kyunki
        transport-level exception us message ko hi kha jaata jiski agent ko
        zaroorat hai. Ye layer usko wapas exception me badalti hai, taaki
        `execute_sql` ka `except` block dono raaston me ek jaisa chale.
        """
        msg = 'column "emp_name" does not exist\nHINT: Perhaps you meant "employees.name"'
        with_mcp({"run_select": json.dumps({"ok": False, "error": msg})})

        with pytest.raises(da.DataAccessError) as exc:
            da.run_sql("SELECT emp_name FROM employees")

        # HINT bacha rehna chahiye — retry prompt exactly usi par chalta hai.
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
