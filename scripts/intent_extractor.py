"""
Intent Extractor Module

Extracts structured recommendation intent from natural language queries.
Replaces basic theme extraction with comprehensive intent analysis.

Intent captures:
- What (themes/topics)
- Who (audience, age)
- How (format, genre, difficulty)
- Why (recommendation type)
- Constraints (what NOT to include)
"""

import json
import os
from dotenv import load_dotenv
from anthropic import Anthropic

try:
    from prompts import INTENT_EXTRACTION_SYSTEM_PROMPT, BROADEN_SEARCH_SYSTEM_PROMPT
    from observability import traced_anthropic_client
except ImportError:
    from .prompts import INTENT_EXTRACTION_SYSTEM_PROMPT, BROADEN_SEARCH_SYSTEM_PROMPT
    from .observability import traced_anthropic_client

load_dotenv()

# Traces every messages.create() call (latency, input/output tokens, model)
# to LangSmith automatically - no per-call instrumentation needed below.
# No-ops safely if LANGSMITH_API_KEY isn't set.
anthropic_client = traced_anthropic_client(Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")))


def extract_text(message) -> str:
    """Get text content from Claude response."""
    for block in message.content:
        if block.type == "text":
            return block.text
    raise ValueError(f"No text block found — got: {[b.type for b in message.content]}")


def _parse_json_response(response_text: str) -> dict:
    """Strip optional markdown code fences and parse JSON."""
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def extract_intent(user_query: str) -> dict:
    """
    Extract structured recommendation intent from user query.

    For progression queries, also generates level structure:
    "levels": [
        {
            "level": 1,
            "description": "Introduction to topic",
            "keywords": ["keyword1", "keyword2"],
            "audience_qualifier": "board book"
        },
        ...
    ]

    Returns dict with themes, audience, genre, format, recommendation_type, etc.
    """
    message = anthropic_client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=INTENT_EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_query}]
    )

    try:
        return _parse_json_response(extract_text(message))
    except (json.JSONDecodeError, IndexError) as e:
        print(f"Error parsing intent: {e}")
        return {
            "themes": [],
            "audience_range": "not_specified",
            "genre": "not_specified",
            "format": "not_specified",
            "recommendation_type": "general",
            "request_type": "general",
            "use_canonical_search": False,
            "known_titles": [],
            "error": str(e)
        }


def broaden_search_with_llm(original_query: str, themes_tried: list, known_titles_tried: list, bad_reason: str) -> dict:
    """
    Phase 2 tier-2 retry: called only when the cheap tier-1 retry (dropping
    the subject: filter and re-searching with the same themes) still didn't
    find enough candidates. Given the full history of what's been tried,
    asks Claude to propose a genuinely broader search rather than a small
    tweak on the same narrow keywords.

    Returns dict with "themes" (exactly 3) and "known_titles" (up to 4).
    Falls back to the original themes/titles unchanged if parsing fails,
    so a broaden failure never leaves the caller with nothing to search.
    """
    history = (
        f"Original request: {original_query}\n"
        f"Themes already tried: {themes_tried}\n"
        f"Known titles already tried: {known_titles_tried}\n"
        f"Why it's still insufficient: {bad_reason}"
    )

    message = anthropic_client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=512,
        system=BROADEN_SEARCH_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": history}]
    )

    try:
        result = _parse_json_response(extract_text(message))
        return {
            "themes": result.get("themes", themes_tried)[:3],
            "known_titles": result.get("known_titles", known_titles_tried)[:4],
        }
    except (json.JSONDecodeError, IndexError) as e:
        print(f"Error parsing broaden-search response: {e}")
        return {"themes": themes_tried, "known_titles": known_titles_tried}


if __name__ == "__main__":
    test_queries = [
        "I'm looking for a beginner-friendly novel about artificial intelligence.",
        "My 4 year old son is into cars and trucks. Give me recommendations.",
        "I need a sci-fi book that deals heavily with AI ethics and personhood.",
        "My son likes cars. Recommend a progression of books so he learns about engineering.",
        "What graphic novels would engage a reluctant 8-year-old reader?",
    ]

    print("=" * 80)
    print("INTENT EXTRACTION TEST")
    print("=" * 80)

    for query in test_queries:
        print(f"\nQuery: {query}")
        print("-" * 80)
        intent = extract_intent(query)
        print(json.dumps(intent, indent=2))
