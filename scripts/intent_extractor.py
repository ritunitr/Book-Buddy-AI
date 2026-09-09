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
    from prompts import INTENT_EXTRACTION_SYSTEM_PROMPT
except ImportError:
    from .prompts import INTENT_EXTRACTION_SYSTEM_PROMPT

load_dotenv()

anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def extract_text(message) -> str:
    """Get text content from Claude response."""
    for block in message.content:
        if block.type == "text":
            return block.text
    raise ValueError(f"No text block found — got: {[b.type for b in message.content]}")


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

    response_text = extract_text(message).strip()

    try:
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]

        intent = json.loads(response_text.strip())
        return intent
    except json.JSONDecodeError as e:
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
