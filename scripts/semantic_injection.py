"""
Semantic Profile Injection using User Preferences (Fact).

Injects user's distilled preference fact into recommendation prompts
to personalize results based on their reading history.
"""

from typing import Optional, Dict, Any
import db_helpers


def build_preference_context(user_email: str) -> str:
    """
    Build preference context from user's fact (semantic memory).
    Returns empty string if no fact exists yet.
    """
    user_id = db_helpers.get_or_create_user(user_email)
    prefs = db_helpers.get_user_preferences(user_id)

    fact = prefs.get("fact")
    if not fact:
        return ""

    return f"User Reading Profile:\n{fact}"


def personalize_recommendation_prompt(
    original_query: str,
    user_email: Optional[str] = None
) -> str:
    """
    Enhance recommendation query with user's preference fact.
    Falls back to original query if no fact exists.
    """
    if not user_email:
        return original_query

    context = build_preference_context(user_email)
    if not context:
        return original_query

    prompt_section = f"""
{context}

Consider this reading profile when selecting recommendations:
- Prioritize books that match their demonstrated interests
- Avoid books similar to ones they disliked
- Look for patterns in their liked books
"""
    return f"{original_query}\n{prompt_section}"


def filter_candidates_by_preferences(
    user_email: str,
    candidate_books: list
) -> tuple:
    """
    Filter candidate books based on user preferences.

    For now, returns all candidates since the fact is qualitative.
    In a more sophisticated system, could extract structured dislikes
    from the fact using Claude.

    Returns:
        (filtered_books, metadata)
    """
    # Currently, filtering is done via semantic injection in the prompt
    # The LLM uses the fact to naturally avoid disliked preferences

    metadata = {
        "original_count": len(candidate_books),
        "filtered_out_count": 0,
        "final_count": len(candidate_books),
        "filter_type": "semantic"
    }

    return candidate_books, metadata
