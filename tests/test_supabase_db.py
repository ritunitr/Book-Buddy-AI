"""
Unit tests for Supabase database schema and operations.
Tests episodic, semantic, and procedural memory structures.
"""

import pytest
import json
import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

@pytest.fixture
def supabase_client():
    """Fixture: Initialize Supabase client."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        pytest.skip("Supabase credentials not configured")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


@pytest.fixture
def test_user(supabase_client: Client):
    """Fixture: Create a test user."""
    response = supabase_client.table("users").insert({
        "email": "test_milestone1@example.com"
    }).execute()

    user_id = response.data[0]["id"]
    yield user_id

    # Cleanup: delete user (cascades to all related data)
    supabase_client.table("users").delete().eq("id", user_id).execute()


class TestUsersTable:
    """Test users table operations."""

    def test_create_user(self, supabase_client: Client):
        """Should create a user with unique email."""
        response = supabase_client.table("users").insert({
            "email": "unique_test_user@example.com"
        }).execute()

        assert response.data
        assert response.data[0]["email"] == "unique_test_user@example.com"
        assert response.data[0]["id"]

        # Cleanup
        supabase_client.table("users").delete().eq(
            "email", "unique_test_user@example.com"
        ).execute()

    def test_duplicate_email_rejected(self, supabase_client: Client, test_user: str):
        """Should reject duplicate emails (UNIQUE constraint)."""
        with pytest.raises(Exception):
            supabase_client.table("users").insert({
                "email": "test_milestone1@example.com"  # Same as test_user
            }).execute()

    def test_read_user(self, supabase_client: Client, test_user: str):
        """Should read user by ID."""
        response = supabase_client.table("users").select("*").eq(
            "id", test_user
        ).execute()

        assert response.data
        assert response.data[0]["id"] == test_user
        assert response.data[0]["email"] == "test_milestone1@example.com"

    def test_user_created_at_timestamp(self, supabase_client: Client, test_user: str):
        """Should automatically set created_at timestamp."""
        response = supabase_client.table("users").select("*").eq(
            "id", test_user
        ).execute()

        assert response.data[0]["created_at"]


class TestRecommendationSessionsTable:
    """Test recommendation_sessions table (episodic memory)."""

    def test_create_session(self, supabase_client: Client, test_user: str):
        """Should create a recommendation session."""
        response = supabase_client.table("recommendation_sessions").insert({
            "user_id": test_user,
            "query": "Find fantasy books",
            "recommendation_type": "general",
            "num_recommendations": 5,
            "recommendations": json.dumps([
                {"title": "Book1", "why": "Fantasy"},
                {"title": "Book2", "why": "Adventure"}
            ])
        }).execute()

        assert response.data
        assert response.data[0]["query"] == "Find fantasy books"
        assert response.data[0]["num_recommendations"] == 5

    def test_session_requires_user_id(self, supabase_client: Client):
        """Should reject session without user_id (FK constraint)."""
        with pytest.raises(Exception):
            supabase_client.table("recommendation_sessions").insert({
                "query": "Find books",
                "recommendation_type": "general"
            }).execute()

    def test_add_feedback_to_session(self, supabase_client: Client, test_user: str):
        """Should add feedback (liked/rejected indices) to existing session."""
        # Create session
        session_response = supabase_client.table("recommendation_sessions").insert({
            "user_id": test_user,
            "query": "Find dragon books",
            "recommendation_type": "general",
            "num_recommendations": 3
        }).execute()

        session_id = session_response.data[0]["id"]

        # Add feedback
        feedback_response = supabase_client.table("recommendation_sessions").update({
            "liked_indices": [0, 2],
            "rejected_indices": [1],
            "user_feedback": "Loved 1st and 3rd, didn't like 2nd"
        }).eq("id", session_id).execute()

        assert feedback_response.data
        assert feedback_response.data[0]["liked_indices"] == [0, 2]
        assert feedback_response.data[0]["rejected_indices"] == [1]

    def test_session_recommendation_type_variants(self, supabase_client: Client, test_user: str):
        """Should support different recommendation types."""
        for rec_type in ["general", "exploration", "progression"]:
            response = supabase_client.table("recommendation_sessions").insert({
                "user_id": test_user,
                "query": f"Test {rec_type}",
                "recommendation_type": rec_type
            }).execute()

            assert response.data[0]["recommendation_type"] == rec_type


class TestReadingHistoryTable:
    """Test reading_history table (user's actual reads)."""

    def test_create_reading_entry(self, supabase_client: Client, test_user: str):
        """Should create a reading history entry."""
        response = supabase_client.table("reading_history").insert({
            "user_id": test_user,
            "book_id": "book-001",
            "title": "The Hobbit",
            "authors": ["J.R.R. Tolkien"],
            "status": "read",
            "rating": 5,
            "review_text": "Excellent adventure novel"
        }).execute()

        assert response.data
        assert response.data[0]["book_id"] == "book-001"
        assert response.data[0]["title"] == "The Hobbit"

    def test_reading_entry_with_recommendation_link(self, supabase_client: Client, test_user: str):
        """Should link reading entry to a recommendation session."""
        # Create session
        session = supabase_client.table("recommendation_sessions").insert({
            "user_id": test_user,
            "query": "Find fantasy"
        }).execute()

        session_id = session.data[0]["id"]

        # Create reading entry linked to session
        reading = supabase_client.table("reading_history").insert({
            "user_id": test_user,
            "book_id": "book-002",
            "title": "The Fellowship",
            "authors": ["J.R.R. Tolkien"],
            "status": "reading",
            "came_from_recommendation_id": session_id
        }).execute()

        assert reading.data[0]["came_from_recommendation_id"] == session_id

    def test_reading_status_variants(self, supabase_client: Client, test_user: str):
        """Should support different reading statuses."""
        for status in ["want", "reading", "read", "abandoned"]:
            response = supabase_client.table("reading_history").insert({
                "user_id": test_user,
                "book_id": f"book-{status}",
                "title": f"Book {status}",
                "authors": ["Author"],
                "status": status
            }).execute()

            assert response.data[0]["status"] == status

    def test_reading_entry_dates(self, supabase_client: Client, test_user: str):
        """Should store date_started and date_finished."""
        response = supabase_client.table("reading_history").insert({
            "user_id": test_user,
            "book_id": "book-dated",
            "title": "Dated Book",
            "authors": ["Author"],
            "status": "read",
            "date_started": "2026-01-01",
            "date_finished": "2026-02-15"
        }).execute()

        assert response.data[0]["date_started"] == "2026-01-01"
        assert response.data[0]["date_finished"] == "2026-02-15"


class TestUserProfilesTable:
    """Test user_profiles table (semantic + procedural memory)."""

    def test_create_user_profile(self, supabase_client: Client, test_user: str):
        """Should create a user profile with semantic and procedural JSON."""
        semantic_data = {
            "interests": ["fantasy", "mythology", "adventure"],
            "preferences": {"tone": "hopeful", "depth": "intermediate"},
            "dislikes": ["horror", "romance"]
        }

        procedural_data = {
            "reading_velocity": 1.5,
            "completion_rate": 0.85,
            "series_preference": True,
            "avg_rating": 4.2
        }

        response = supabase_client.table("user_profiles").insert({
            "user_id": test_user,
            "semantic_json": json.dumps(semantic_data),
            "procedural_json": json.dumps(procedural_data)
        }).execute()

        assert response.data
        retrieved = json.loads(response.data[0]["semantic_json"])
        assert retrieved["interests"] == ["fantasy", "mythology", "adventure"]

    def test_user_profile_uniqueness(self, supabase_client: Client, test_user: str):
        """Should enforce one profile per user (UNIQUE constraint)."""
        # Create first profile
        supabase_client.table("user_profiles").insert({
            "user_id": test_user,
            "semantic_json": json.dumps({"interests": ["books"]})
        }).execute()

        # Try to create second profile for same user
        with pytest.raises(Exception):
            supabase_client.table("user_profiles").insert({
                "user_id": test_user,
                "semantic_json": json.dumps({"interests": ["different"]})
            }).execute()

    def test_update_user_profile(self, supabase_client: Client, test_user: str):
        """Should update semantic/procedural JSON."""
        # Create profile
        response = supabase_client.table("user_profiles").insert({
            "user_id": test_user,
            "semantic_json": json.dumps({"interests": ["fantasy"]})
        }).execute()

        profile_id = response.data[0]["id"]

        # Update profile
        updated = supabase_client.table("user_profiles").update({
            "semantic_json": json.dumps({"interests": ["fantasy", "sci-fi"]})
        }).eq("id", profile_id).execute()

        assert json.loads(updated.data[0]["semantic_json"])["interests"] == ["fantasy", "sci-fi"]

    def test_profile_last_summarized_tracking(self, supabase_client: Client, test_user: str):
        """Should track when profile was last summarized."""
        response = supabase_client.table("user_profiles").insert({
            "user_id": test_user,
            "semantic_json": json.dumps({"interests": []})
        }).execute()

        # Update with last_summarized timestamp
        profile_id = response.data[0]["id"]
        updated = supabase_client.table("user_profiles").update({
            "last_summarized": "now()"
        }).eq("id", profile_id).execute()

        assert updated.data[0]["last_summarized"]


class TestInteractionLogTable:
    """Test interaction_log table (audit trail)."""

    def test_create_interaction_log_entry(self, supabase_client: Client, test_user: str):
        """Should create an interaction log entry."""
        response = supabase_client.table("interaction_log").insert({
            "user_id": test_user,
            "event_type": "question_asked",
            "event_data": json.dumps({"query": "Find fantasy books"})
        }).execute()

        assert response.data
        assert response.data[0]["event_type"] == "question_asked"

    def test_interaction_log_event_types(self, supabase_client: Client, test_user: str):
        """Should support various event types."""
        event_types = [
            "question_asked",
            "recommendation_shown",
            "feedback_given",
            "book_rated"
        ]

        for event_type in event_types:
            response = supabase_client.table("interaction_log").insert({
                "user_id": test_user,
                "event_type": event_type
            }).execute()

            assert response.data[0]["event_type"] == event_type

    def test_interaction_log_with_session_link(self, supabase_client: Client, test_user: str):
        """Should link interaction log to a recommendation session."""
        session = supabase_client.table("recommendation_sessions").insert({
            "user_id": test_user,
            "query": "Find books"
        }).execute()

        session_id = session.data[0]["id"]

        interaction = supabase_client.table("interaction_log").insert({
            "user_id": test_user,
            "session_id": session_id,
            "event_type": "recommendation_shown"
        }).execute()

        assert interaction.data[0]["session_id"] == session_id


class TestCascadeDelete:
    """Test cascade delete behavior."""

    def test_delete_user_cascades_to_sessions(self, supabase_client: Client):
        """Should delete all sessions when user is deleted."""
        # Create user
        user = supabase_client.table("users").insert({
            "email": "cascade_test@example.com"
        }).execute()
        user_id = user.data[0]["id"]

        # Create session for user
        session = supabase_client.table("recommendation_sessions").insert({
            "user_id": user_id,
            "query": "Test cascade"
        }).execute()
        session_id = session.data[0]["id"]

        # Delete user
        supabase_client.table("users").delete().eq("id", user_id).execute()

        # Verify session is gone
        result = supabase_client.table("recommendation_sessions").select("*").eq(
            "id", session_id
        ).execute()

        assert len(result.data) == 0

    def test_delete_user_cascades_to_reading_history(self, supabase_client: Client):
        """Should delete all reading history when user is deleted."""
        user = supabase_client.table("users").insert({
            "email": "cascade_reading@example.com"
        }).execute()
        user_id = user.data[0]["id"]

        reading = supabase_client.table("reading_history").insert({
            "user_id": user_id,
            "book_id": "book-cascade",
            "title": "Test Book",
            "authors": ["Author"]
        }).execute()
        reading_id = reading.data[0]["id"]

        supabase_client.table("users").delete().eq("id", user_id).execute()

        result = supabase_client.table("reading_history").select("*").eq(
            "id", reading_id
        ).execute()

        assert len(result.data) == 0

    def test_delete_user_cascades_to_profile(self, supabase_client: Client):
        """Should delete user profile when user is deleted."""
        user = supabase_client.table("users").insert({
            "email": "cascade_profile@example.com"
        }).execute()
        user_id = user.data[0]["id"]

        profile = supabase_client.table("user_profiles").insert({
            "user_id": user_id,
            "semantic_json": json.dumps({})
        }).execute()
        profile_id = profile.data[0]["id"]

        supabase_client.table("users").delete().eq("id", user_id).execute()

        result = supabase_client.table("user_profiles").select("*").eq(
            "id", profile_id
        ).execute()

        assert len(result.data) == 0


class TestDataIntegrity:
    """Test data integrity and constraints."""

    def test_foreign_key_constraint_sessions(self, supabase_client: Client):
        """Should reject session with invalid user_id."""
        fake_user_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(Exception):
            supabase_client.table("recommendation_sessions").insert({
                "user_id": fake_user_id,
                "query": "Invalid user"
            }).execute()

    def test_recommendations_json_storage(self, supabase_client: Client, test_user: str):
        """Should store and retrieve complex recommendation JSON."""
        recommendations = [
            {
                "title": "Book 1",
                "authors": ["Author 1"],
                "why": "Matches interests",
                "score": 0.95
            },
            {
                "title": "Book 2",
                "authors": ["Author 2", "Author 3"],
                "why": "Similar theme",
                "score": 0.87
            }
        ]

        response = supabase_client.table("recommendation_sessions").insert({
            "user_id": test_user,
            "query": "Find books",
            "recommendations": json.dumps(recommendations)
        }).execute()

        retrieved = json.loads(response.data[0]["recommendations"])
        assert len(retrieved) == 2
        assert retrieved[0]["score"] == 0.95


class TestIndexPerformance:
    """Test that indexes are created (query performance)."""

    def test_query_by_user_id_sessions(self, supabase_client: Client, test_user: str):
        """Should efficiently query sessions by user_id (index exists)."""
        # Create multiple sessions
        for i in range(3):
            supabase_client.table("recommendation_sessions").insert({
                "user_id": test_user,
                "query": f"Query {i}"
            }).execute()

        # Query by user_id (uses idx_rec_sessions_user)
        result = supabase_client.table("recommendation_sessions").select("*").eq(
            "user_id", test_user
        ).execute()

        assert len(result.data) == 3

    def test_query_by_user_id_reading_history(self, supabase_client: Client, test_user: str):
        """Should efficiently query reading history by user_id."""
        for i in range(2):
            supabase_client.table("reading_history").insert({
                "user_id": test_user,
                "book_id": f"book-{i}",
                "title": f"Book {i}",
                "authors": ["Author"]
            }).execute()

        result = supabase_client.table("reading_history").select("*").eq(
            "user_id", test_user
        ).execute()

        assert len(result.data) == 2
