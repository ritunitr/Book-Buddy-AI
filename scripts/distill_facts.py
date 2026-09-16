"""
Distillation Job - Converts episodic memory (interaction_log) to semantic memory (fact).

Runs as a Render background worker on a cron schedule.
For each user with undistilled interactions, generates a comprehensive fact summary.

Usage:
    python distill_facts.py
"""

import db_helpers
from anthropic import Anthropic

MODEL = "claude-3-5-sonnet-20241022"


def generate_fact_for_user(user_id: str) -> str:
    """
    Generate a semantic memory fact from user's episodic feedback.

    Reads all liked/disliked books from interaction_log and generates
    a coherent text summary (the fact) that captures the user's reading preferences.

    Args:
        user_id: User ID

    Returns:
        Generated fact as text
    """
    feedback = db_helpers.get_all_feedback(user_id)
    prefs = db_helpers.get_user_preferences(user_id)

    liked_books = feedback.get("liked_books", [])
    disliked_books = feedback.get("disliked_books", [])

    if not liked_books and not disliked_books:
        return None  # No feedback yet

    # Current fact (if any)
    current_fact = prefs.get("fact", "")

    prompt = f"""Based on this user's book preferences, generate a concise, insightful fact about their reading taste.

Books they LIKED:
{chr(10).join(f"- {book}" for book in liked_books)}

Books they DISLIKED:
{chr(10).join(f"- {book}" for book in disliked_books)}

{f'Previous fact (update if needed): {current_fact}' if current_fact else ''}

Generate a 1-2 sentence fact that:
1. Describes their reading preferences and themes they enjoy
2. Notes what they avoid
3. Could be used to personalize recommendations

Be specific and concrete. Example format:
"User enjoys epic fantasy with complex magic systems (Sanderson, Rothfuss) and hard sci-fi exploring consciousness (Gibson, Asimov). Avoids grimdark and horror."

Generate ONLY the fact, no preamble."""

    client = Anthropic()

    message = client.messages.create(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text.strip()


def distill_all_users():
    """
    Main distillation process.

    For each user with undistilled interactions:
    1. Generate fact from feedback
    2. Update user_preferences with fact
    3. Mark interactions as distilled
    """
    print("🔄 Starting distillation job...")

    # Get users with undistilled interactions
    undistilled_users = db_helpers.get_undistilled_users()

    if not undistilled_users:
        print("✓ No undistilled interactions found.")
        return

    print(f"✓ Found {len(undistilled_users)} users with new feedback\n")

    successful = 0
    failed = 0

    for user_id in undistilled_users:
        try:
            print(f"Processing user {user_id}...")

            # Generate fact from feedback
            fact = generate_fact_for_user(user_id)

            if fact:
                # Update preferences with fact
                db_helpers.update_preference_fact(user_id, fact)
                print(f"  ✓ Fact generated: {fact[:60]}...")

                # Mark as distilled
                count = db_helpers.mark_interactions_as_distilled(user_id)
                print(f"  ✓ Marked {count} interactions as distilled\n")

                successful += 1
            else:
                print(f"  ⊘ No feedback for user (skipped)\n")

        except Exception as e:
            print(f"  ✗ Error: {str(e)}\n")
            failed += 1

    print("="*60)
    print(f"Distillation complete: {successful} successful, {failed} failed")
    print("="*60)


if __name__ == "__main__":
    distill_all_users()
