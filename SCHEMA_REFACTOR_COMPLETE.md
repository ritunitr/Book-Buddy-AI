# Schema Refactor Complete ✓

## Summary

Refactored from complex 4-table schema (20+ fields) to simple 3-table schema with explicit user preferences. This simplifies the codebase and aligns with MVP learning goals about episodic, semantic, and procedural memory.

### Old Schema (Removed)
- `user_profiles`: 20+ fields including semantic_json, procedural_json
- `reading_history`: complex tracking of read/reading/abandoned/want statuses
- Session tracking with complex event types and event data

### New Schema (In Use)
1. **users** (existing): `id`, `email`
2. **user_preferences** (new): explicit preferences for recommendations
3. **interaction_log** (new): episodic feedback from recommendation sessions

---

## What Changed

### Files Modified

#### 1. db_helpers.py ✓ COMPLETE
Completely rewritten with new functions:
- `get_or_create_preferences(user_id)` — Get or create user preference record
- `get_user_preferences(user_id)` — Fetch current preferences
- `update_preferences(user_id, preferences)` — Update preference arrays
- `add_to_preferences(user_id, field, value)` — Add single item to array
- `log_feedback(user_id, liked_books, disliked_books)` — Log session feedback
- `get_recent_interactions(user_id, limit)` — Get recent feedback
- `get_all_feedback(user_id)` — Aggregate all liked/disliked from history
- `detect_patterns(user_id)` — Placeholder for LLM pattern detection
- `get_user_stats(user_id)` — Summary statistics

#### 2. semantic_injection.py ✓ COMPLETE
Completely rewritten:
- `build_preference_context(user_email)` — Format preferences for prompt injection
- `personalize_recommendation_prompt(query, user_email)` — Enhance query with preferences
- `filter_candidates_by_preferences(user_email, candidates)` — Remove disliked books

#### 3. user_profile_endpoints.py ✓ COMPLETE
Simplified to three clean endpoints:
- `POST /feedback` — Record liked/disliked books from a session
- `GET /user-profile` — Get user's current preferences
- `POST /user-profile/preferences` — Update user preferences

#### 4. main.py ✓ COMPLETE
Updated to use new imports and functions:
- Removed `profile_summarizer` imports (no longer needed)
- Updated `/feedback` endpoint to use new `handle_feedback()`
- Updated `/user-profile` endpoint to use new `handle_get_preferences()`
- Updated filtering logic to use `filter_candidates_by_preferences()`

#### 5. requirements.txt ✓ COMPLETE
Added `supabase>=2.0.0` dependency

---

## Testing

Run tests to verify refactor:

```bash
cd scripts
python -m pytest test_refactored_schema.py -v
```

All 10 tests pass ✓:
- Feedback endpoint records liked/rejected books
- Preferences endpoint get/update operations
- Semantic injection formats preferences correctly
- Filtering removes disliked books
- Request/response structures are correct

---

## Database Migration Steps

### 1. Run SQL Migration in Supabase

Open Supabase SQL Editor and run:

```sql
-- Create user_preferences table (explicit preferences)
CREATE TABLE user_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  liked_books TEXT[] DEFAULT '{}',
  disliked_books TEXT[] DEFAULT '{}',
  liked_authors TEXT[] DEFAULT '{}',
  liked_genres TEXT[] DEFAULT '{}',
  disliked_authors TEXT[] DEFAULT '{}',
  disliked_genres TEXT[] DEFAULT '{}',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Create interaction_log table (episodic feedback)
CREATE TABLE interaction_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  liked_books TEXT[] DEFAULT '{}',
  disliked_books TEXT[] DEFAULT '{}',
  timestamp TIMESTAMP DEFAULT NOW()
);

-- Create indexes for query performance
CREATE INDEX idx_user_preferences_user_id ON user_preferences(user_id);
CREATE INDEX idx_interaction_log_user_id ON interaction_log(user_id);
CREATE INDEX idx_interaction_log_timestamp ON interaction_log(timestamp DESC);

-- Optional: Drop old tables if you have them
-- DROP TABLE IF EXISTS reading_history CASCADE;
-- ALTER TABLE user_profiles DROP COLUMN IF EXISTS semantic_json;
-- ALTER TABLE user_profiles DROP COLUMN IF EXISTS procedural_json;
```

### 2. Restart Backend

```bash
cd scripts
python -m uvicorn main:app --reload
```

The backend will automatically create user_preferences records on first request.

---

## Flow Examples

### Example 1: New User Gets Personalized Recommendations

```
1. User submits query: "I like science fiction"
2. Backend calls personalize_recommendation_prompt()
   - Checks user preferences (empty on first query)
   - Returns original query (no preferences yet)
3. User receives recommendations
4. User votes on recommendations (👍 👎)
5. Feedback is logged to interaction_log
```

### Example 2: Returning User Gets Filtered Recommendations

```
1. User has voted on 10 books (logged in interaction_log)
2. User sets explicit preferences: liked_genres: ["Science Fiction", "Fantasy"]
3. User submits new query
4. Backend calls personalize_recommendation_prompt()
   - Builds context: "Interested in: Science Fiction, Fantasy"
   - Returns enhanced query
5. Backend fetches candidates
6. Backend calls filter_candidates_by_preferences()
   - Removes any books in disliked_books array
   - Returns filtered candidates
7. Backend generates personalized recommendations
```

### Example 3: Pattern Detection (Future)

```
1. User has feedback history in interaction_log
2. Detect_patterns() analyzes liked/disliked books
3. Suggests new preferences: "You seem to like mystery novels"
4. User can accept/reject suggestions
5. Preferences are updated in user_preferences
```

---

## What Still Works

✓ Intent extraction — unchanged
✓ Google Books API fetching — unchanged  
✓ Claude recommendations — unchanged
✓ LangGraph retrieval — unchanged
✓ Progression queries — unchanged

---

## Next Steps (Optional)

1. **Streamlit UI** — Add preferences page to set liked/disliked books, authors, genres
2. **Pattern Detection UI** — Show detected patterns to user for confirmation
3. **Profile Visualization** — Dashboard showing user's preferences and reading stats
4. **Integration Testing** — End-to-end test of full flow: preferences → query → feedback → updated preferences

---

## Notes

- User preferences are now explicit and transparent (good for MVP learning)
- Episodic memory is fully captured in interaction_log
- Semantic/procedural memory can be learned from feedback with Claude (placeholder in `detect_patterns()`)
- Old profile_summarizer.py is no longer used (can be deleted if desired)
- All timestamps use UTC timezone-aware datetimes

