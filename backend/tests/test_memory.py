"""The seams of conversation memory — without a single LLM or Postgres call.

**Why no real model here:** these tests check the *semantics* of memory, not the
quality of the model. The real question is which state carries between turns and
which resets. That question lives entirely outside the LLM, and the Gemini free
tier allows 20 requests/day, so spending that quota on tests that learn nothing
from it is a straight loss.

A real multi-turn conversation was verified by hand separately — it is written up
in `docs/CODE_NOTES.md`.
"""

import app.config as config_mod
import app.graph as graph_mod
import app.nodes as nodes_mod
from app.nodes import _append_turn, _format_history


class TestHistoryFormatting:
    def test_empty_history_adds_nothing_to_the_prompt(self):
        """On the first turn the prompt must be exactly what it always was.

        Sending an empty "Earlier in this conversation:" heading suggests a
        context to the model that does not exist.
        """
        assert _format_history([]) == ""

    def test_history_carries_sql_not_just_the_answer(self):
        """The SQL is what actually resolves the reference.

        The English answer to "Which department has the highest average salary?"
        may or may not name the department; that turn’s SQL
        (`ORDER BY AVG(salary) DESC LIMIT 1`) always says what "them" refers to.
        """
        block = _format_history(
            [
                {
                    "question": "Which department has the highest average salary?",
                    "sql_query": "SELECT d.name FROM departments d ORDER BY 1 LIMIT 1",
                    "answer": "Engineering.",
                }
            ]
        )
        assert "highest average salary" in block
        assert "ORDER BY 1 LIMIT 1" in block
        assert "Engineering." in block

    def test_only_the_last_few_turns_are_sent(self, monkeypatch):
        """Sending the whole history costs both tokens and attention."""
        monkeypatch.setattr(config_mod, "HISTORY_TURNS_IN_PROMPT", 2)

        history = [
            {"question": f"q{i}", "sql_query": f"sql{i}", "answer": f"a{i}"}
            for i in range(5)
        ]
        block = _format_history(history)

        assert "q4" in block and "q3" in block
        assert "q0" not in block and "q2" not in block


class TestHistoryAppend:
    def test_turn_is_recorded_with_question_sql_and_answer(self):
        state = {"question": "Who works in Bangalore?", "sql_query": "SELECT 1", "history": []}

        history = _append_turn(state, "Two people.")

        assert history == [
            {
                "question": "Who works in Bangalore?",
                "sql_query": "SELECT 1",
                "answer": "Two people.",
            }
        ]

    def test_append_does_not_mutate_the_previous_history(self):
        """State updates have to be new objects.

        LangGraph reuses checkpointed state; mutating in place is the kind of bug
        that surfaces when a turn rolls back — by which point the history has
        already been written.
        """
        original = [{"question": "q1", "sql_query": "s1", "answer": "a1"}]
        state = {"question": "q2", "sql_query": "s2", "history": original}

        new = _append_turn(state, "a2")

        assert len(original) == 1, "the previous list must not be touched"
        assert len(new) == 2

    def test_history_grows_by_exactly_one_per_turn(self):
        """`generate_sql` runs again inside the retry loop.

        That is why only `synthesize_and_validate` writes history — the last node
        in the graph, which runs exactly once per turn. Appending in any middle
        node would make a retry-heavy turn produce three entries.
        """
        state = {"question": "q", "sql_query": "s", "history": []}
        after_one = _append_turn(state, "a")
        after_two = _append_turn({**state, "history": after_one}, "a2")

        assert len(after_one) == 1
        assert len(after_two) == 2


class TestPerTurnReset:
    """The most important invariant — and the one the checkpointer created.

    Before memory, every invocation started from empty state, so the question did
    not arise. Now state survives between turns, and the input dict from
    `run_agent` is **merged over** the checkpointed state. Any key missing from
    that dict carries over from the previous turn.
    """

    def _turn_input_keys(self):
        """Mirrors the per-turn dict that `run_agent` builds."""
        return {
            "question",
            "sql_query",
            "query_result",
            "error",
            "retry_count",
            "final_answer",
            "logs",
        }

    def test_every_per_turn_field_is_reset(self):
        """If `retry_count` carried over, the next turn would give up immediately.

        If the previous turn spent 3 retries and `retry_count` is not reset, the
        very first error on the next turn sends `should_retry` to `give_up` — the
        self-healing loop dies silently. The trace would also show the previous
        question’s lines.
        """
        import inspect

        source = inspect.getsource(graph_mod.run_agent)
        for field in self._turn_input_keys():
            assert f'"{field}"' in source, f"{field} is missing from the per-turn reset"

    def test_history_is_not_reset(self):
        """`history` *must* carry over — that is the entire feature."""
        import inspect

        source = inspect.getsource(graph_mod.run_agent)
        # The stateless path sets history to empty; the memory path must leave it
        # out so it comes from the checkpoint.
        assert 'turn_input["history"] = []' in source
        assert "if checkpointer is None:" in source


class TestStatelessFallback:
    def test_no_thread_id_means_no_checkpointer(self, monkeypatch):
        """Without a `thread_id` the behaviour must be exactly what it was.

        The eval harness calls `run_agent(question)`. If that silently picked up
        memory, the answer to one eval question would change the score of the next
        — and measurement was the entire point of the eval.
        """
        called = []
        monkeypatch.setattr(
            graph_mod, "get_checkpointer", lambda: called.append(1) or "saver"
        )
        captured = {}

        class FakeGraph:
            def invoke(self, state, config=None):
                captured["state"] = state
                captured["config"] = config
                return {**state, "final_answer": "ok"}

        monkeypatch.setattr(graph_mod, "_get_graph", lambda cp: FakeGraph())

        graph_mod.run_agent("who works in Bangalore?")

        assert called == [], "the checkpointer must not be touched without a thread_id"
        assert captured["config"] is None
        assert captured["state"]["history"] == []

    def test_thread_id_is_passed_through_as_the_config_key(self, monkeypatch):
        monkeypatch.setattr(graph_mod, "get_checkpointer", lambda: "saver")
        captured = {}

        class FakeGraph:
            def invoke(self, state, config=None):
                captured["state"] = state
                captured["config"] = config
                return {**state, "final_answer": "ok"}

        monkeypatch.setattr(graph_mod, "_get_graph", lambda cp: FakeGraph())

        graph_mod.run_agent("and how many of them are in Bangalore?", thread_id="t-42")

        assert captured["config"] == {"configurable": {"thread_id": "t-42"}}
        # History must not be in the input — it has to come from the checkpoint.
        assert "history" not in captured["state"]
