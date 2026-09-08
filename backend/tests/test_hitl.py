"""HITL approval gate ke seams — bina LLM, bina Postgres, bina interrupt chalaye.

Yahan jo test hota hai wo **routing aur guard ka faisla** hai: kaunsi query gate
pe rukti hai, approval ke bina execute kya karta hai, approve/reject ke baad
kahan jaata hai, aur write commit hota hai ya rollback. Ye sab pure functions
aur node-level behaviour hai — asli graph interrupt chalane ke liye Postgres
checkpointer chahiye, aur wo integration hai, unit nahi.

Ek asli end-to-end approval cycle (pause → approve → rollback report) alag se
haath se verify hui hai; `docs/CODE_NOTES.md` me likhi hai.
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
        """Model kabhi lowercase SQL deta hai; guard case pe nahi tik sakta."""
        assert is_destructive("drop table employees") is True

    def test_conservative_about_words_inside_literals(self):
        """Ye jaan-boojh ke false positive hai, bug nahi.

        Substring match `'updated'` jaise literal pe bhi lag jaata hai. Uska
        anjaam ek fizool approval prompt hai. Ulta case — write chup-chaap nikal
        jaana — bahut mehnga hai. Test isliye hai ki ye behaviour koi galti se
        "theek" na kar de bina trade-off samjhe.
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
        """Resume bina faisle ke aaya to default "chalao" nahi ho sakta.

        Gate ka poora maqsad hi yahi hai — anjaan haalat me write nahi hoti.
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
        """Stateless mode ka path: koi checkpointer nahi, to koi interrupt nahi.

        Wahan purana hard block hi sahi hai — aisa approval prompt dikhana jise
        honour hi nahi kiya ja sakta, us prompt ka matlab hi khatam kar deta hai.
        """
        out = execute_sql(
            {"sql_query": "DELETE FROM employees", "logs": [], "retry_count": 0}
        )
        assert out["error"]
        assert out["retry_count"] == config_mod.MAX_RETRIES, (
            "block ko loop se bahar nikalna chahiye — policy rejection retry se "
            "theek nahi hoti, model wahi query dobara likhega"
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
        assert "2" in out["query_result"], "affected count report me hona chahiye"

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
        """Rejection ek fixed policy outcome hai, generate karne wali cheez nahi.

        Model se likhwane ka matlab hota use ye mauka dena ki wo narrate karte
        hue kuch aur bol de — wahi galti pehle "removed from the HR department"
        wale jhooth me nikli thi, jahan guard ne data bacha liya tha par jawab
        ne deletion confirm kar di.
        """

        def explode():
            raise AssertionError("rejection path me LLM call nahi honi chahiye")

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
        """Warna agla follow-up ek aise turn ko refer karta jo kabhi hua hi nahi."""
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
