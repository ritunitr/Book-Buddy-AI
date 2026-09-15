"""
Demo script to test pattern detection with real database.

Tests:
1. Create test user
2. Add sample feedback to interaction_log
3. Call detect_patterns() and show suggestions
4. Confirm suggestions and update user_preferences
5. Verify database updates
"""

import sys
from datetime import datetime
import db_helpers

# Test user email
TEST_EMAIL = "pattern_test@example.com"


def print_section(title):
    """Print formatted section header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def test_pattern_detection():
    """End-to-end pattern detection test."""

    # Step 1: Create or get user
    print_section("Step 1: Create/Get User")
    user_id = db_helpers.get_or_create_user(TEST_EMAIL)
    print(f"✓ User created/retrieved: {user_id}")
    print(f"  Email: {TEST_EMAIL}")

    # Step 2: Initialize preferences
    print_section("Step 2: Initialize User Preferences")
    prefs = db_helpers.get_or_create_preferences(user_id)
    print(f"✓ Preferences initialized")
    print(f"  Liked genres: {prefs.get('liked_genres', [])}")
    print(f"  Liked authors: {prefs.get('liked_authors', [])}")

    # Step 3: Add sample feedback to interaction_log
    print_section("Step 3: Add Sample Feedback")
    sample_feedback = [
        {
            "liked": ["The Hobbit", "Foundation", "Dune"],
            "disliked": ["1984", "Brave New World"]
        },
        {
            "liked": ["The Fifth Season", "Neuromancer", "Snow Crash"],
            "disliked": []
        },
        {
            "liked": ["Mistborn", "The Way of Kings"],
            "disliked": ["The Lord of the Rings (too long)"]
        }
    ]

    for i, feedback in enumerate(sample_feedback, 1):
        interaction_id = db_helpers.log_feedback(
            user_id=user_id,
            liked_books=feedback["liked"],
            disliked_books=feedback["disliked"]
        )
        print(f"✓ Interaction {i} logged: {interaction_id}")
        print(f"  Liked: {feedback['liked']}")
        print(f"  Disliked: {feedback['disliked']}")

    # Step 4: Get feedback summary
    print_section("Step 4: View Feedback History")
    all_feedback = db_helpers.get_all_feedback(user_id)
    print(f"✓ Total liked books: {len(all_feedback['liked_books'])}")
    for book in all_feedback['liked_books']:
        print(f"  - {book}")
    print(f"\n✓ Total disliked books: {len(all_feedback['disliked_books'])}")
    for book in all_feedback['disliked_books']:
        print(f"  - {book}")

    # Step 5: Detect patterns using Claude
    print_section("Step 5: Detect Patterns (Claude Analysis)")
    print("Sending feedback to Claude for analysis...")
    patterns = db_helpers.detect_patterns(user_id)

    print(f"\n✓ Pattern Detection Complete!")
    print(f"  Confidence: {patterns.get('confidence', 0):.2f}")
    print(f"  Analysis: {patterns.get('analysis', '')}")

    print(f"\n  Suggested Liked Genres:")
    for genre in patterns.get('suggested_liked_genres', []):
        print(f"    - {genre}")

    print(f"\n  Suggested Liked Authors:")
    for author in patterns.get('suggested_liked_authors', []):
        print(f"    - {author}")

    print(f"\n  Suggested Disliked Genres:")
    for genre in patterns.get('suggested_disliked_genres', []):
        print(f"    - {genre}")

    print(f"\n  Suggested Disliked Authors:")
    for author in patterns.get('suggested_disliked_authors', []):
        print(f"    - {author}")

    # Step 6: Accept suggestions (selective)
    print_section("Step 6: Accept Suggestions & Update Preferences")
    to_accept = {
        "liked_genres": patterns.get('suggested_liked_genres', []),
        "liked_authors": patterns.get('suggested_liked_authors', []),
        "disliked_genres": patterns.get('suggested_disliked_genres', [])
    }

    db_helpers.update_preferences(user_id, to_accept)
    print(f"✓ Preferences updated with suggestions")

    # Step 7: Verify database update
    print_section("Step 7: Verify Database Update")
    updated_prefs = db_helpers.get_user_preferences(user_id)
    print(f"✓ Current Preferences:")
    print(f"  Liked genres: {updated_prefs.get('liked_genres', [])}")
    print(f"  Liked authors: {updated_prefs.get('liked_authors', [])}")
    print(f"  Disliked genres: {updated_prefs.get('disliked_genres', [])}")

    # Step 8: Get user stats
    print_section("Step 8: User Statistics")
    stats = db_helpers.get_user_stats(user_id)
    print(f"✓ User Stats:")
    print(f"  Total interactions: {stats.get('total_interactions', 0)}")
    print(f"  Liked books in preferences: {stats.get('liked_books', 0)}")
    print(f"  Disliked books in preferences: {stats.get('disliked_books', 0)}")
    print(f"  Liked genres: {stats.get('liked_genres', 0)}")
    print(f"  Liked authors: {stats.get('liked_authors', 0)}")
    print(f"  Disliked genres: {stats.get('disliked_genres', 0)}")
    print(f"  Last updated: {stats.get('updated_at', 'N/A')}")

    print_section("✅ Demo Complete!")
    print(f"Test user: {TEST_EMAIL}")
    print(f"User ID: {user_id}")
    print("\nYou can now check the database to verify all tables were updated correctly:")
    print("- user_profile table: user created")
    print("- interaction_log table: 3 feedback sessions logged")
    print("- user_preferences table: preferences updated with patterns")


if __name__ == "__main__":
    try:
        test_pattern_detection()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
