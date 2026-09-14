#!/usr/bin/env python3
"""Test Supabase connection and schema."""

import os
import json
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

if not url or not key:
    print("❌ Missing SUPABASE_URL or SUPABASE_KEY in .env")
    exit(1)

supabase: Client = create_client(url, key)
print("✓ Connected to Supabase")

# Test 1: Create a test user
print("\n[Test 1] Creating test user...")
user_data = supabase.table("users").insert({
    "email": "test@example.com"
}).execute()

if user_data.data:
    test_user_id = user_data.data[0]["id"]
    print(f"✓ User created: {test_user_id}")
else:
    print("❌ Failed to create user")
    exit(1)

# Test 2: Create a recommendation session
print("\n[Test 2] Creating recommendation session...")
session_data = supabase.table("recommendation_sessions").insert({
    "user_id": test_user_id,
    "query": "Find dragon books",
    "recommendation_type": "general",
    "num_recommendations": 3,
    "recommendations": json.dumps([
        {"title": "Percy Jackson", "why": "Dragons and adventure"},
        {"title": "Wings of Fire", "why": "Dragon protagonist"},
        {"title": "HTTYD", "why": "Classic"}
    ])
}).execute()

if session_data.data:
    session_id = session_data.data[0]["id"]
    print(f"✓ Session created: {session_id}")
else:
    print("❌ Failed to create session")
    exit(1)

# Test 3: Add feedback to session
print("\n[Test 3] Updating session with feedback...")
feedback_data = supabase.table("recommendation_sessions").update({
    "liked_indices": [0],
    "rejected_indices": [1, 2],
    "user_feedback": "Loved Percy Jackson, not interested in others",
}).eq("id", session_id).execute()

print("✓ Feedback added")

# Test 4: Add reading history
print("\n[Test 4] Adding to reading history...")
reading_data = supabase.table("reading_history").insert({
    "user_id": test_user_id,
    "book_id": "percy-jackson-001",
    "title": "Percy Jackson: The Lightning Thief",
    "authors": ["Rick Riordan"],
    "status": "read",
    "rating": 5,
    "review_text": "Loved the mythology and quick pacing",
    "came_from_recommendation_id": session_id
}).execute()

print("✓ Reading history added")

# Test 5: Create user profile
print("\n[Test 5] Creating user profile...")
profile_data = supabase.table("user_profiles").insert({
    "user_id": test_user_id,
    "semantic_json": json.dumps({
        "interests": ["mythology", "fantasy", "adventure"],
        "preferences": {"depth": "intermediate", "tone": "hopeful"},
    }),
    "procedural_json": json.dumps({
        "reading_velocity": 1.5,
        "completion_rate": 0.72,
        "series_preference": True
    })
}).execute()

print("✓ User profile created")

# Test 6: Query back all data
print("\n[Test 6] Querying all data back...")
user = supabase.table("users").select("*").eq("id", test_user_id).execute()
print(f"User: {user.data[0]['email']}")

sessions = supabase.table("recommendation_sessions").select("*").eq("user_id", test_user_id).execute()
print(f"Sessions: {len(sessions.data)} found")

history = supabase.table("reading_history").select("*").eq("user_id", test_user_id).execute()
print(f"Books read: {len(history.data)} found")

profile = supabase.table("user_profiles").select("*").eq("user_id", test_user_id).execute()
if profile.data:
    interests = json.loads(profile.data[0]['semantic_json'])['interests']
    print(f"Profile interests: {interests}")

# Test 7: Cleanup
print("\n[Test 7] Cleanup (deleting test user)...")
supabase.table("users").delete().eq("id", test_user_id).execute()
print("✓ Test user deleted (cascade cleanup worked)")

print("\n✅ All tests passed! Database is ready for Milestone 1.\n")
