"""The seams of the HITL approval gate — no LLM, no Postgres, no real interrupt.

What is tested here is the **routing and the guard decision**: which query stops
at the gate, what execute does without an approval, where approve and reject lead,
and whether a write commits or rolls back. All of that is pure functions and
node-level behaviour — running a real graph interrupt needs a Postgres
checkpointer, and that is integration, not unit.

A real end-to-end approval cycle (pause → approve → rollback report) was verified
by hand separately; it is written up in `docs/CODE_NOTES.md`.
"""

import app.config as config_mod
import app.nodes as nodes_mod
from app.nodes import (
    after_approval,
    await_approval,
    execute_sql,
    is_destructive,
    needs_approval,
    synthesize_and_validate,
)


class TestDestructiveDetection:
    def test_plain_select_is_not_destructive(self):
        assert is_destructive("SELECT name FROM employees") is False

    def test_delete_is_destructive(self):
        assert is_destructive("DELETE FROM employees WHERE id = 1") is True

    def test_detection_is_case_insensitive(self):
        """The model sometimes emits lowercase SQL; the guard cannot rest on case."""
        assert is_destructive("drop table employees") is True

    def test_conservative_about_words_inside_literals(self):
        """This false positive is deliberate, not a bug.

        A substring match also fires on a literal such as the word updated. The
        cost of that is one needless approval prompt. The opposite case, a write
        slipping through silently, is far more expensive. The test exists so that
        nobody "fixes" this behaviour without understanding the trade-off.
        """
        assert is_destructive("SELECT * FROM logs WHERE msg = 'updated'") is True


class TestRouting:
    def test_select_goes_straight_to_execute(self):
        assert needs_approval({"sql_query": "SELECT 1"}) == "execute"

    def test_write_goes_to_the_approval_gate(self):
        assert needs_approval({"sql_query": "DELETE FROM employees"}) == "approval"

    def test_approved_continues_to_execute(self):
        assert after_approval({"approval_status": "approved"}) == "execute"

    def test_rejected_skips_execution(self):
        assert after_approval({"approval_status": "rejected"}) == "rejected"

    def test_missing_decision_is_treated_as_rejection(self):
        """If a resume arrives with no decision, the default cannot be "run it".

        That is the entire purpose of the gate — no write happens in an unknown
        state.
        """
        assert after_approval({}) == "rejected"


class TestApprovalNode:
    def test_records_the_approval_in_the_trace(self):
        out = await_approval({"approval_status": "approved", "logs": []})
        assert out["approval_status"] == "approved"
        assert any("approved" in line.lower() for line in out["logs"])

    def test_records_the_rejection_in_the_trace(self):
        out = await_approval({"approval_status": "rejected", "logs": []})
        assert any("rejected" in line.lower() for line in out["logs"])

    def test_decisionless_resume_becomes_a_rejection(self):
        out = await_approval({"logs": []})
        assert out["approval_status"] == "rejected"


class TestExecuteGuard:
    def test_write_without_approval_is_blocked(self):
        """The stateless path: no checkpointer, so no interrupt.

        There the old hard block is the right behaviour — showing an approval
        prompt that cannot be honoured drains the meaning out of the prompt
        itself.
        """
        out = execute_sql(
            {"sql_query": "DELETE FROM employees", "logs": [], "retry_count": 0}
        )
        assert out["error"]
        assert out["retry_count"] == config_mod.MAX_RETRIES, (
            "the block must exit the loop — a policy rejection is not fixed by "
            "retrying, the model would just write the same query again"
        )

    def test_approved_write_rolls_back_when_writes_are_disabled(self, monkeypatch):
        captured = {}

        def fake_run_write(query, commit):
            captured["commit"] = commit
            return 2

        monkeypatch.setattr(nodes_mod, "run_write", fake_run_write)
        monkeypatch.setattr(config_mod, "ALLOW_WRITES", False)

        out = execute_sql(
            {
                "sql_query": "DELETE FROM employees WHERE id = 1",
                "approval_status": "approved",
                "logs": [],
                "retry_count": 0,
            }
        )

        assert captured["commit"] is False
        assert not out["error"]
        assert "rolled back" in out["query_result"].lower()
        assert "2" in out["query_result"], "the affected count belongs in the report"

    def test_approved_write_commits_when_writes_are_enabled(self, monkeypatch):
        captured = {}

        def fake_run_write(query, commit):
            captured["commit"] = commit
            return 5

        monkeypatch.setattr(nodes_mod, "run_write", fake_run_write)
        monkeypatch.setattr(config_mod, "ALLOW_WRITES", True)

        out = execute_sql(
            {
                "sql_query": "UPDATE employees SET salary = 1",
                "approval_status": "approved",
                "logs": [],
                "retry_count": 0,
            }
        )

        assert captured["commit"] is True
        assert "committed" in out["query_result"].lower()

    def test_select_path_is_untouched_by_the_gate(self, monkeypatch):
        monkeypatch.setattr(nodes_mod, "run_sql", lambda q: [{"n": 1}])

        out = execute_sql({"sql_query": "SELECT 1", "logs": [], "retry_count": 0})

        assert not out["error"]
        assert "1" in out["query_result"]


class TestRejectionAnswer:
    def test_rejection_answer_is_not_generated_by_the_llm(self, monkeypatch):
        """A rejection is a fixed policy outcome, not something to generate.

        Having the model write it would give it room to narrate its way into
        saying something else — which is exactly how the earlier "removed from the
        HR department" lie happened, where the guard saved the data but the answer
        confirmed the deletion anyway.
        """

        def explode():
            raise AssertionError("the rejection path must not make an LLM call")

        monkeypatch.setattr(nodes_mod, "_llm", explode)

        out = synthesize_and_validate(
            {
                "question": "delete everyone in HR",
                "approval_status": "rejected",
                "sql_query": "DELETE FROM employees",
                "logs": [],
                "history": [],
            }
        )

        answer = out["final_answer"].lower()
        assert "not approved" in answer
        assert "nothing has been changed" in answer

    def test_rejected_turn_still_enters_history(self):
        """Otherwise the next follow-up would refer to a turn that never happened."""
        out = synthesize_and_validate(
            {
                "question": "delete everyone in HR",
                "approval_status": "rejected",
                "sql_query": "DELETE FROM employees",
                "logs": [],
                "history": [],
            }
        )
        assert len(out["history"]) == 1
        assert out["history"][0]["question"] == "delete everyone in HR"
