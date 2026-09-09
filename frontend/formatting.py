"""
Formatting

Pure functions that turn a backend /recommend JSON response into a Markdown
string for display in Gradio. No recommendation logic lives here - this
module only re-shapes data the backend already decided on (which books,
which order, what to say about each one). It never calls Google Books,
Claude, or any ranking/filtering code.
"""


def _format_book(rec: dict, index: int) -> str:
    title = rec.get("title", "Unknown title")
    authors = rec.get("authors") or []
    author_str = ", ".join(authors) if authors else "Unknown author"
    why = rec.get("why_recommended", "")
    notes = rec.get("notes", "")

    lines = [f"**{index}. {title}** — {author_str}"]
    if why:
        lines.append(f"   {why}")
    if notes:
        lines.append(f"   *{notes}*")
    return "\n\n".join(lines)


def _format_flat_recommendations(recommendations: list) -> str:
    if not recommendations:
        return "_No recommendations found for this query._"
    return "\n\n".join(_format_book(rec, i) for i, rec in enumerate(recommendations, 1))


def format_recommendations(response: dict) -> str:
    """
    Render a backend /recommend response as Markdown.

    Handles both response shapes:
    - general / exploration: a single flat "recommendations" list
    - progression: a "levels" array, each with its own "recommendations" list

    Args:
        response: The dict returned by api_client.get_recommendations().

    Returns:
        Markdown-formatted string ready to display in a Gradio Markdown component.
    """
    request_type = response.get("request_type", "general")

    if request_type == "progression":
        return _format_progression(response)
    return _format_general(response)


def _format_general(response: dict) -> str:
    recommendations = response.get("recommendations", [])
    overall_notes = response.get("overall_notes", "")

    parts = [_format_flat_recommendations(recommendations)]
    if overall_notes:
        parts.append(f"---\n\n**Overall notes:** {overall_notes}")

    return "\n\n".join(parts)


def _format_progression(response: dict) -> str:
    levels = response.get("levels", [])
    age_context = response.get("age_context", "")

    parts = []
    if age_context:
        parts.append(f"**Age context:** {age_context}")

    if not levels:
        parts.append("_No progression levels found for this query._")
        return "\n\n".join(parts)

    for level in levels:
        level_num = level.get("level", "?")
        description = level.get("description", "")
        audience_range = level.get("audience_range", "")

        header = f"## Level {level_num}: {description}"
        if audience_range:
            header += f" _{audience_range}_"
        parts.append(header)

        recs = level.get("recommendations", [])
        parts.append(_format_flat_recommendations(recs))

        level_notes = level.get("notes", "")
        if level_notes:
            parts.append(f"*{level_notes}*")

    return "\n\n".join(parts)


def format_error(message: str) -> str:
    """Render a user-facing error message as Markdown."""
    return f"⚠️ {message}"
