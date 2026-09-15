"""
Semantic Profile Injection using User Preferences.

Injects user's explicit preferences (liked/disliked books, authors, genres)
into the recommendation prompt to personalize results.
"""

from typing import Optional, Dict, Any
import db_helpers


def build_preference_context(user_email: str) -> str:
    """
    Build preference context string from user's settings.
    Returns empty string if no preferences set.
    """
    user_id = db_helpers.get_or_create_user(user_email)
    prefs = db_helpers.get_user_preferences(user_id)

    lines = []

    # Liked preferences
    if prefs.get("liked_genres"):
        lines.append(f"Interested in: {', '.join(prefs['liked_genres'])}")

    if prefs.get("liked_authors"):
        lines.append(f"Favorite authors: {', '.join(prefs['liked_authors'])}")

    if prefs.get("liked_books"):
        lines.append(f"Books they enjoyed: {', '.join(prefs['liked_books'][:3])}")

    # Dislikes
    if prefs.get("disliked_genres"):
        lines.append(f"Avoid: {', '.join(prefs['disliked_genres'])}")

    if prefs.get("disliked_authors"):
        lines.append(f"Not interested in: {', '.join(prefs['disliked_authors'])}")

    if not lines:
        return ""

    return "User Preferences:\n" + "\n".join(f"  • {line}" for line in lines)


def personalize_recommendation_prompt(
    original_query: str,
    user_email: Optional[str] = None
) -> str:
    """
    Enhance recommendation query with user's preferences.
    Falls back to original query if no preferences exist.
    """
    if not user_email:
        return original_query

    context = build_preference_context(user_email)
    if not context:
        return original_query

    prompt_section = f"""
{context}

Consider these preferences when selecting recommendations.
- Prioritize books matching their interests
- Avoid books in their dislike list
- Look for similar authors or genres they enjoy
"""
    return f"{original_query}\n{prompt_section}"


def filter_candidates_by_preferences(
    user_email: str,
    candidate_books: list
) -> tuple:
    """
    Filter candidate books by user's preferences.
    Removes books by disliked authors or in disliked genres (if extractable).

    Returns:
        (filtered_books, metadata)
    """
    user_id = db_helpers.get_or_create_user(user_email)
    prefs = db_helpers.get_user_preferences(user_id)

    disliked_books = set(prefs.get("disliked_books", []) or [])

    # Filter out explicitly disliked books
    filtered = [b for b in candidate_books if b.get("title") not in disliked_books]

    metadata = {
        "original_count": len(candidate_books),
        "filtered_out_count": len(candidate_books) - len(filtered),
        "final_count": len(filtered)
    }

    return filtered, metadata
