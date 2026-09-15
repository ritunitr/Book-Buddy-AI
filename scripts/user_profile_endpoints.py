"""
User Profile Endpoints - Simplified

POST /feedback - Record liked/disliked books from a recommendation session
POST /preferences - Update user's explicit preferences
GET /user-profile - Get user's current preferences and stats
"""

from typing import Optional, List
from pydantic import BaseModel
import db_helpers


class FeedbackRequest(BaseModel):
    """Record feedback from a recommendation session."""
    user_email: str
    liked_book_titles: List[str]
    rejected_book_titles: List[str]


class FeedbackResponse(BaseModel):
    """Response from /feedback endpoint."""
    success: bool
    message: str
    feedback_count: int


class PreferencesRequest(BaseModel):
    """Update user preferences."""
    user_email: str
    liked_books: Optional[List[str]] = None
    disliked_books: Optional[List[str]] = None
    liked_authors: Optional[List[str]] = None
    liked_genres: Optional[List[str]] = None
    disliked_authors: Optional[List[str]] = None
    disliked_genres: Optional[List[str]] = None


class PreferencesResponse(BaseModel):
    """Current user preferences."""
    user_email: str
    liked_books: List[str]
    disliked_books: List[str]
    liked_authors: List[str]
    liked_genres: List[str]
    disliked_authors: List[str]
    disliked_genres: List[str]
    updated_at: str


class PatternSuggestions(BaseModel):
    """Suggested preferences based on feedback analysis."""
    user_email: str
    suggested_liked_genres: List[str]
    suggested_liked_authors: List[str]
    suggested_disliked_genres: List[str]
    suggested_disliked_authors: List[str]
    analysis: str
    confidence: float
    feedback_count: int
    books_analyzed: List[str]


class ConfirmPatternsRequest(BaseModel):
    """Confirm which suggested patterns to accept."""
    user_email: str
    liked_genres: Optional[List[str]] = None
    liked_authors: Optional[List[str]] = None
    disliked_genres: Optional[List[str]] = None
    disliked_authors: Optional[List[str]] = None


# ============================================================================
# Feedback Endpoint
# ============================================================================

async def handle_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """
    Record user feedback from a recommendation session.

    Flow:
    1. Get or create user
    2. Log feedback (liked/disliked books)
    3. Return feedback count
    """
    user_id = db_helpers.get_or_create_user(request.user_email)

    # Log this session's feedback
    db_helpers.log_feedback(
        user_id=user_id,
        liked_books=request.liked_book_titles,
        disliked_books=request.rejected_book_titles
    )

    # Get total feedback count
    interactions = db_helpers.get_recent_interactions(user_id, limit=100)
    feedback_count = len(interactions)

    return FeedbackResponse(
        success=True,
        message=f"Feedback recorded ({feedback_count} total sessions)",
        feedback_count=feedback_count
    )


# ============================================================================
# Preferences Endpoint
# ============================================================================

async def handle_get_preferences(user_email: str) -> PreferencesResponse:
    """Get user's current preferences."""
    user_id = db_helpers.get_or_create_user(user_email)
    prefs = db_helpers.get_user_preferences(user_id)

    return PreferencesResponse(
        user_email=user_email,
        liked_books=prefs.get("liked_books", []) or [],
        disliked_books=prefs.get("disliked_books", []) or [],
        liked_authors=prefs.get("liked_authors", []) or [],
        liked_genres=prefs.get("liked_genres", []) or [],
        disliked_authors=prefs.get("disliked_authors", []) or [],
        disliked_genres=prefs.get("disliked_genres", []) or [],
        updated_at=prefs.get("updated_at", "")
    )


async def handle_update_preferences(request: PreferencesRequest) -> PreferencesResponse:
    """Update user preferences."""
    user_id = db_helpers.get_or_create_user(request.user_email)

    # Build update dict with non-None values
    update_data = {}
    if request.liked_books is not None:
        update_data["liked_books"] = request.liked_books
    if request.disliked_books is not None:
        update_data["disliked_books"] = request.disliked_books
    if request.liked_authors is not None:
        update_data["liked_authors"] = request.liked_authors
    if request.liked_genres is not None:
        update_data["liked_genres"] = request.liked_genres
    if request.disliked_authors is not None:
        update_data["disliked_authors"] = request.disliked_authors
    if request.disliked_genres is not None:
        update_data["disliked_genres"] = request.disliked_genres

    if update_data:
        db_helpers.update_preferences(user_id, update_data)

    # Return updated preferences
    prefs = db_helpers.get_user_preferences(user_id)

    return PreferencesResponse(
        user_email=request.user_email,
        liked_books=prefs.get("liked_books", []) or [],
        disliked_books=prefs.get("disliked_books", []) or [],
        liked_authors=prefs.get("liked_authors", []) or [],
        liked_genres=prefs.get("liked_genres", []) or [],
        disliked_authors=prefs.get("disliked_authors", []) or [],
        disliked_genres=prefs.get("disliked_genres", []) or [],
        updated_at=prefs.get("updated_at", "")
    )


# ============================================================================
# Pattern Detection Endpoints
# ============================================================================

async def handle_get_patterns(user_email: str) -> PatternSuggestions:
    """
    Detect patterns from user's feedback history.
    Uses Claude to analyze liked/disliked books and suggest new preferences.
    """
    user_id = db_helpers.get_or_create_user(user_email)
    patterns = db_helpers.detect_patterns(user_id)

    return PatternSuggestions(
        user_email=user_email,
        suggested_liked_genres=patterns.get("suggested_liked_genres", []),
        suggested_liked_authors=patterns.get("suggested_liked_authors", []),
        suggested_disliked_genres=patterns.get("suggested_disliked_genres", []),
        suggested_disliked_authors=patterns.get("suggested_disliked_authors", []),
        analysis=patterns.get("analysis", ""),
        confidence=patterns.get("confidence", 0.0),
        feedback_count=patterns.get("feedback_count", 0),
        books_analyzed=patterns.get("books_analyzed", [])
    )


async def handle_confirm_patterns(request: ConfirmPatternsRequest) -> PreferencesResponse:
    """
    Accept suggested patterns and update user preferences.
    User can choose which suggestions to keep and which to reject.
    """
    user_id = db_helpers.get_or_create_user(request.user_email)
    prefs = db_helpers.get_user_preferences(user_id)

    # Build update dict by merging suggestions with existing preferences
    update_data = {}

    if request.liked_genres is not None:
        current_genres = set(prefs.get("liked_genres", []) or [])
        current_genres.update(request.liked_genres)
        update_data["liked_genres"] = list(current_genres)

    if request.liked_authors is not None:
        current_authors = set(prefs.get("liked_authors", []) or [])
        current_authors.update(request.liked_authors)
        update_data["liked_authors"] = list(current_authors)

    if request.disliked_genres is not None:
        current_genres = set(prefs.get("disliked_genres", []) or [])
        current_genres.update(request.disliked_genres)
        update_data["disliked_genres"] = list(current_genres)

    if request.disliked_authors is not None:
        current_authors = set(prefs.get("disliked_authors", []) or [])
        current_authors.update(request.disliked_authors)
        update_data["disliked_authors"] = list(current_authors)

    if update_data:
        db_helpers.update_preferences(user_id, update_data)

    # Return updated preferences
    prefs = db_helpers.get_user_preferences(user_id)

    return PreferencesResponse(
        user_email=request.user_email,
        liked_books=prefs.get("liked_books", []) or [],
        disliked_books=prefs.get("disliked_books", []) or [],
        liked_authors=prefs.get("liked_authors", []) or [],
        liked_genres=prefs.get("liked_genres", []) or [],
        disliked_authors=prefs.get("disliked_authors", []) or [],
        disliked_genres=prefs.get("disliked_genres", []) or [],
        updated_at=prefs.get("updated_at", "")
    )
