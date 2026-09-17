"""
Semantic Profile Injection using User Preferences (Fact).

Injects user's distilled preference fact into recommendation prompts
to personalize results based on their reading history.
"""

from typing import Optional
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
    Hard filter: Remove books that user explicitly disliked.

    Gets disliked books from interaction_log and removes exact title matches
    from candidates before recommendation LLM sees them.

    Returns:
        (filtered_books, metadata)
    """
    if not candidate_books:
        return [], {
            "original_count": 0,
            "filtered_out_count": 0,
            "final_count": 0,
            "filter_type": "disliked_books"
        }

    # Get user's disliked books from interaction history
    user_id = db_helpers.get_or_create_user(user_email)
    feedback = db_helpers.get_all_feedback(user_id)
    disliked_books = set(b.lower().strip() for b in feedback.get("disliked_books", []))

    if not disliked_books:
        return candidate_books, {
            "original_count": len(candidate_books),
            "filtered_out_count": 0,
            "final_count": len(candidate_books),
            "filter_type": "disliked_books"
        }

    # Filter out books matching disliked titles
    filtered = []
    filtered_out_count = 0

    for book in candidate_books:
        title = book.get("title", "").lower().strip()
        if title not in disliked_books:
            filtered.append(book)
        else:
            filtered_out_count += 1

    metadata = {
        "original_count": len(candidate_books),
        "filtered_out_count": filtered_out_count,
        "final_count": len(filtered),
        "filter_type": "disliked_books"
    }

    return filtered, metadata
