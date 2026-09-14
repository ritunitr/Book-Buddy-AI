"""
Profile Summarizer: Uses Claude to distill episodic memory into semantic/procedural facts.

Runs every Nth feedback (currently N=5).
- Reads recommendation sessions and feedback
- Uses Claude to extract patterns (interests, preferences, reading velocity, etc.)
- Writes distilled facts to user_profiles table
"""

import os
import json
from typing import Dict, Any, Optional
from anthropic import Anthropic
from dotenv import load_dotenv
import db_helpers

load_dotenv()

anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Claude model to use for summarization
SUMMARIZER_MODEL = "claude-opus-5"
MAX_SESSIONS_TO_ANALYZE = 50  # Limit sessions for cost/speed


SUMMARIZER_SYSTEM_PROMPT = """You are an expert at analyzing reading patterns and preferences from user feedback.

Given a user's recommendation sessions and feedback history, extract:
1. SEMANTIC MEMORY (what the user likes/dislikes):
   - interests: list of genres, themes, topics they like
   - preferences: tone (dark/hopeful), depth (light/intermediate/deep), pacing, etc.
   - dislikes: genres/themes/styles they explicitly rejected

2. PROCEDURAL MEMORY (learned reading patterns):
   - reading_velocity: books per month (estimated from dates if available)
   - completion_rate: % of started books they finish (0-1)
   - series_preference: do they prefer series or standalones?
   - avg_rating: their average rating of books they read
   - preferred_length: short/medium/long books (if discernible)

Output ONLY valid JSON (no markdown, no explanation) with this exact structure:
{
  "semantic": {
    "interests": ["list", "of", "interests"],
    "preferences": {"key": "value", ...},
    "dislikes": ["list", "of", "dislikes"]
  },
  "procedural": {
    "reading_velocity": 1.5,
    "completion_rate": 0.85,
    "series_preference": true,
    "avg_rating": 4.2,
    "preferred_length": "medium"
  }
}

Be conservative: only include facts you can infer from the data. If you're unsure, omit it.
"""


async def summarize_user_profile(user_id: str) -> Dict[str, Any]:
    """
    Summarize user's episodic memory into semantic/procedural profile.
    Called every Nth feedback session.

    Returns:
        {
            "semantic": {...},
            "procedural": {...},
            "last_summarized": timestamp
        }
    """

    # Fetch user's data
    user = db_helpers.get_user_by_id(user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")

    sessions = db_helpers.get_user_sessions(user_id, limit=MAX_SESSIONS_TO_ANALYZE)
    reading_history = db_helpers.get_user_reading_history(user_id)

    # Prepare context for Claude
    episodic_summary = _format_episodic_data(sessions, reading_history)

    # Call Claude to distill patterns
    semantic_data, procedural_data = await _call_summarizer_claude(
        user_email=user["email"],
        episodic_data=episodic_summary
    )

    # Update user profile in database
    updated_profile = db_helpers.update_user_profile(
        user_id=user_id,
        semantic_data=semantic_data,
        procedural_data=procedural_data
    )

    return {
        "user_id": user_id,
        "semantic": semantic_data,
        "procedural": procedural_data,
        "last_summarized": updated_profile.get("last_summarized")
    }


def _format_episodic_data(sessions: list, reading_history: list) -> str:
    """Format episodic data for Claude to analyze."""

    # Format feedback from sessions
    feedback_summary = []
    for session in sessions[:10]:  # Most recent 10 sessions
        if session.get("liked_indices") or session.get("rejected_indices"):
            recs = session.get("recommendations", [])

            liked = []
            for idx in session.get("liked_indices", []):
                if idx < len(recs):
                    liked.append(f"{recs[idx].get('title', 'Unknown')} ({recs[idx].get('why', '')})")

            rejected = []
            for idx in session.get("rejected_indices", []):
                if idx < len(recs):
                    rejected.append(f"{recs[idx].get('title', 'Unknown')}")

            feedback_summary.append({
                "query": session["query"],
                "liked": liked,
                "rejected": rejected,
                "feedback": session.get("user_feedback", "")
            })

    # Format reading history
    books_read = [
        {
            "title": b["title"],
            "authors": b.get("authors", []),
            "status": b["status"],
            "rating": b.get("rating"),
            "review": b.get("review_text", "")
        }
        for b in reading_history[:20]  # Most recent 20 reads
    ]

    return json.dumps({
        "recent_feedback": feedback_summary,
        "recent_reads": books_read,
        "total_sessions": len(sessions),
        "total_reads": len(reading_history)
    }, indent=2)


async def _call_summarizer_claude(user_email: str, episodic_data: str) -> tuple:
    """
    Call Claude Opus to distill episodic data into semantic/procedural memory.

    Returns:
        (semantic_dict, procedural_dict)
    """

    user_prompt = f"""User: {user_email}

Recent recommendation sessions and feedback:
{episodic_data}

Extract semantic (interests/preferences/dislikes) and procedural (patterns) memory from this user's behavior.
Return ONLY valid JSON, no other text."""

    response = anthropic.messages.create(
        model=SUMMARIZER_MODEL,
        max_tokens=1024,
        system=SUMMARIZER_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_prompt}
        ]
    )

    # Parse Claude's response
    response_text = response.content[0].text.strip()

    # Handle markdown code blocks if Claude wraps response
    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]
        response_text = response_text.strip()

    result = json.loads(response_text)

    semantic = result.get("semantic", {})
    procedural = result.get("procedural", {})

    return semantic, procedural


# ============================================================================
# Debug/Manual Trigger
# ============================================================================

def summarize_manually(user_email: str) -> Dict[str, Any]:
    """
    Manually trigger summarization for a user (for testing/debugging).
    This is a sync wrapper around the async function.
    """
    import asyncio

    user_id = db_helpers.get_or_create_user(user_email)

    # Run async function in sync context
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(summarize_user_profile(user_id))
    loop.close()

    return result
