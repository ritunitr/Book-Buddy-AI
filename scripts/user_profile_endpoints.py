"""
Milestone 2: User Profile Endpoints
- POST /feedback: Capture user feedback on recommendations
- GET /user-profile: Retrieve user's semantic + procedural profile
"""

from typing import Optional, List
from pydantic import BaseModel
import db_helpers
from asyncio import create_task
from datetime import datetime


# ============================================================================
# Request/Response Models
# ============================================================================

class FeedbackRequest(BaseModel):
    """POST /feedback request body."""
    user_email: str
    liked_book_titles: List[str]
    rejected_book_titles: List[str]
    feedback_text: Optional[str] = None


class FeedbackResponse(BaseModel):
    """Response from /feedback endpoint."""
    success: bool
    message: str
    feedback_count: int
    summarizer_triggered: bool


class UserProfileResponse(BaseModel):
    """Response from /user-profile endpoint."""
    user_email: str
    semantic_profile: dict  # interests, preferences, dislikes
    procedural_profile: dict  # reading_velocity, completion_rate, etc.
    stats: dict


# ============================================================================
# Feedback Endpoint (POST /feedback)
# ============================================================================

FEEDBACK_SUMMARIZER_THRESHOLD = 5  # Trigger summarizer every 5 feedbacks


async def handle_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """
    Handle user feedback on book recommendations.

    Flow:
    1. Get or create user
    2. Add liked books to reading_history (so they're not recommended again)
    3. Add rejected books to reading_history with "abandoned" status (filtered out)
    4. Log interaction (feedback given)
    5. Every Nth feedback, trigger Claude to distill semantic/procedural profile
    """

    # Step 1: Get or create user
    user_id = db_helpers.get_or_create_user(request.user_email)

    # Step 2: Add liked books to reading_history (status: "want" = wishlist)
    for title in request.liked_book_titles:
        try:
            db_helpers.add_to_reading_history(
                user_id=user_id,
                book_id=f"liked_{title.lower().replace(' ', '_')}",
                title=title,
                authors=[],
                status="want"  # Wishlist: user liked it, won't recommend same book
            )
        except Exception:
            pass  # Skip if book already exists

    # Step 3: Add rejected books to reading_history (status: "abandoned")
    for title in request.rejected_book_titles:
        try:
            db_helpers.add_to_reading_history(
                user_id=user_id,
                book_id=f"rejected_{title.lower().replace(' ', '_')}",
                title=title,
                authors=[],
                status="abandoned"  # Filtered out: won't recommend again
            )
        except Exception:
            pass  # Skip if book already exists

    # Step 4: Log the feedback interaction
    db_helpers.log_interaction(
        user_id=user_id,
        event_type="feedback_given",
        event_data={
            "liked_titles": request.liked_book_titles,
            "rejected_titles": request.rejected_book_titles,
            "feedback_text": request.feedback_text or ""
        }
    )

    # Step 5: Check if summarizer should trigger (every Nth feedback)
    feedback_count = db_helpers.count_feedback_since_last_summary(user_id)
    summarizer_triggered = False

    if feedback_count >= FEEDBACK_SUMMARIZER_THRESHOLD:
        # Trigger async summarizer (non-blocking)
        create_task(_trigger_summarizer_async(user_id))
        summarizer_triggered = True

    return FeedbackResponse(
        success=True,
        message="Feedback recorded successfully",
        feedback_count=feedback_count,
        summarizer_triggered=summarizer_triggered
    )


async def _trigger_summarizer_async(user_id: str):
    """
    Async task: Summarize user's episodic memory into semantic/procedural facts.
    This will call Claude to distill patterns.
    """
    try:
        # Import here to avoid circular dependency
        from profile_summarizer import summarize_user_profile

        await summarize_user_profile(user_id)
    except Exception as e:
        print(f"[Summarizer Error] Failed to summarize profile for user {user_id}: {e}")


# ============================================================================
# User Profile Endpoint (GET /user-profile)
# ============================================================================

async def handle_get_user_profile(user_email: str) -> UserProfileResponse:
    """
    Get user's current semantic and procedural profile.

    Semantic: interests, preferences, dislikes (distilled from feedback)
    Procedural: reading_velocity, completion_rate, series_preference (learned patterns)
    """

    # Get or create user
    user_id = db_helpers.get_or_create_user(user_email)

    # Ensure profile exists
    db_helpers.get_or_create_user_profile(user_id)

    # Fetch profile
    profile = db_helpers.get_user_profile(user_id)

    if not profile:
        # Shouldn't happen, but handle gracefully
        profile = {
            "semantic_json": {},
            "procedural_json": {},
            "last_summarized": None
        }

    # Get stats
    stats = db_helpers.get_user_stats(user_id)

    return UserProfileResponse(
        user_email=user_email,
        semantic_profile=profile.get("semantic_json", {}),
        procedural_profile=profile.get("procedural_json", {}),
        stats=stats
    )


# ============================================================================
# Graceful Fallback (No Profile Yet)
# ============================================================================

def handle_get_user_profile_fallback(user_email: str) -> UserProfileResponse:
    """
    Fallback when user has no profile yet.
    Returns empty semantic/procedural profiles with stats.
    """
    user_id = db_helpers.get_or_create_user(user_email)
    stats = db_helpers.get_user_stats(user_id)

    return UserProfileResponse(
        user_email=user_email,
        semantic_profile={},
        procedural_profile={},
        stats=stats
    )
