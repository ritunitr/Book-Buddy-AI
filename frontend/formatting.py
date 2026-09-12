"""
Formatting

Pure functions that turn a backend /recommend JSON response into a Markdown
string for display in Gradio. No recommendation logic lives here - this
module only re-shapes data the backend already decided on (which books,
which order, what to say about each one). It never calls Google Books,
Claude, or any ranking/filtering code.
"""

import re

# Friendly age-range labels for the "Selection Criteria" line. Static
# presentation mapping only - not a recommendation decision.
_AGE_LABELS = {
    "toddler": "Age 1–3",
    "preschool": "Age 3–5",
    "early_reader": "Age 5–7",
    "middle_grade": "Age 8–12",
    "young_adult": "Age 13–17",
    "adult": "Adult",
}


def _format_book(rec: dict, index: int) -> str:
    """Title + author, then a single description line. The backend's
    separate "notes" field is intentionally not shown - one line of context
    per book reads cleaner than two."""
    title = rec.get("title", "Unknown title")
    authors = rec.get("authors") or []
    author_str = ", ".join(authors) if authors else "Unknown author"
    why = rec.get("why_recommended", "")

    lines = [f"**{index}. {title}** — {author_str}"]
    if why:
        lines.append(f"   {why}")
    # "  \n" (trailing double-space) is a Markdown line break within the same
    # paragraph - tighter than "\n\n", which renders as a full blank line.
    return "  \n".join(lines)


def _format_flat_recommendations(recommendations: list) -> str:
    if not recommendations:
        return "_No recommendations found for this query._"
    return "\n\n".join(_format_book(rec, i) for i, rec in enumerate(recommendations, 1))


def _humanize(value: str) -> str:
    """Turn a backend enum-style value ('young_adult') into readable text."""
    if not value or value == "not_specified":
        return ""
    return value.replace("_", " ")


def _age_label(audience_range: str) -> str:
    return _AGE_LABELS.get(audience_range, "")


def _theme_tags_from_search_query(search_query: str, max_tags: int = 3) -> list:
    """
    Best-effort extraction of readable theme tags from the general query's
    raw search_query string (e.g. 'dragons subject:"fiction" |
    "fantasy adventure" subject:"fiction" | intitle:"The Hobbit"').

    Only available for general queries - progression levels don't expose a
    search_query in the API response, so this has nothing to work with there
    (see _selection_criteria_level, which falls back to age-only).

    This is a display cleanup of a string the backend already returns, not
    new recommendation logic: drops the subject:"..." filter and intitle:
    canonical-title clauses (not themes), keeping only the topic keywords.
    """
    if not search_query:
        return []

    tags = []
    for clause in search_query.split(" | "):
        clause = clause.strip()
        if clause.startswith("intitle:") or clause.startswith("inauthor:"):
            continue
        clause = re.sub(r'subject:"[^"]*"', "", clause).strip().strip('"').strip()
        if clause and clause.title() not in tags:
            tags.append(clause.title())

    return tags[:max_tags]


def _selection_criteria_general(response: dict) -> str:
    age = _age_label(response.get("audience_range", ""))
    tags = _theme_tags_from_search_query(response.get("search_query", ""))
    parts = ([age] if age else []) + tags
    return " | ".join(parts)


def _selection_criteria_level(level: dict) -> str:
    """
    Progression levels don't carry a search_query (or any theme/keyword
    field) in the API response, so unlike the general path, only the age
    label is available here - no thematic tags.
    """
    return _age_label(level.get("audience_range", ""))


def _first_sentence(text: str) -> str:
    """
    overall_notes is a full multi-sentence paragraph (explaining inclusions/
    exclusions), not the short one-line framing the italic "targeting" line
    is meant to be. Trim to just the first sentence for that spot rather
    than dumping the whole paragraph up top.
    """
    if not text:
        return ""
    match = re.search(r"^.*?[.!?](?=\s|$)", text.strip())
    return match.group(0) if match else text.strip()


def _opening_statement_general(response: dict) -> str:
    """A short conversational line before the list, giving context on what
    was searched and why these books were picked."""
    recs = response.get("recommendations", [])
    n = len(recs)
    if n == 0:
        return ""

    audience = _humanize(response.get("audience_range", ""))
    candidates_found = response.get("candidates_found", 0)

    audience_phrase = f" for a {audience} reader" if audience else ""
    found_phrase = f", picked from {candidates_found} books I looked at" if candidates_found else ""

    return f"Based on what you shared, here {'is' if n == 1 else 'are'} {n} book{'' if n == 1 else 's'} I'd recommend{audience_phrase}{found_phrase}:"


def _opening_statement_progression(response: dict) -> str:
    """A short conversational line before the level-by-level list."""
    levels = response.get("levels", [])
    n = len(levels)
    if n == 0:
        return ""

    age_context = _humanize(response.get("age_context", ""))
    age_phrase = f", starting around {age_context}" if age_context else ""

    return f"Here's a {n}-step reading progression{age_phrase} — each level builds on the one before it as your reader grows:"


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

    parts = []

    opening = _opening_statement_general(response)
    if opening:
        parts.append(opening)

    criteria = _selection_criteria_general(response)
    if criteria:
        parts.append(f"**Selection Criteria:** {criteria}")

    # overall_notes is the only Claude-authored descriptive text available
    # for a general query, so it doubles as the italic "targeting" line -
    # trimmed to one sentence to match that line's short, framing role,
    # shown once up top rather than repeated in full as a trailing note.
    opening_note = _first_sentence(overall_notes)
    if opening_note:
        parts.append(f"*{opening_note}*")

    parts.append(_format_flat_recommendations(recommendations))

    return "\n\n".join(parts)


def _format_progression(response: dict) -> str:
    levels = response.get("levels", [])

    parts = []
    opening = _opening_statement_progression(response)
    if opening:
        parts.append(opening)

    if not levels:
        parts.append("_No progression levels found for this query._")
        return "\n\n".join(parts)

    total = len(levels)
    for level in levels:
        level_num = level.get("level", "?")
        description = level.get("description", "")
        audience = _humanize(level.get("audience_range", ""))
        recs = level.get("recommendations", [])
        n = len(recs)
        candidates_found = level.get("candidates_found", 0)

        parts.append("---")
        parts.append(f"### 📖 Step {level_num} of {total}")

        if n:
            audience_phrase = f" for a {audience} reader" if audience else ""
            found_phrase = f", picked from {candidates_found} books I looked at" if candidates_found else ""
            parts.append(
                f"Here {'is' if n == 1 else 'are'} {n} book{'' if n == 1 else 's'} "
                f"I'd recommend{audience_phrase}{found_phrase}:"
            )

        criteria = _selection_criteria_level(level)
        if criteria:
            parts.append(f"**Selection Criteria:** {criteria}")

        if description:
            parts.append(f"*{description}*")

        parts.append(_format_flat_recommendations(recs))

        level_notes = level.get("notes", "")
        if level_notes:
            parts.append(f"> {level_notes}")

    return "\n\n".join(parts)


def format_error(message: str) -> str:
    """Render a user-facing error message as Markdown."""
    return f"⚠️ {message}"
