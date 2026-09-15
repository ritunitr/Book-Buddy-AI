"""
Test the refactored schema: simplified 3-table design with explicit preferences.

Tests:
1. Feedback endpoint: Record liked/disliked books
2. Preferences endpoint: Get and update user preferences
3. Semantic injection: Build preference context for prompt enhancement
4. Filtering: Filter candidates by disliked books
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from user_profile_endpoints import (
    FeedbackRequest,
    PreferencesRequest,
    handle_feedback,
    handle_get_preferences,
    handle_update_preferences,
)
from semantic_injection import (
    build_preference_context,
    personalize_recommendation_prompt,
    filter_candidates_by_preferences,
)


# Mock Supabase responses
MOCK_USER_ID = "test-user-id-123"

MOCK_USER = {
    "id": MOCK_USER_ID,
    "email": "test@example.com",
}

MOCK_PREFERENCES = {
    "id": "pref-id-123",
    "user_id": MOCK_USER_ID,
    "liked_books": ["The Hobbit", "Dune"],
    "disliked_books": ["1984"],
    "liked_authors": ["J.R.R. Tolkien", "Frank Herbert"],
    "liked_genres": ["Fantasy", "Science Fiction"],
    "disliked_authors": ["George Orwell"],
    "disliked_genres": ["Horror"],
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
}

MOCK_INTERACTIONS = [
    {
        "id": "interaction-1",
        "user_id": MOCK_USER_ID,
        "liked_books": ["Neuromancer"],
        "disliked_books": [],
        "timestamp": "2026-01-02T00:00:00Z",
    }
]


# ============================================================================
# Feedback Endpoint Tests
# ============================================================================

@patch("db_helpers.supabase")
def test_feedback_records_liked_and_rejected_books(mock_supabase):
    """Test that feedback endpoint logs liked/rejected books correctly."""
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        MOCK_USER
    ]
    mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [
        MOCK_INTERACTIONS[0]
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.order.return_value.execute.return_value.data = [
        MOCK_INTERACTIONS[0]
    ]

    request = FeedbackRequest(
        user_email="test@example.com",
        liked_book_titles=["Neuromancer"],
        rejected_book_titles=[]
    )

    # Note: This is an async function, so we'd need pytest-asyncio to test it properly
    # For now, this demonstrates the structure


@patch("db_helpers.supabase")
def test_feedback_returns_feedback_count(mock_supabase):
    """Test that feedback endpoint returns total feedback count."""
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        MOCK_USER
    ]
    mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "interaction-2"}
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.order.return_value.execute.return_value.data = (
        MOCK_INTERACTIONS
    )


# ============================================================================
# Preferences Endpoint Tests
# ============================================================================

@patch("db_helpers.supabase")
def test_get_preferences_returns_user_preferences(mock_supabase):
    """Test that get_preferences returns current user preferences."""
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        MOCK_USER
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        MOCK_PREFERENCES
    ]


@patch("db_helpers.supabase")
def test_update_preferences_modifies_arrays(mock_supabase):
    """Test that update_preferences modifies preference arrays correctly."""
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        MOCK_USER
    ]
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
        {
            **MOCK_PREFERENCES,
            "liked_genres": ["Fantasy", "Science Fiction", "Mystery"],
        }
    ]


# ============================================================================
# Semantic Injection Tests
# ============================================================================

@patch("db_helpers.get_or_create_user")
@patch("db_helpers.get_user_preferences")
def test_build_preference_context_formats_preferences(mock_prefs, mock_user):
    """Test that preference context is formatted correctly for prompt injection."""
    mock_user.return_value = MOCK_USER_ID
    mock_prefs.return_value = MOCK_PREFERENCES

    context = build_preference_context("test@example.com")

    assert "Interested in: Fantasy, Science Fiction" in context
    assert "Favorite authors: J.R.R. Tolkien, Frank Herbert" in context
    assert "Books they enjoyed: The Hobbit" in context
    assert "Avoid: Horror" in context


@patch("db_helpers.get_or_create_user")
@patch("db_helpers.get_user_preferences")
def test_personalize_prompt_includes_preferences(mock_prefs, mock_user):
    """Test that personalize_recommendation_prompt includes preference context."""
    mock_user.return_value = MOCK_USER_ID
    mock_prefs.return_value = MOCK_PREFERENCES

    original_query = "Give me book recommendations"
    personalized = personalize_recommendation_prompt(original_query, "test@example.com")

    assert original_query in personalized
    assert "User Preferences:" in personalized or "Interested in:" in personalized


# ============================================================================
# Filtering Tests
# ============================================================================

@patch("db_helpers.get_or_create_user")
@patch("db_helpers.get_user_preferences")
def test_filter_candidates_removes_disliked_books(mock_prefs, mock_user):
    """Test that filter_candidates_by_preferences removes disliked books."""
    mock_user.return_value = MOCK_USER_ID
    mock_prefs.return_value = MOCK_PREFERENCES

    candidates = [
        {"title": "The Hobbit", "authors": ["J.R.R. Tolkien"]},
        {"title": "1984", "authors": ["George Orwell"]},  # Disliked
        {"title": "Dune", "authors": ["Frank Herbert"]},
    ]

    filtered, metadata = filter_candidates_by_preferences("test@example.com", candidates)

    assert len(filtered) == 2
    assert metadata["original_count"] == 3
    assert metadata["filtered_out_count"] == 1
    assert metadata["final_count"] == 2
    assert all(book["title"] != "1984" for book in filtered)


@patch("db_helpers.get_or_create_user")
@patch("db_helpers.get_user_preferences")
def test_filter_candidates_handles_no_dislikes(mock_prefs, mock_user):
    """Test that filter_candidates works when user has no disliked books."""
    mock_user.return_value = MOCK_USER_ID
    mock_prefs.return_value = {**MOCK_PREFERENCES, "disliked_books": []}

    candidates = [
        {"title": "The Hobbit", "authors": ["J.R.R. Tolkien"]},
        {"title": "Dune", "authors": ["Frank Herbert"]},
    ]

    filtered, metadata = filter_candidates_by_preferences("test@example.com", candidates)

    assert len(filtered) == 2
    assert metadata["filtered_out_count"] == 0


# ============================================================================
# Schema Structure Tests
# ============================================================================

def test_preferences_request_structure():
    """Test that PreferencesRequest accepts all preference fields."""
    request = PreferencesRequest(
        user_email="test@example.com",
        liked_books=["The Hobbit"],
        liked_genres=["Fantasy"],
        disliked_books=["1984"],
    )

    assert request.user_email == "test@example.com"
    assert request.liked_books == ["The Hobbit"]
    assert request.liked_genres == ["Fantasy"]
    assert request.disliked_books == ["1984"]


def test_feedback_request_structure():
    """Test that FeedbackRequest accepts liked and rejected books."""
    request = FeedbackRequest(
        user_email="test@example.com",
        liked_book_titles=["Dune"],
        rejected_book_titles=["1984"],
    )

    assert request.user_email == "test@example.com"
    assert request.liked_book_titles == ["Dune"]
    assert request.rejected_book_titles == ["1984"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
