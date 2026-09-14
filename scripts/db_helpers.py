"""
Database helper functions for Supabase operations.
Abstracts episodic, semantic, and procedural memory interactions.
"""

import os
import json
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from supabase import create_client, Client

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
    # Try to find existing user
    result = supabase.table("users").select("id").eq("email", email).execute()

    if result.data:
        return result.data[0]["id"]

    # Create new user
    new_user = supabase.table("users").insert({"email": email}).execute()
    return new_user.data[0]["id"]


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Fetch user by ID."""
    result = supabase.table("users").select("*").eq("id", user_id).execute()
    return result.data[0] if result.data else None


# ============================================================================
# Episodic Memory: Recommendation Sessions
# ============================================================================

def create_recommendation_session(
    user_id: str,
    query: str,
    recommendation_type: str,
    recommendations: List[Dict[str, Any]]
) -> str:
    """
    Create a recommendation session (episodic event).

    Returns:
        session_id: UUID of the created session
    """
    response = supabase.table("recommendation_sessions").insert({
        "user_id": user_id,
        "query": query,
        "recommendation_type": recommendation_type,
        "num_recommendations": len(recommendations),
        "recommendations": json.dumps(recommendations)
    }).execute()

    return response.data[0]["id"]


def add_feedback_to_session(
    session_id: str,
    liked_indices: List[int],
    rejected_indices: List[int],
    feedback_text: Optional[str] = None
) -> Dict[str, Any]:
    """
    Add user feedback to a recommendation session.

    Returns:
        updated session data
    """
    update_data = {
        "liked_indices": liked_indices,
        "rejected_indices": rejected_indices
    }

    if feedback_text:
        update_data["user_feedback"] = feedback_text

    response = supabase.table("recommendation_sessions").update(
        update_data
    ).eq("id", session_id).execute()

    return response.data[0] if response.data else {}


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a recommendation session."""
    try:
        result = supabase.table("recommendation_sessions").select("*").eq(
            "id", session_id
        ).execute()

        if result.data:
            # Parse JSON fields
            session = result.data[0]
            if session.get("recommendations"):
                session["recommendations"] = json.loads(session["recommendations"])
            return session

        return None
    except Exception:
        # Invalid UUID format or other error
        return None


def get_user_sessions(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Fetch all recommendation sessions for a user (ordered by most recent).
    Used by summarizer to extract semantic/procedural patterns.
    """
    result = supabase.table("recommendation_sessions").select("*").eq(
        "user_id", user_id
    ).order("timestamp", desc=True).limit(limit).execute()

    sessions = []
    for session in result.data:
        if session.get("recommendations"):
            session["recommendations"] = json.loads(session["recommendations"])
        sessions.append(session)

    return sessions


# ============================================================================
# Episodic Memory: Reading History
# ============================================================================

def add_to_reading_history(
    user_id: str,
    book_id: str,
    title: str,
    authors: List[str],
    status: str,
    rating: Optional[int] = None,
    review_text: Optional[str] = None,
    came_from_session_id: Optional[str] = None
) -> str:
    """
    Add a book to user's reading history.
    Tracks user's actual reads (not just recommendations).
    """
    data = {
        "user_id": user_id,
        "book_id": book_id,
        "title": title,
        "authors": authors,
        "status": status
    }

    if rating:
        data["rating"] = rating

    if review_text:
        data["review_text"] = review_text

    if came_from_session_id:
        data["came_from_recommendation_id"] = came_from_session_id

    response = supabase.table("reading_history").insert(data).execute()
    return response.data[0]["id"]


def get_user_reading_history(user_id: str) -> List[Dict[str, Any]]:
    """Fetch all books user has read/is reading."""
    result = supabase.table("reading_history").select("*").eq(
        "user_id", user_id
    ).order("date_finished", desc=True).execute()

    return result.data


def get_unread_books(user_id: str) -> List[str]:
    """
    Get list of book IDs user has already read or is reading.
    These should be filtered out from recommendations.

    Books with status "want" (wishlist) or "abandoned" are NOT excluded
    since users may want recommendations similar to what they abandoned,
    and wishlist books can be recommended by others.
    """
    result = supabase.table("reading_history").select("book_id").eq(
        "user_id", user_id
    ).in_("status", ["read", "reading"]).execute()

    # Extract book_ids (only read or currently reading)
    already_read_ids = set(row["book_id"] for row in result.data)

    # Also check recommendations they've given feedback on (already got)
    sessions = get_user_sessions(user_id)
    for session in sessions:
        if session.get("liked_indices"):
            recs = session.get("recommendations", [])
            for idx in session["liked_indices"]:
                if idx < len(recs):
                    already_read_ids.add(recs[idx].get("book_id", ""))

    return list(already_read_ids)


# ============================================================================
# Semantic Memory: User Profiles
# ============================================================================

def get_or_create_user_profile(user_id: str) -> str:
    """Get user profile ID, or create empty one if doesn't exist."""
    result = supabase.table("user_profiles").select("id").eq(
        "user_id", user_id
    ).execute()

    if result.data:
        return result.data[0]["id"]

    # Create new profile
    new_profile = supabase.table("user_profiles").insert({
        "user_id": user_id,
        "semantic_json": json.dumps({}),
        "procedural_json": json.dumps({})
    }).execute()

    return new_profile.data[0]["id"]


def get_user_profile(user_id: str) -> Optional[Dict[str, Any]]:
    """Fetch user's semantic + procedural profile."""
    result = supabase.table("user_profiles").select("*").eq(
        "user_id", user_id
    ).execute()

    if not result.data:
        return None

    profile = result.data[0]

    # Parse JSON fields
    if profile.get("semantic_json"):
        profile["semantic_json"] = json.loads(profile["semantic_json"])
    else:
        profile["semantic_json"] = {}

    if profile.get("procedural_json"):
        profile["procedural_json"] = json.loads(profile["procedural_json"])
    else:
        profile["procedural_json"] = {}

    return profile


def update_user_profile(
    user_id: str,
    semantic_data: Optional[Dict[str, Any]] = None,
    procedural_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Update user's semantic/procedural profile.
    Called by the summarizer agent after distilling facts from episodic data.
    """
    update_dict = {}

    if semantic_data is not None:
        update_dict["semantic_json"] = json.dumps(semantic_data)

    if procedural_data is not None:
        update_dict["procedural_json"] = json.dumps(procedural_data)

    if update_dict:
        update_dict["last_summarized"] = "now()"

    result = supabase.table("user_profiles").update(update_dict).eq(
        "user_id", user_id
    ).execute()

    if result.data:
        profile = result.data[0]
        if profile.get("semantic_json"):
            profile["semantic_json"] = json.loads(profile["semantic_json"])
        if profile.get("procedural_json"):
            profile["procedural_json"] = json.loads(profile["procedural_json"])
        return profile

    return {}


# ============================================================================
# Interaction Log (Audit Trail)
# ============================================================================

def log_interaction(
    user_id: str,
    event_type: str,
    event_data: Dict[str, Any],
    session_id: Optional[str] = None
) -> str:
    """Log an interaction event."""
    data = {
        "user_id": user_id,
        "event_type": event_type,
        "event_data": json.dumps(event_data)
    }

    if session_id:
        data["session_id"] = session_id

    response = supabase.table("interaction_log").insert(data).execute()
    return response.data[0]["id"]


def get_user_interactions(user_id: str, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch user's interaction logs, optionally filtered by event type."""
    query = supabase.table("interaction_log").select("*").eq("user_id", user_id)

    if event_type:
        query = query.eq("event_type", event_type)

    result = query.order("timestamp", desc=True).execute()

    interactions = []
    for log in result.data:
        if log.get("event_data"):
            log["event_data"] = json.loads(log["event_data"])
        interactions.append(log)

    return interactions


# ============================================================================
# Feedback Counting (For Summarizer Trigger)
# ============================================================================

def count_feedback_since_last_summary(user_id: str) -> int:
    """
    Count how many feedback entries user has given since last summarization.
    Used to trigger summarizer every Nth feedback.
    """
    profile = get_user_profile(user_id)

    if not profile or not profile.get("last_summarized"):
        # Never summarized, count all feedback
        last_summary = None
    else:
        last_summary = profile["last_summarized"]

    # Count sessions with feedback since last summary
    query = supabase.table("recommendation_sessions").select(
        "count", count="exact"
    ).eq("user_id", user_id).not_.is_("liked_indices", "null")

    if last_summary:
        query = query.gt("feedback_timestamp", last_summary)

    result = query.execute()
    return result.count if result.count is not None else 0


# ============================================================================
# Summary Statistics (For Debugging)
# ============================================================================

def get_user_stats(user_id: str) -> Dict[str, Any]:
    """Get summary statistics about a user."""
    sessions = get_user_sessions(user_id)
    reading_history = get_user_reading_history(user_id)
    profile = get_user_profile(user_id)

    feedback_count = sum(
        1 for s in sessions if s.get("liked_indices") or s.get("rejected_indices")
    )

    return {
        "total_queries": len(sessions),
        "total_feedback_given": feedback_count,
        "books_read": len([b for b in reading_history if b["status"] == "read"]),
        "books_currently_reading": len([b for b in reading_history if b["status"] == "reading"]),
        "books_in_wishlist": len([b for b in reading_history if b["status"] == "want"]),
        "profile_interests": profile["semantic_json"].get("interests", []) if profile else [],
        "last_summarized": profile["last_summarized"] if profile else None
    }
