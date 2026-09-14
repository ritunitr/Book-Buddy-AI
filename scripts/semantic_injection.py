"""
Semantic Profile Injection for Personalized Recommendations

Takes user's learned semantic profile (interests, preferences, dislikes) and
injects it into the recommendation prompt to personalize results.

This is where "semantic memory" becomes actionable - the distilled facts about
the user guide the recommendation engine to pick books that actually match their taste.
"""

from typing import Optional, Dict, Any
import db_helpers


def build_semantic_context(user_email: str) -> str:
    """
    Build a semantic context string from user's profile.
    This gets injected into the recommendation prompt.

    Returns:
        Formatted context string for Claude (empty string if no profile yet)
    """
    user_id = db_helpers.get_or_create_user(user_email)
    profile = db_helpers.get_user_profile(user_id)

    if not profile:
        return ""

    semantic = profile.get("semantic_json", {})
    procedural = profile.get("procedural_json", {})

    # If profile is empty, return empty context
    if not semantic and not procedural:
        return ""

    # Build context string
    lines = []

    # Semantic preferences
    if semantic.get("interests"):
        lines.append(f"Interests: {', '.join(semantic['interests'])}")

    if semantic.get("preferences"):
        prefs = semantic["preferences"]
        pref_list = [f"{k}: {v}" for k, v in prefs.items()]
        lines.append(f"Preferences: {', '.join(pref_list)}")

    if semantic.get("dislikes"):
        lines.append(f"Dislikes: {', '.join(semantic['dislikes'])}")

    # Procedural patterns
    if procedural.get("reading_velocity"):
        lines.append(f"Reading pace: {procedural['reading_velocity']} books/month")

    if procedural.get("series_preference") is not None:
        pref = "prefers series" if procedural["series_preference"] else "prefers standalones"
        lines.append(f"Series preference: {pref}")

    if procedural.get("completion_rate"):
        rate = int(procedural["completion_rate"] * 100)
        lines.append(f"Completion rate: {rate}% of started books finished")

    if procedural.get("preferred_length"):
        lines.append(f"Preferred book length: {procedural['preferred_length']}")

    if not lines:
        return ""

    context = "User Profile:\n" + "\n".join(f"  - {line}" for line in lines)
    return context


def build_unread_filter_context(user_email: str, candidate_books: list) -> tuple:
    """
    Build unread filter and return books + context about what was filtered.

    Returns:
        (filtered_books, filter_context_str)
        - filtered_books: Books user hasn't read yet
        - filter_context_str: Summary of how many books were filtered
    """
    user_id = db_helpers.get_or_create_user(user_email)
    unread_book_ids = set(db_helpers.get_unread_books(user_id))

    if not unread_book_ids:
        # User has no reading history yet, return all candidates
        return candidate_books, ""

    # Filter candidates to only unread books
    filtered_books = [
        book for book in candidate_books
        if book.get("book_id") and book["book_id"] not in unread_book_ids
    ]

    filtered_count = len(candidate_books) - len(filtered_books)

    if filtered_count == 0:
        return filtered_books, ""

    context = f"(Filtered out {filtered_count} books you've already read)"
    return filtered_books, context


def get_personalization_prompt_section(user_email: str) -> str:
    """
    Get the complete personalization section to inject into recommendation prompt.

    This becomes part of the system prompt or user message to guide Claude's selection.
    """
    semantic_context = build_semantic_context(user_email)

    if not semantic_context:
        return ""

    prompt_section = f"""
{semantic_context}

IMPORTANT: Use this profile to select recommendations that align with their taste.
- Prioritize books matching their interests
- Avoid books in their dislikes list
- Consider their preferences (tone, depth, pacing)
"""
    return prompt_section


# ============================================================================
# Integration with Recommendation Flow
# ============================================================================

def personalize_recommendation_prompt(
    original_query: str,
    user_email: Optional[str] = None
) -> str:
    """
    Enhance the recommendation query with user's semantic profile.

    If user_email is provided, injects their learned preferences into the query.
    Otherwise, returns original query unchanged (graceful fallback).
    """
    if not user_email:
        return original_query

    personalization = get_personalization_prompt_section(user_email)

    if not personalization:
        return original_query

    return f"{original_query}\n{personalization}"


def filter_candidates_by_profile(
    user_email: str,
    candidate_books: list
) -> tuple:
    """
    Filter candidate books by user's profile.

    Currently filters:
    1. Books user has already read

    Returns:
        (filtered_books, metadata)
        - filtered_books: Recommended books (excluding already-read)
        - metadata: {
              "original_count": int,
              "filtered_out_count": int,
              "final_count": int,
              "filter_context": str
          }
    """
    original_count = len(candidate_books)

    # Filter unread books
    filtered, filter_msg = build_unread_filter_context(user_email, candidate_books)

    metadata = {
        "original_count": original_count,
        "filtered_out_count": original_count - len(filtered),
        "final_count": len(filtered),
        "filter_context": filter_msg
    }

    return filtered, metadata
