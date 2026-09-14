"""
Fetch Candidate Books v2: Uses the new agentic retrieval orchestrator

Instead of calling run_retrieval() from retrieval_graph.py (which has
hard-coded tier1/tier2 logic), this version uses run_retrieval_agentic()
from retrieval_graph_v2.py, which lets Claude decide the search strategy.

This is the only file that needs to change in the orchestration layer.
"""

try:
    from retrieval_graph_v2 import run_retrieval_agentic
except ImportError:
    from .retrieval_graph_v2 import run_retrieval_agentic


def fetch_candidate_books_agentic(intent: dict) -> dict:
    """
    Fetch candidate books using the new Claude-driven agentic orchestrator.

    Claude autonomously decides which search tools to call based on the user's
    intent and the results it sees from each search.

    Args:
        intent: Output from intent_extractor.extract_intent()

    Returns:
        {
            "request_type": "general" | "exploration" | "progression",
            "books": [...candidates...],
            "search_history": [...decisions Claude made...],
            "attempts_used": int
        }
    """
    original_query = intent.get("original_query", "")
    recommendation_type = intent.get("recommendation_type", "general")

    # Use the new agentic retrieval
    result = run_retrieval_agentic(
        original_query=original_query,
        intent_data=intent
    )

    return {
        "request_type": recommendation_type,
        "books": result["books"],
        "search_history": result["search_history"],
        "attempts_used": result["attempts_used"],
        "total_results": len(result["books"]),
    }


# Note: For progression queries, we'd still call this per level:
# for level in levels:
#     candidates = fetch_candidate_books_agentic(level_intent)
#     # ... rest of level handling
