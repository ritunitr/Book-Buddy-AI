"""
Database helper functions for simplified schema.
Manages users, preferences, and interaction log.
"""

import os
import json
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from supabase import create_client, Client
from prompts import get_pattern_detection_prompt

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================================================
# User Management
# ============================================================================

def get_or_create_user(email: str) -> str:
    """Get user ID by email, or create user if doesn't exist."""
    result = supabase.table("user_profile").select("user_id").eq("email", email).execute()

    if result.data:
        return result.data[0]["user_id"]

    # Create new user
    new_user = supabase.table("user_profile").insert({"email": email}).execute()
    return new_user.data[0]["user_id"]


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Fetch user by ID."""
    result = supabase.table("user_profile").select("*").eq("user_id", user_id).execute()
    return result.data[0] if result.data else None


# ============================================================================
# User Preferences (THE CORE)
# ============================================================================

def get_or_create_preferences(user_id: str) -> Dict[str, Any]:
    """Get or create user preferences."""
    result = supabase.table("user_preferences").select("*").eq("user_id", user_id).execute()

    if result.data:
        return result.data[0]

    # Create new preferences
    new_prefs = supabase.table("user_preferences").insert({
        "user_id": user_id,
        "liked_books": [],
        "disliked_books": [],
        "liked_authors": [],
        "liked_genres": [],
        "disliked_authors": [],
        "disliked_genres": []
    }).execute()

    return new_prefs.data[0]


def get_user_preferences(user_id: str) -> Dict[str, Any]:
    """Fetch user preferences."""
    result = supabase.table("user_preferences").select("*").eq("user_id", user_id).execute()
    return result.data[0] if result.data else get_or_create_preferences(user_id)


def update_preferences(user_id: str, preferences: Dict[str, List[str]]) -> Dict[str, Any]:
    """
    Update user preferences.

    Args:
        user_id: User ID
        preferences: {
            "liked_books": [...],
            "disliked_books": [...],
            "liked_authors": [...],
            "liked_genres": [...],
            "disliked_authors": [...],
            "disliked_genres": [...]
        }
    """
    from datetime import datetime, timezone
    update_data = {
        **preferences,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    result = supabase.table("user_preferences").update(update_data).eq("user_id", user_id).execute()
    return result.data[0] if result.data else {}


def add_to_preferences(user_id: str, field: str, value: str) -> None:
    """
    Add a single item to a preference array.

    Args:
        field: 'liked_books', 'disliked_authors', etc.
        value: Item to add
    """
    from datetime import datetime, timezone
    prefs = get_user_preferences(user_id)
    current = prefs.get(field, []) or []

    if value not in current:
        current.append(value)
        update_data = {
            field: current,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        supabase.table("user_preferences").update(update_data).eq("user_id", user_id).execute()


# ============================================================================
# Interaction Log (Session Feedback)
# ============================================================================

def log_feedback(user_id: str, liked_books: List[str], disliked_books: List[str]) -> str:
    """
    Log user feedback from a single query session.

    Returns:
        interaction_log_id
    """
    result = supabase.table("interaction_log").insert({
        "user_id": user_id,
        "liked_books": liked_books,
        "disliked_books": disliked_books
    }).execute()

    return result.data[0]["id"] if result.data else None


def get_recent_interactions(user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent feedback interactions for a user."""
    result = supabase.table("interaction_log").select("*").eq(
        "user_id", user_id
    ).order("timestamp", desc=True).limit(limit).execute()

    return result.data


def get_all_feedback(user_id: str) -> Dict[str, List[str]]:
    """
    Get all liked and disliked books from interaction history.
    Used for pattern detection.
    """
    interactions = get_recent_interactions(user_id, limit=100)

    all_liked = set()
    all_disliked = set()

    for interaction in interactions:
        all_liked.update(interaction.get("liked_books", []))
        all_disliked.update(interaction.get("disliked_books", []))

    return {
        "liked_books": list(all_liked),
        "disliked_books": list(all_disliked)
    }


# ============================================================================
# Pattern Detection (for suggesting preference updates)
# ============================================================================

def detect_patterns(user_id: str) -> Dict[str, Any]:
    """
    Detect patterns from recent feedback using Claude.
    Analyzes liked/disliked books to suggest new genres, authors, themes.

    Returns:
        {
            "suggested_liked_genres": [...],
            "suggested_liked_authors": [...],
            "suggested_disliked_genres": [...],
            "suggested_disliked_authors": [...],
            "analysis": "Why these suggestions",
            "confidence": 0.8,
            "feedback_count": 10,
            "books_analyzed": ["Title 1", "Title 2", ...]
        }
    """
    from anthropic import Anthropic

    feedback = get_all_feedback(user_id)
    prefs = get_user_preferences(user_id)

    liked_books = feedback.get("liked_books", [])
    disliked_books = feedback.get("disliked_books", [])

    # Need at least 5 voted books to detect patterns
    if len(liked_books) + len(disliked_books) < 5:
        return {
            "suggested_liked_genres": [],
            "suggested_liked_authors": [],
            "suggested_disliked_genres": [],
            "suggested_disliked_authors": [],
            "analysis": f"Need at least 5 votes to detect patterns (currently {len(liked_books) + len(disliked_books)})",
            "confidence": 0.0,
            "feedback_count": len(liked_books) + len(disliked_books),
            "books_analyzed": []
        }

    # Use Claude to detect patterns
    client = Anthropic()
    prompt = get_pattern_detection_prompt(liked_books, disliked_books, prefs)

    try:
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        import json
        response_text = message.content[0].text

        # Extract JSON from response
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to find JSON in the response
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                raise ValueError("Could not parse Claude response as JSON")

        return {
            **result,
            "feedback_count": len(liked_books) + len(disliked_books),
            "books_analyzed": liked_books + disliked_books
        }

    except Exception as e:
        print(f"Error detecting patterns: {e}")
        return {
            "suggested_liked_genres": [],
            "suggested_liked_authors": [],
            "suggested_disliked_genres": [],
            "suggested_disliked_authors": [],
            "analysis": f"Pattern detection error: {str(e)}",
            "confidence": 0.0,
            "feedback_count": len(liked_books) + len(disliked_books),
            "books_analyzed": []
        }


# ============================================================================
# Statistics
# ============================================================================

def get_user_stats(user_id: str) -> Dict[str, Any]:
    """Get summary statistics about a user."""
    prefs = get_user_preferences(user_id)
    interactions = get_recent_interactions(user_id, limit=100)

    return {
        "total_interactions": len(interactions),
        "liked_books": len(prefs.get("liked_books", []) or []),
        "disliked_books": len(prefs.get("disliked_books", []) or []),
        "liked_authors": len(prefs.get("liked_authors", []) or []),
        "liked_genres": len(prefs.get("liked_genres", []) or []),
        "disliked_authors": len(prefs.get("disliked_authors", []) or []),
        "disliked_genres": len(prefs.get("disliked_genres", []) or []),
        "updated_at": prefs.get("updated_at")
    }
