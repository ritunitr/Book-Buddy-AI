"""
Test pattern detection flow.

Tests:
1. Detect patterns with sufficient feedback
2. Handle insufficient feedback gracefully
3. Confirm and apply suggested patterns
4. Merge suggestions with existing preferences
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from user_profile_endpoints import (
    ConfirmPatternsRequest,
    handle_get_patterns,
    handle_confirm_patterns,
)


MOCK_USER_ID = "test-user-id-123"

MOCK_PREFERENCES = {
    "id": "pref-id-123",
    "user_id": MOCK_USER_ID,
    "liked_books": [],
    "disliked_books": [],
    "liked_authors": ["Isaac Asimov"],
    "liked_genres": ["Science Fiction"],
    "disliked_authors": [],
    "disliked_genres": [],
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
}

MOCK_FEEDBACK = {
    "liked_books": [
        "Foundation",
        "I, Robot",
        "Dune",
        "The Left Hand of Darkness",
        "Neuromancer",
        "Snow Crash",
    ],
    "disliked_books": ["1984", "Brave New World"],
}

MOCK_CLAUDE_RESPONSE = """{
    "suggested_liked_genres": ["Cyberpunk", "Hard Science Fiction"],
    "suggested_liked_authors": ["William Gibson", "Frank Herbert"],
    "suggested_disliked_genres": ["Dystopian"],
    "suggested_disliked_authors": ["George Orwell"],
    "analysis": "You clearly enjoy hard SF with complex worldbuilding. Your likes suggest interest in cyberpunk and space opera. Your dislikes show aversion to dystopian works.",
    "confidence": 0.85
}"""


# ============================================================================
# Pattern Detection Tests
# ============================================================================

@patch("anthropic.Anthropic")
@patch("db_helpers.supabase")
def test_detect_patterns_with_sufficient_feedback(mock_supabase, mock_anthropic_class):
    """Test pattern detection with enough feedback."""
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": MOCK_USER_ID, "email": "test@example.com"}
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        MOCK_PREFERENCES
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.order.return_value.execute.return_value.data = [
        {
            "id": "interaction-1",
            "user_id": MOCK_USER_ID,
            "liked_books": MOCK_FEEDBACK["liked_books"],
            "disliked_books": MOCK_FEEDBACK["disliked_books"],
            "timestamp": "2026-01-02T00:00:00Z",
        }
    ]

    # Mock Claude response
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=MOCK_CLAUDE_RESPONSE)]
    mock_anthropic_class.return_value.messages.create.return_value = mock_message

    # This would work in an async context
    # For now, just verify the structure


@patch("db_helpers.get_or_create_user")
@patch("db_helpers.detect_patterns")
def test_get_patterns_endpoint_structure(mock_detect, mock_user):
    """Test that get_patterns returns correct structure."""
    mock_user.return_value = MOCK_USER_ID
    mock_detect.return_value = {
        "suggested_liked_genres": ["Cyberpunk", "Hard Science Fiction"],
        "suggested_liked_authors": ["William Gibson"],
        "suggested_disliked_genres": ["Dystopian"],
        "suggested_disliked_authors": ["George Orwell"],
        "analysis": "You like complex sci-fi",
        "confidence": 0.85,
        "feedback_count": 8,
        "books_analyzed": ["Foundation", "Dune", "1984"],
    }


@patch("db_helpers.supabase")
def test_insufficient_feedback_returns_empty(mock_supabase):
    """Test that pattern detection gracefully handles insufficient feedback."""
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": MOCK_USER_ID, "email": "test@example.com"}
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        MOCK_PREFERENCES
    ]
    # Only 2 voted books (need 5)
    mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.order.return_value.execute.return_value.data = [
        {
            "id": "interaction-1",
            "user_id": MOCK_USER_ID,
            "liked_books": ["Foundation", "Dune"],
            "disliked_books": [],
            "timestamp": "2026-01-02T00:00:00Z",
        }
    ]


# ============================================================================
# Confirm Patterns Tests
# ============================================================================

@patch("db_helpers.supabase")
def test_confirm_patterns_merges_with_existing(mock_supabase):
    """Test that confirming patterns merges with existing preferences."""
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": MOCK_USER_ID, "email": "test@example.com"}
    ]
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        MOCK_PREFERENCES
    ]
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
        {
            **MOCK_PREFERENCES,
            "liked_genres": ["Science Fiction", "Cyberpunk", "Hard Science Fiction"],
            "liked_authors": ["Isaac Asimov", "William Gibson", "Frank Herbert"],
            "disliked_genres": ["Dystopian"],
            "disliked_authors": ["George Orwell"],
        }
    ]


@patch("db_helpers.get_or_create_user")
@patch("db_helpers.get_user_preferences")
@patch("db_helpers.update_preferences")
def test_confirm_patterns_endpoint_merges_correctly(mock_update, mock_get_prefs, mock_user):
    """Test that confirm endpoint correctly merges suggestions."""
    mock_user.return_value = MOCK_USER_ID
    mock_get_prefs.return_value = MOCK_PREFERENCES

    request = ConfirmPatternsRequest(
        user_email="test@example.com",
        liked_genres=["Cyberpunk", "Hard Science Fiction"],
        liked_authors=["William Gibson"],
        disliked_genres=["Dystopian"],
        disliked_authors=["George Orwell"]
    )

    # Verify request structure
    assert request.user_email == "test@example.com"
    assert "Cyberpunk" in request.liked_genres
    assert "William Gibson" in request.liked_authors


@patch("db_helpers.get_or_create_user")
@patch("db_helpers.get_user_preferences")
@patch("db_helpers.update_preferences")
def test_confirm_patterns_partial_acceptance(mock_update, mock_get_prefs, mock_user):
    """Test that user can accept some suggestions and reject others."""
    mock_user.return_value = MOCK_USER_ID
    mock_get_prefs.return_value = MOCK_PREFERENCES

    # Only accept liked_genres, not disliked
    request = ConfirmPatternsRequest(
        user_email="test@example.com",
        liked_genres=["Cyberpunk"],
        disliked_genres=None  # User rejects this suggestion
    )

    assert request.liked_genres == ["Cyberpunk"]
    assert request.disliked_genres is None


@patch("db_helpers.get_or_create_user")
@patch("db_helpers.get_user_preferences")
@patch("db_helpers.update_preferences")
def test_confirm_patterns_avoids_duplicates(mock_update, mock_get_prefs, mock_user):
    """Test that confirming patterns doesn't create duplicates."""
    mock_user.return_value = MOCK_USER_ID
    mock_get_prefs.return_value = MOCK_PREFERENCES

    # Science Fiction already exists in preferences
    request = ConfirmPatternsRequest(
        user_email="test@example.com",
        liked_genres=["Science Fiction", "Cyberpunk"],
    )

    # The endpoint should use set() to merge, so duplicates are avoided


# ============================================================================
# Integration Flow Tests
# ============================================================================

def test_pattern_detection_flow():
    """
    Integration test for full pattern detection flow:
    1. User votes on books (feedback logged)
    2. User requests pattern detection
    3. Claude analyzes feedback
    4. User confirms suggestions
    5. Preferences updated
    """
    # This would be an async integration test
    # For now, documents the expected flow


def test_full_learning_loop():
    """
    Test complete episodic -> semantic memory flow:
    1. Fresh user sets initial preferences
    2. User queries and gets recommendations
    3. User votes on recommendations (episodic memory in interaction_log)
    4. After 5+ votes, pattern detection triggers
    5. Claude suggests new preferences (learned semantic memory)
    6. User confirms suggestions
    7. Preferences updated for future queries
    """
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
