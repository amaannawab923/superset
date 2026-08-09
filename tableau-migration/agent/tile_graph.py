"""Phase-1 per-tile subgraph (LangGraph).

The heart of Migration Buddy (architecture §3): for one tile,
    translate -> data-oracle -> execute -> verify(numeric + structural)
        -> GREEN                          (both checks pass; freeze SQL)
        -> Fix (LLM) -> execute           (mismatch, retries left, LLM available)
        -> flag YELLOW/RED                (unverifiable / mismatch exhausted; never fake)

Deterministic tools own every number; the LLM only does judgment in `fix`, and is
guarded so a missing API key degrades to a flag rather than a fake-green.
"""

from typing import Any, Optional, TypedDict

from langgraph.graph import StateGraph, START, END

from . import tools

MAX_RETRIES = 2


class TileState(TypedDict, total=False):
    tile: dict
    oracle: Optional[dict]
    sql: dict
    got: dict
    query: str
    numeric_ok: bool
    structural_ok: bool
    diffs: dict
    struct: dict
    retries: int
    verdict: str          # GREEN | YELLOW | RED
    reason: str
    fix_note: str         # what the LLM changed, if anything


def build_tile_graph(primary: Any, llm=None):
    """Compile a per-tile graph. `primary` is the .hyper frame (kept out of state).

    `llm` is an optional callable (spec, diffs) -> revised_spec for the Fix node;
    when None, a mismatch is flagged instead of retried (flag, don't fake).
    """

    def translate(state: TileState) -> TileState:
        return {"sql": tools.translate_sql(state["tile"]), "retries": state.get("retries", 0)}

    def oracle(state: TileState) -> TileState:
        return {"oracle": tools.data_oracle(state["tile"], primary)}

    def execute(state: TileState) -> TileState:
        got, query = tools.execute_sql(state["sql"], primary)
        return {"got": got, "query": query}

    def verify(state: TileState) -> TileState:
        oc = state.get("oracle")
        got = state.get("got", {})
        structural_ok, struct = tools.structural_diff(state["tile"], state["sql"])
        if "__error__" in got:
            return {"numeric_ok": False, "structural_ok": structural_ok, "struct": struct,
                    "exec_error": got["__error__"]}
        numeric_ok, diffs = tools.numeric_diff(oc, got)
        return {
            "numeric_ok": numeric_ok,
            "structural_ok": structural_ok,
            "diffs": diffs,
            "struct": struct,
        }

    def fix(state: TileState) -> TileState:
        # LLM judgment node: read the diff/error, propose a revised translation.
        revised = llm(state["sql"], state.get("diffs", {}), state["tile"])
        return {"sql": revised, "retries": state.get("retries", 0) + 1,
                "fix_note": "LLM revised translation from numeric diff"}

    def finalize_green(state: TileState) -> TileState:
        return {"verdict": "GREEN", "reason": "numeric + structural match; SQL frozen"}

    def flag(state: TileState) -> TileState:
        # Never fake: pick the honest colour + reason.
        if not state.get("oracle"):
            return {"verdict": "YELLOW",
                    "reason": f'unverified by data-oracle ({state["tile"]["reason"]}); '
                              "needs Tier-1 rendered oracle or human"}
        if state.get("exec_error"):
            return {"verdict": "RED",
                    "reason": f'could not execute translated SQL: {state["exec_error"]}'}
        if not state.get("structural_ok"):
            return {"verdict": "RED",
                    "reason": f'structural mismatch: shelf {state["struct"]["shelf"]} '
                              f'!= built {state["struct"]["built"]}'}
        return {"verdict": "RED", "reason": "numeric mismatch after retries"}

    def after_oracle(state: TileState) -> str:
        # Skip execution for tiles Tier-0 can't verify; flag them honestly.
        return "execute" if state.get("oracle") else "flag"

    def route(state: TileState) -> str:
        if state.get("numeric_ok") and state.get("structural_ok"):
            return "finalize_green"
        can_retry = state.get("retries", 0) < MAX_RETRIES and llm is not None \
            and state.get("oracle") and not state.get("numeric_ok")
        return "fix" if can_retry else "flag"

    g = StateGraph(TileState)
    for name, fn in [
        ("translate", translate), ("oracle", oracle), ("execute", execute),
        ("verify", verify), ("fix", fix), ("finalize_green", finalize_green), ("flag", flag),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "translate")
    g.add_edge("translate", "oracle")
    g.add_conditional_edges("oracle", after_oracle, {"execute": "execute", "flag": "flag"})
    g.add_edge("execute", "verify")
    g.add_conditional_edges("verify", route,
                            {"finalize_green": "finalize_green", "fix": "fix", "flag": "flag"})
    g.add_edge("fix", "execute")          # revised SQL re-executed and re-verified
    g.add_edge("finalize_green", END)
    g.add_edge("flag", END)
    return g.compile()
