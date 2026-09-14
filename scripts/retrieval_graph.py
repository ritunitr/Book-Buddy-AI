"""
Retrieval Graph (Phase 2: restricted ReAct / agentic retrieval)

A small, bounded LangGraph that wraps a single search-and-check unit with
up to two broaden-and-retry attempts when the result is bad. Used once per
general/exploration query, and once per level for progression queries (only
the failed level retries, not the whole progression).

"Bad" is a mechanical, code-only check (candidate count), never another LLM
call - see _check_result. Retry has two tiers:
  - Tier 1 (cheap, no LLM call): drop the subject: filter, re-search with the
    same themes/known_titles. subject: is a relevance BOOST, not a hard
    filter, so removing it only adds candidates, never removes good ones.
  - Tier 2 (one LLM call, only if tier 1 still bad): ask Claude to propose a
    genuinely broader search given the full history of what's been tried.
After tier 2, the graph stops regardless of outcome and returns whatever it
has - this is "restricted", not open-ended agentic retrying.
"""

from typing import TypedDict
from langgraph.graph import StateGraph, END

try:
    from google_books_client import (
        _search_multi_query,
        _search_known_titles,
        _filter_books_by_intent,
        _is_likely_non_book,
    )
    from intent_extractor import broaden_search_with_llm
except ImportError:
    from .google_books_client import (
        _search_multi_query,
        _search_known_titles,
        _filter_books_by_intent,
        _is_likely_non_book,
    )
    from .intent_extractor import broaden_search_with_llm

# Below this many candidates, a search is considered "bad" and worth
# retrying. Chosen well below what Phase 0's healthy queries produced
# (40-90 candidates typical) but above zero, to catch thin pools before
# they reach the recommender, not just outright empty ones.
MIN_CANDIDATES = 20

# Early stopping threshold: if we have this many candidates, stop retrying
# (even if we haven't hit MAX_ATTEMPTS). Reduces latency by avoiding
# unnecessary queries when we already have enough books.
ENOUGH_CANDIDATES = 30

MAX_ATTEMPTS = 2  # tier 1 + tier 2, then stop regardless


class RetrievalState(TypedDict):
    # Fixed for the life of this graph invocation
    original_query: str
    is_exploration: bool
    audience_range: str
    genre: str
    format_type: str

    # Mutable search params - what changes across retries
    themes: list          # flat mode: topic keywords; exploration mode after
                           # tier 2 also becomes flat (see broaden_tier2)
    exploration_clusters: list  # only used while is_exploration and attempt==0
    known_titles: list
    subject: str
    format_marker: str

    # Retry bookkeeping
    attempt: int
    debug_log: list

    # Results
    books: list
    search_queries_used: list
    is_bad: bool
    bad_reason: str


def _merge_and_filter(semantic_books: list, sub_queries: list, known_titles: list, intent_like: dict) -> tuple:
    canonical_books = _search_known_titles(known_titles)
    canonical_queries = [f'intitle:"{t.split(" by ")[0].strip()}"' for t in known_titles]

    semantic_filtered = _filter_books_by_intent(semantic_books, intent_like)
    canonical_filtered = [b for b in canonical_books if not _is_likely_non_book(b)]

    merged = {}
    for book in semantic_filtered:
        merged[book.get("title", "Unknown")] = book
    for book in canonical_filtered:
        merged[book.get("title", "Unknown")] = book

    return list(merged.values()), sub_queries + canonical_queries


def _search_node(state: RetrievalState) -> dict:
    intent_like = {"genre": state["genre"], "format": state["format_type"]}

    if state["is_exploration"] and state["attempt"] == 0:
        semantic_books, sub_queries = _search_multi_query(
            state["exploration_clusters"],
            subject=state["subject"],
            format_marker=state["format_marker"],
            tag_clusters=True,
        )
    else:
        theme_clusters = [[t] for t in state["themes"]]
        semantic_books, sub_queries = _search_multi_query(
            theme_clusters,
            subject=state["subject"],
            format_marker=state["format_marker"],
        )

    books, queries_used = _merge_and_filter(semantic_books, sub_queries, state["known_titles"], intent_like)

    return {"books": books, "search_queries_used": queries_used}


def _check_result_node(state: RetrievalState) -> dict:
    n = len(state["books"])

    # Early stopping: if we have enough candidates, stop retrying
    if n >= ENOUGH_CANDIDATES:
        return {"is_bad": False, "bad_reason": ""}

    # Otherwise, check if we should retry
    if n == 0:
        return {"is_bad": True, "bad_reason": f"Zero candidates found (attempt {state['attempt']})"}
    if n < MIN_CANDIDATES:
        return {"is_bad": True, "bad_reason": f"Only {n} candidates found, below minimum {MIN_CANDIDATES} (attempt {state['attempt']})"}
    return {"is_bad": False, "bad_reason": ""}


def _broaden_tier1_node(state: RetrievalState) -> dict:
    log_entry = f"Tier 1: dropped subject filter (was {state['subject']!r}) and retried with same themes {state['themes'] or state['exploration_clusters']}"
    return {
        "subject": None,
        "attempt": 1,
        "debug_log": state["debug_log"] + [log_entry],
    }


def _broaden_tier2_node(state: RetrievalState) -> dict:
    # Flatten exploration clusters to a plain theme list for the broaden call -
    # by tier 2 (last resort), getting decent results matters more than
    # preserving the cluster-diversity structure.
    themes_tried = state["themes"] if state["themes"] else [kw for cluster in state["exploration_clusters"] for kw in cluster]

    result = broaden_search_with_llm(
        original_query=state["original_query"],
        themes_tried=themes_tried,
        known_titles_tried=state["known_titles"],
        bad_reason=state["bad_reason"],
    )

    log_entry = (
        f"Tier 2: LLM broaden given history (themes tried: {themes_tried}, "
        f"reason: {state['bad_reason']!r}) -> new themes {result['themes']}, "
        f"known_titles {result['known_titles']}"
    )

    return {
        "themes": result["themes"],
        "known_titles": result["known_titles"],
        "attempt": 2,
        "debug_log": state["debug_log"] + [log_entry],
    }


def _route_after_check(state: RetrievalState) -> str:
    if not state["is_bad"]:
        return "end"
    if state["attempt"] == 0:
        return "tier1"
    if state["attempt"] == 1:
        return "tier2"
    return "end"  # attempt == 2 (post-tier-2): stop regardless, best effort


def _build_graph():
    graph = StateGraph(RetrievalState)
    graph.add_node("search", _search_node)
    graph.add_node("check_result", _check_result_node)
    graph.add_node("broaden_tier1", _broaden_tier1_node)
    graph.add_node("broaden_tier2", _broaden_tier2_node)

    graph.set_entry_point("search")
    graph.add_edge("search", "check_result")
    graph.add_conditional_edges(
        "check_result",
        _route_after_check,
        {"tier1": "broaden_tier1", "tier2": "broaden_tier2", "end": END},
    )
    graph.add_edge("broaden_tier1", "search")
    graph.add_edge("broaden_tier2", "search")

    return graph.compile()


_RETRIEVAL_GRAPH = _build_graph()


def run_retrieval(
    original_query: str,
    themes: list,
    known_titles: list,
    subject: str,
    format_marker: str,
    genre: str,
    format_type: str,
    audience_range: str,
    exploration_clusters: list = None,
) -> dict:
    """
    Run the bounded search-check-broaden graph once.

    Pass exploration_clusters (list of keyword-lists) for exploration mode;
    leave it None and use `themes` (flat list) for general queries and single
    progression levels.

    Returns:
        {"books": [...], "search_queries_used": [...], "debug_log": [...],
         "attempts_used": int, "final_bad_reason": str or ""}
    """
    is_exploration = exploration_clusters is not None

    initial_state: RetrievalState = {
        "original_query": original_query,
        "is_exploration": is_exploration,
        "audience_range": audience_range,
        "genre": genre,
        "format_type": format_type,
        "themes": themes if not is_exploration else [],
        "exploration_clusters": exploration_clusters or [],
        "known_titles": known_titles,
        "subject": subject,
        "format_marker": format_marker,
        "attempt": 0,
        "debug_log": [],
        "books": [],
        "search_queries_used": [],
        "is_bad": False,
        "bad_reason": "",
    }

    final_state = _RETRIEVAL_GRAPH.invoke(initial_state)

    return {
        "books": final_state["books"],
        "search_queries_used": final_state["search_queries_used"],
        "debug_log": final_state["debug_log"],
        "attempts_used": final_state["attempt"],
        "final_bad_reason": final_state["bad_reason"] if final_state["is_bad"] else "",
    }
