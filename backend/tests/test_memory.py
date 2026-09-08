"""Conversation memory ke seams — bina ek bhi LLM ya Postgres call ke.

**Yahan asli model kyun nahi:** ye tests memory ki *semantics* ka test hain, model
ki quality ka nahi. Asli sawaal ye hai — kaunsi state turns ke beech carry hoti
hai aur kaunsi reset. Wo poora sawaal LLM ke bahar hai, aur Gemini ka free tier
20 requests/day deta hai, to us quota ko un tests pe kharch karna jo usse kuch
seekh hi nahi rahe, seedha nuksan hai.

Ek asli multi-turn conversation alag se, haath se verify hui hai — wo
`docs/CODE_NOTES.md` me likhi hai.
"""

import app.config as config_mod
import app.graph as graph_mod
import app.nodes as nodes_mod
from app.nodes import _append_turn, _format_history


class TestHistoryFormatting:
    def test_empty_history_adds_nothing_to_the_prompt(self):
        """Pehle turn pe prompt bilkul pehle jaisa rehna chahiye.

        Khaali "Earlier in this conversation:" heading bhejna model ko ek aisa
        context suggest karta hai jo hai hi nahi.
        """
        assert _format_history([]) == ""

    def test_history_carries_sql_not_just_the_answer(self):
        """SQL hi wo cheez hai jo reference resolve karti hai.

        "Which department has the highest average salary?" ka angrezi jawab
        department ka naam bol bhi sakta hai aur nahi bhi; us turn ka SQL
        (`ORDER BY AVG(salary) DESC LIMIT 1`) hamesha batata hai ki "them"
        kiski baat hai.
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
        """Poori history bhejna tokens aur dhyaan dono kharch karta hai."""
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
        """State updates naye objects hone chahiye.

        LangGraph checkpointed state ko reuse karta hai; jagah pe mutate karna wo
        bug hai jo tab dikhta hai jab ek turn rollback ho — tab tak history pehle
        hi likhi ja chuki hoti hai.
        """
        original = [{"question": "q1", "sql_query": "s1", "answer": "a1"}]
        state = {"question": "q2", "sql_query": "s2", "history": original}

        new = _append_turn(state, "a2")

        assert len(original) == 1, "purani list chhedni nahi chahiye"
        assert len(new) == 2

    def test_history_grows_by_exactly_one_per_turn(self):
        """Retry loop me `generate_sql` dobara chalta hai.

        Isiliye history sirf `synthesize_and_validate` likhta hai — graph ka
        aakhri node, jo har turn me theek ek baar chalta hai. Beech ke kisi node
        me append karne se ek retry-heavy turn teen entries banata.
        """
        state = {"question": "q", "sql_query": "s", "history": []}
        after_one = _append_turn(state, "a")
        after_two = _append_turn({**state, "history": after_one}, "a2")

        assert len(after_one) == 1
        assert len(after_two) == 2


class TestPerTurnReset:
    """Sabse zaroori invariant — aur wahi jo checkpointer ne naya banaya.

    Memory se pehle har invocation khaali state se shuru hoti thi, to ye sawaal
    tha hi nahi. Ab state turns ke beech survive karti hai, aur `run_agent` ka
    input dict checkpointed state ke **upar merge** hota hai. Jo key us dict me
    nahi hogi, wo pichhle turn se carry ho jaayegi.
    """

    def _turn_input_keys(self):
        """`run_agent` jo per-turn dict banata hai, wahi yahan mirror hai."""
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
        """`retry_count` carry ho jaye to agla turn turant give-up karega.

        Pichhle turn ne agar 3 retries kharch ki, aur `retry_count` reset na ho,
        to agle turn ka pehla hi error `should_retry` ko `give_up` de dega —
        self-healing loop chup-chaap mar jaata hai. Trace me bhi pichhle sawaal
        ki lines dikhengi.
        """
        import inspect

        source = inspect.getsource(graph_mod.run_agent)
        for field in self._turn_input_keys():
            assert f'"{field}"' in source, f"{field} per-turn reset se chhoot gaya"

    def test_history_is_not_reset(self):
        """`history` ko carry hona *chahiye* — yahi poora feature hai."""
        import inspect

        source = inspect.getsource(graph_mod.run_agent)
        # Stateless path me history khaali set hoti hai; memory path me use
        # chhodna zaroori hai taaki checkpoint se aaye.
        assert 'turn_input["history"] = []' in source
        assert "if checkpointer is None:" in source


class TestStatelessFallback:
    def test_no_thread_id_means_no_checkpointer(self, monkeypatch):
        """Bina `thread_id` ke behaviour bilkul pehle jaisa rehna chahiye.

        Eval harness `run_agent(question)` call karta hai. Agar wo chup-chaap
        memory le lene lage, to pehle eval question ka jawab agle ke score ko
        badal dega — aur eval ka poora point hi measurement tha.
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

        assert called == [], "thread_id ke bina checkpointer chhuna nahi chahiye"
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
        # History input me nahi honi chahiye — wo checkpoint se aani chahiye.
        assert "history" not in captured["state"]
