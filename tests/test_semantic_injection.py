"""
Unit tests for Semantic Profile Injection and Unread Filtering

Tests that user profiles are correctly injected into recommendations
and that already-read books are filtered out.
"""

import pytest
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import db_helpers
from semantic_injection import (
    build_semantic_context,
    build_unread_filter_context,
    get_personalization_prompt_section,
    personalize_recommendation_prompt,
    filter_candidates_by_profile
)

load_dotenv()


@pytest.fixture
def test_user_email():
    """Fixture: Test user email."""
    return "test_semantic_user@example.com"


@pytest.fixture
def test_user(test_user_email):
    """Fixture: Create test user with profile."""
    user_id = db_helpers.get_or_create_user(test_user_email)
    db_helpers.get_or_create_user_profile(user_id)
    yield user_id

    # Cleanup
    supabase = db_helpers.supabase
    supabase.table("users").delete().eq("id", user_id).execute()


@pytest.fixture
def sample_candidate_books():
    """Fixture: Sample candidate books."""
    return [
        {"book_id": "book-1", "title": "The Hobbit", "authors": ["Tolkien"]},
        {"book_id": "book-2", "title": "Dune", "authors": ["Herbert"]},
        {"book_id": "book-3", "title": "Foundation", "authors": ["Asimov"]},
        {"book_id": "book-4", "title": "1984", "authors": ["Orwell"]},
        {"book_id": "book-5", "title": "Pride and Prejudice", "authors": ["Austen"]}
    ]


class TestSemanticContextBuilding:
    """Test building semantic context from user profile."""

    def test_empty_profile_returns_empty_context(self, test_user_email):
        """Should return empty string for user with no profile."""
        context = build_semantic_context(test_user_email)
        assert context == ""

    def test_profile_with_interests(self, test_user, test_user_email):
        """Should include interests in context."""
        db_helpers.update_user_profile(
            user_id=test_user,
            semantic_data={
                "interests": ["fantasy", "sci-fi", "adventure"]
            }
        )

        context = build_semantic_context(test_user_email)

        assert "Interests" in context
        assert "fantasy" in context
        assert "sci-fi" in context

    def test_profile_with_preferences(self, test_user, test_user_email):
        """Should include preferences in context."""
        db_helpers.update_user_profile(
            user_id=test_user,
            semantic_data={
                "preferences": {"tone": "hopeful", "depth": "intermediate", "pacing": "fast"}
            }
        )

        context = build_semantic_context(test_user_email)

        assert "Preferences" in context
        assert "tone: hopeful" in context
        assert "depth: intermediate" in context

    def test_profile_with_dislikes(self, test_user, test_user_email):
        """Should include dislikes in context."""
        db_helpers.update_user_profile(
            user_id=test_user,
            semantic_data={
                "dislikes": ["horror", "romance"]
            }
        )

        context = build_semantic_context(test_user_email)

        assert "Dislikes" in context
        assert "horror" in context
        assert "romance" in context

    def test_profile_with_procedural_data(self, test_user, test_user_email):
        """Should include procedural patterns in context."""
        db_helpers.update_user_profile(
            user_id=test_user,
            procedural_data={
                "reading_velocity": 2.5,
                "series_preference": True,
                "completion_rate": 0.85
            }
        )

        context = build_semantic_context(test_user_email)

        assert "2.5 books/month" in context
        assert "prefers series" in context
        assert "85%" in context

    def test_complete_profile_context(self, test_user, test_user_email):
        """Should build complete context from full profile."""
        db_helpers.update_user_profile(
            user_id=test_user,
            semantic_data={
                "interests": ["fantasy"],
                "preferences": {"tone": "dark"},
                "dislikes": ["horror"]
            },
            procedural_data={
                "reading_velocity": 1.5,
                "series_preference": False,
                "completion_rate": 0.9
            }
        )

        context = build_semantic_context(test_user_email)

        assert "User Profile:" in context
        assert "Interests" in context
        assert "Preferences" in context
        assert "Dislikes" in context
        assert "Reading pace" in context
        assert "Series preference" in context
        assert "Completion rate" in context


class TestUnreadFiltering:
    """Test filtering out books user has already read."""

    def test_no_reading_history_returns_all(self, test_user_email, sample_candidate_books):
        """Should return all books if user has no reading history."""
        filtered, context = build_unread_filter_context(test_user_email, sample_candidate_books)

        assert len(filtered) == len(sample_candidate_books)
        assert context == ""

    def test_filters_read_books(self, test_user, test_user_email, sample_candidate_books):
        """Should exclude books user has read."""
        # Mark first 2 books as read
        for i in range(2):
            db_helpers.add_to_reading_history(
                user_id=test_user,
                book_id=sample_candidate_books[i]["book_id"],
                title=sample_candidate_books[i]["title"],
                authors=sample_candidate_books[i]["authors"],
                status="read"
            )

        filtered, context = build_unread_filter_context(test_user_email, sample_candidate_books)

        assert len(filtered) == 3  # 5 - 2 = 3
        assert "book-1" not in [b.get("book_id") for b in filtered]
        assert "book-2" not in [b.get("book_id") for b in filtered]
        assert "Filtered out 2 books" in context

    def test_filters_in_progress_books(self, test_user, test_user_email, sample_candidate_books):
        """Should exclude books user is currently reading."""
        db_helpers.add_to_reading_history(
            user_id=test_user,
            book_id=sample_candidate_books[0]["book_id"],
            title=sample_candidate_books[0]["title"],
            authors=sample_candidate_books[0]["authors"],
            status="reading"
        )

        filtered, context = build_unread_filter_context(test_user_email, sample_candidate_books)

        assert len(filtered) == 4
        assert "book-1" not in [b.get("book_id") for b in filtered]

    def test_includes_abandoned_books(self, test_user, test_user_email, sample_candidate_books):
        """Should NOT exclude books user abandoned (ok to recommend similar)."""
        db_helpers.add_to_reading_history(
            user_id=test_user,
            book_id=sample_candidate_books[0]["book_id"],
            title=sample_candidate_books[0]["title"],
            authors=sample_candidate_books[0]["authors"],
            status="abandoned"
        )

        filtered, context = build_unread_filter_context(test_user_email, sample_candidate_books)

        # Abandoned books ARE included (user might want similar but better books)
        assert len(filtered) == 5

    def test_includes_wishlist_books(self, test_user, test_user_email, sample_candidate_books):
        """Should NOT exclude books in user's wishlist."""
        db_helpers.add_to_reading_history(
            user_id=test_user,
            book_id=sample_candidate_books[0]["book_id"],
            title=sample_candidate_books[0]["title"],
            authors=sample_candidate_books[0]["authors"],
            status="want"
        )

        filtered, context = build_unread_filter_context(test_user_email, sample_candidate_books)

        # Wishlist books are still candidates
        assert len(filtered) == 5


class TestPersonalizationPrompt:
    """Test prompt personalization."""

    def test_no_profile_returns_original_query(self, test_user_email):
        """Should return original query if no profile."""
        query = "Find fantasy books"
        personalized = personalize_recommendation_prompt(query, test_user_email)

        assert personalized == query

    def test_with_profile_enhances_query(self, test_user, test_user_email):
        """Should enhance query with profile when available."""
        db_helpers.update_user_profile(
            user_id=test_user,
            semantic_data={"interests": ["fantasy"]}
        )

        query = "Find fantasy books"
        personalized = personalize_recommendation_prompt(query, test_user_email)

        assert query in personalized
        assert "User Profile:" in personalized
        assert "Interests" in personalized

    def test_none_email_returns_original_query(self):
        """Should handle None email gracefully."""
        query = "Find books"
        personalized = personalize_recommendation_prompt(query, None)

        assert personalized == query


class TestFilterCandidatesByProfile:
    """Test filtering candidates with metadata."""

    def test_filter_returns_metadata(self, test_user, test_user_email, sample_candidate_books):
        """Should return filtered books and metadata."""
        # Mark 2 books as read
        for i in range(2):
            db_helpers.add_to_reading_history(
                user_id=test_user,
                book_id=sample_candidate_books[i]["book_id"],
                title=sample_candidate_books[i]["title"],
                authors=sample_candidate_books[i]["authors"],
                status="read"
            )

        filtered, metadata = filter_candidates_by_profile(test_user_email, sample_candidate_books)

        assert metadata["original_count"] == 5
        assert metadata["filtered_out_count"] == 2
        assert metadata["final_count"] == 3
        assert len(filtered) == 3

    def test_metadata_with_no_filtering(self, test_user_email, sample_candidate_books):
        """Should show zero filtering if no reading history."""
        filtered, metadata = filter_candidates_by_profile(test_user_email, sample_candidate_books)

        assert metadata["original_count"] == 5
        assert metadata["filtered_out_count"] == 0
        assert metadata["final_count"] == 5

    def test_filter_context_messages(self, test_user, test_user_email, sample_candidate_books):
        """Should include helpful filter context messages."""
        db_helpers.add_to_reading_history(
            user_id=test_user,
            book_id=sample_candidate_books[0]["book_id"],
            title=sample_candidate_books[0]["title"],
            authors=sample_candidate_books[0]["authors"],
            status="read"
        )

        filtered, metadata = filter_candidates_by_profile(test_user_email, sample_candidate_books)

        assert "Filtered out" in metadata["filter_context"]


class TestEndToEndPersonalization:
    """End-to-end tests for semantic injection + filtering."""

    def test_personalize_and_filter_together(self, test_user, test_user_email, sample_candidate_books):
        """Should personalize prompt and filter candidates together."""
        # Set up user profile
        db_helpers.update_user_profile(
            user_id=test_user,
            semantic_data={
                "interests": ["sci-fi", "fantasy"],
                "dislikes": ["romance"]
            },
            procedural_data={
                "reading_velocity": 1.5
            }
        )

        # Mark books as read
        db_helpers.add_to_reading_history(
            user_id=test_user,
            book_id="book-1",
            title=sample_candidate_books[0]["title"],
            authors=sample_candidate_books[0]["authors"],
            status="read"
        )

        # Get personalized prompt
        query = "Find good sci-fi"
        personalized_prompt = personalize_recommendation_prompt(query, test_user_email)

        assert "User Profile:" in personalized_prompt
        assert "sci-fi" in personalized_prompt

        # Filter candidates
        filtered, metadata = filter_candidates_by_profile(test_user_email, sample_candidate_books)

        assert metadata["filtered_out_count"] >= 1
        assert len(filtered) < len(sample_candidate_books)

    def test_new_user_no_personalization(self, sample_candidate_books):
        """Should gracefully handle completely new user."""
        new_email = "brand_new_user@example.com"

        # Personalize (should be no-op)
        query = "Find books"
        personalized = personalize_recommendation_prompt(query, new_email)
        assert personalized == query

        # Filter (should be no-op)
        filtered, metadata = filter_candidates_by_profile(new_email, sample_candidate_books)
        assert len(filtered) == len(sample_candidate_books)
        assert metadata["filtered_out_count"] == 0

        # Cleanup
        user_id = db_helpers.get_or_create_user(new_email)
        db_helpers.supabase.table("users").delete().eq("id", user_id).execute()
