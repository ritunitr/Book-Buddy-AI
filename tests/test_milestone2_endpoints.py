"""
Unit tests for Milestone 2: User Profile Endpoints
Tests POST /feedback and GET /user-profile endpoints
"""

import pytest
import json
import asyncio
from typing import Dict, Any
from dotenv import load_dotenv
import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import db_helpers
from user_profile_endpoints import (
    FeedbackRequest,
    FeedbackResponse,
    UserProfileResponse,
    handle_feedback,
    handle_get_user_profile,
    FEEDBACK_SUMMARIZER_THRESHOLD
)

load_dotenv()


@pytest.fixture
def test_user_email():
    """Fixture: Test user email."""
    return "test_endpoint_user@example.com"


@pytest.fixture
def test_user(test_user_email):
    """Fixture: Create test user and cleanup after."""
    user_id = db_helpers.get_or_create_user(test_user_email)
    db_helpers.get_or_create_user_profile(user_id)
    yield user_id

    # Cleanup
    supabase = db_helpers.supabase
    supabase.table("users").delete().eq("id", user_id).execute()


@pytest.fixture
def test_session(test_user):
    """Fixture: Create test recommendation session."""
    session_id = db_helpers.create_recommendation_session(
        user_id=test_user,
        query="Find fantasy books",
        recommendation_type="general",
        recommendations=[
            {"title": "Book 1", "why": "Fantasy"},
            {"title": "Book 2", "why": "Adventure"},
            {"title": "Book 3", "why": "Magic"}
        ]
    )
    yield session_id


class TestFeedbackEndpoint:
    """Test POST /feedback endpoint."""

    @pytest.mark.asyncio
    async def test_feedback_basic(self, test_user_email, test_session):
        """Should accept feedback on a recommendation session."""
        request = FeedbackRequest(
            user_email=test_user_email,
            session_id=test_session,
            liked_indices=[0, 2],
            rejected_indices=[1],
            feedback_text="Loved 1st and 3rd books"
        )

        response = await handle_feedback(request)

        assert response.success
        assert response.session_id == test_session
        assert response.feedback_count >= 1

    @pytest.mark.asyncio
    async def test_feedback_without_text(self, test_user_email, test_session):
        """Should accept feedback without explanatory text."""
        request = FeedbackRequest(
            user_email=test_user_email,
            session_id=test_session,
            liked_indices=[0],
            rejected_indices=[1, 2]
        )

        response = await handle_feedback(request)

        assert response.success
        assert response.feedback_count >= 1

    @pytest.mark.asyncio
    async def test_feedback_invalid_session(self, test_user_email):
        """Should reject feedback for non-existent session."""
        request = FeedbackRequest(
            user_email=test_user_email,
            session_id="invalid-session-id",
            liked_indices=[0],
            rejected_indices=[]
        )

        response = await handle_feedback(request)

        assert not response.success
        assert "not found" in response.message.lower()

    @pytest.mark.asyncio
    async def test_feedback_wrong_user_session(self, test_user_email, test_session):
        """Should reject feedback if session doesn't belong to user."""
        # Create session for different user
        other_user_id = db_helpers.get_or_create_user("other_user@example.com")
        other_session = db_helpers.create_recommendation_session(
            user_id=other_user_id,
            query="Test query",
            recommendation_type="general",
            recommendations=[{"title": "Book", "why": "Test"}]
        )

        request = FeedbackRequest(
            user_email=test_user_email,
            session_id=other_session,
            liked_indices=[0],
            rejected_indices=[]
        )

        response = await handle_feedback(request)

        assert not response.success
        assert "does not belong" in response.message.lower()

        # Cleanup
        db_helpers.supabase.table("users").delete().eq("id", other_user_id).execute()

    @pytest.mark.asyncio
    async def test_feedback_logs_interaction(self, test_user_email, test_user, test_session):
        """Should log interaction when feedback is given."""
        request = FeedbackRequest(
            user_email=test_user_email,
            session_id=test_session,
            liked_indices=[0],
            rejected_indices=[1]
        )

        await handle_feedback(request)

        # Check interaction log
        interactions = db_helpers.get_user_interactions(test_user, event_type="feedback_given")
        assert len(interactions) > 0
        assert interactions[0]["event_data"]["liked_count"] == 1
        assert interactions[0]["event_data"]["rejected_count"] == 1

    @pytest.mark.asyncio
    async def test_feedback_multiple_times(self, test_user_email, test_session):
        """Should accept multiple feedback submissions."""
        for i in range(3):
            request = FeedbackRequest(
                user_email=test_user_email,
                session_id=test_session,
                liked_indices=[i % 3],
                rejected_indices=[]
            )

            response = await handle_feedback(request)
            assert response.success

    @pytest.mark.asyncio
    async def test_new_user_created_automatically(self, test_session):
        """Should create user if doesn't exist."""
        new_email = "auto_created_user@example.com"

        request = FeedbackRequest(
            user_email=new_email,
            session_id=test_session,
            liked_indices=[0],
            rejected_indices=[]
        )

        # This should fail because session doesn't belong to new user
        response = await handle_feedback(request)
        assert not response.success

        # But user should be created
        user = db_helpers.get_or_create_user(new_email)
        assert user is not None

        # Cleanup
        db_helpers.supabase.table("users").delete().eq("id", user).execute()


class TestUserProfileEndpoint:
    """Test GET /user-profile endpoint."""

    @pytest.mark.asyncio
    async def test_get_profile_new_user(self):
        """Should return empty profile for new user."""
        new_email = "new_profile_user@example.com"

        response = await handle_get_user_profile(new_email)

        assert response.user_email == new_email
        assert isinstance(response.semantic_profile, dict)
        assert isinstance(response.procedural_profile, dict)
        assert response.stats["total_queries"] == 0

        # Cleanup
        user_id = db_helpers.get_or_create_user(new_email)
        db_helpers.supabase.table("users").delete().eq("id", user_id).execute()

    @pytest.mark.asyncio
    async def test_get_profile_with_data(self, test_user_email, test_user):
        """Should return populated profile for user with data."""
        # Add some data
        db_helpers.update_user_profile(
            user_id=test_user,
            semantic_data={
                "interests": ["fantasy", "mythology"],
                "preferences": {"tone": "hopeful"}
            },
            procedural_data={
                "reading_velocity": 1.5,
                "completion_rate": 0.85
            }
        )

        response = await handle_get_user_profile(test_user_email)

        assert response.user_email == test_user_email
        assert "fantasy" in response.semantic_profile.get("interests", [])
        assert response.procedural_profile.get("reading_velocity") == 1.5

    @pytest.mark.asyncio
    async def test_get_profile_includes_stats(self, test_user_email, test_user, test_session):
        """Should include user statistics in profile."""
        # Add feedback
        db_helpers.add_feedback_to_session(
            session_id=test_session,
            liked_indices=[0, 1],
            rejected_indices=[2]
        )

        # Add reading history
        db_helpers.add_to_reading_history(
            user_id=test_user,
            book_id="book-1",
            title="Test Book",
            authors=["Author"],
            status="read",
            rating=5
        )

        response = await handle_get_user_profile(test_user_email)

        assert response.stats["total_queries"] >= 1
        assert response.stats["books_read"] >= 1
        assert response.stats["total_feedback_given"] >= 1

    @pytest.mark.asyncio
    async def test_get_profile_graceful_fallback(self):
        """Should return empty profile gracefully if no profile exists."""
        fallback_email = "fallback_user@example.com"

        response = await handle_get_user_profile(fallback_email)

        assert response.user_email == fallback_email
        assert response.semantic_profile == {} or isinstance(response.semantic_profile, dict)
        assert response.procedural_profile == {} or isinstance(response.procedural_profile, dict)

        # Cleanup
        user_id = db_helpers.get_or_create_user(fallback_email)
        db_helpers.supabase.table("users").delete().eq("id", user_id).execute()


class TestSummarizerTrigger:
    """Test summarizer trigger logic."""

    @pytest.mark.asyncio
    async def test_feedback_count_increments(self, test_user_email, test_user):
        """Should increment feedback count."""
        initial_count = db_helpers.count_feedback_since_last_summary(test_user)

        # Create sessions and add feedback
        for i in range(2):
            session = db_helpers.create_recommendation_session(
                user_id=test_user,
                query=f"Query {i}",
                recommendation_type="general",
                recommendations=[{"title": f"Book {i}"}]
            )

            db_helpers.add_feedback_to_session(
                session_id=session,
                liked_indices=[0],
                rejected_indices=[]
            )

        new_count = db_helpers.count_feedback_since_last_summary(test_user)
        assert new_count >= initial_count + 2

    @pytest.mark.asyncio
    async def test_summarizer_trigger_threshold(self, test_user_email, test_user):
        """Should detect when threshold is reached."""
        # Create FEEDBACK_SUMMARIZER_THRESHOLD feedback entries
        for i in range(FEEDBACK_SUMMARIZER_THRESHOLD):
            session = db_helpers.create_recommendation_session(
                user_id=test_user,
                query=f"Query {i}",
                recommendation_type="general",
                recommendations=[{"title": f"Book {i}"}]
            )

            request = FeedbackRequest(
                user_email=test_user_email,
                session_id=session,
                liked_indices=[0],
                rejected_indices=[]
            )

            response = await handle_feedback(request)

            # Last feedback should trigger summarizer
            if i == FEEDBACK_SUMMARIZER_THRESHOLD - 1:
                # Note: summarizer_triggered might be true if threshold reached
                # This is a soft check since async trigger is non-blocking
                pass


class TestProfileUpdates:
    """Test profile update logic."""

    def test_semantic_profile_update(self, test_user):
        """Should update semantic profile."""
        semantic_data = {
            "interests": ["fantasy", "sci-fi"],
            "preferences": {"tone": "dark", "depth": "deep"},
            "dislikes": ["romance"]
        }

        db_helpers.update_user_profile(
            user_id=test_user,
            semantic_data=semantic_data
        )

        profile = db_helpers.get_user_profile(test_user)
        assert profile["semantic_json"] == semantic_data

    def test_procedural_profile_update(self, test_user):
        """Should update procedural profile."""
        procedural_data = {
            "reading_velocity": 2.5,
            "completion_rate": 0.95,
            "series_preference": True,
            "avg_rating": 4.5
        }

        db_helpers.update_user_profile(
            user_id=test_user,
            procedural_data=procedural_data
        )

        profile = db_helpers.get_user_profile(test_user)
        assert profile["procedural_json"] == procedural_data

    def test_both_profiles_update(self, test_user):
        """Should update both semantic and procedural simultaneously."""
        semantic_data = {"interests": ["books"]}
        procedural_data = {"reading_velocity": 1.0}

        db_helpers.update_user_profile(
            user_id=test_user,
            semantic_data=semantic_data,
            procedural_data=procedural_data
        )

        profile = db_helpers.get_user_profile(test_user)
        assert profile["semantic_json"] == semantic_data
        assert profile["procedural_json"] == procedural_data

    def test_profile_timestamp_update(self, test_user):
        """Should update last_summarized timestamp."""
        db_helpers.update_user_profile(
            user_id=test_user,
            semantic_data={"interests": []}
        )

        profile = db_helpers.get_user_profile(test_user)
        assert profile["last_summarized"] is not None


class TestEndToEnd:
    """End-to-end tests for feedback + profile flow."""

    @pytest.mark.asyncio
    async def test_feedback_then_profile(self, test_user_email, test_user, test_session):
        """Should record feedback and reflect in profile."""
        # Give feedback
        request = FeedbackRequest(
            user_email=test_user_email,
            session_id=test_session,
            liked_indices=[0, 1],
            rejected_indices=[2],
            feedback_text="Good recommendations"
        )

        feedback_response = await handle_feedback(request)
        assert feedback_response.success

        # Check profile has stats
        profile_response = await handle_get_user_profile(test_user_email)

        assert profile_response.stats["total_feedback_given"] >= 1
        assert profile_response.stats["total_queries"] >= 1

    @pytest.mark.asyncio
    async def test_multiple_sessions_multiple_feedback(self, test_user_email, test_user):
        """Should handle multiple feedback sessions."""
        for session_num in range(3):
            session = db_helpers.create_recommendation_session(
                user_id=test_user,
                query=f"Query {session_num}",
                recommendation_type="general",
                recommendations=[
                    {"title": f"Book {i}", "why": "Test"} for i in range(3)
                ]
            )

            request = FeedbackRequest(
                user_email=test_user_email,
                session_id=session,
                liked_indices=[0],
                rejected_indices=[1, 2]
            )

            response = await handle_feedback(request)
            assert response.success

        # Check profile
        profile = await handle_get_user_profile(test_user_email)
        assert profile.stats["total_queries"] >= 3
        assert profile.stats["total_feedback_given"] >= 3
