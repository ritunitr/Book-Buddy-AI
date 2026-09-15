# Pattern Detection & Learning Flow

Implements the bridge from episodic memory (feedback votes) to semantic memory (learned preferences) using Claude's analysis capabilities.

---

## Architecture

### Memory Layers

1. **Episodic Memory** ✓ COMPLETE
   - **Table**: `interaction_log`
   - **What**: Raw timestamped feedback (likes/dislikes from each query session)
   - **How**: `/feedback` endpoint logs books voted on

2. **Explicit Semantic Memory** ✓ COMPLETE
   - **Table**: `user_preferences`
   - **What**: User-set preferences (genres, authors, books, dislikes)
   - **How**: User explicitly sets via `/user-profile/preferences`

3. **Learned Semantic Memory** ✓ NEW
   - **Process**: Claude analyzes episodic memory to detect patterns
   - **Suggests**: New genres, authors, themes based on feedback
   - **How**: `/user-profile/patterns` detects, `/user-profile/patterns/confirm` accepts

### Data Flow

```
User votes on books
    ↓
Logged to interaction_log (episodic memory)
    ↓
User requests patterns: GET /user-profile/patterns
    ↓
Claude analyzes all liked/disliked books
    ↓
Returns suggested new preferences + confidence scores
    ↓
User selectively accepts suggestions: POST /user-profile/patterns/confirm
    ↓
Preferences updated in user_preferences (learned semantic)
    ↓
Future queries use updated preferences for personalization
```

---

## Endpoints

### 1. Get Pattern Suggestions

```http
GET /user-profile/patterns?user_email=user@example.com
```

**Response:**
```json
{
  "user_email": "user@example.com",
  "suggested_liked_genres": ["Cyberpunk", "Hard Science Fiction"],
  "suggested_liked_authors": ["William Gibson", "N.K. Jemisin"],
  "suggested_disliked_genres": ["Horror", "Dystopian"],
  "suggested_disliked_authors": ["Stephen King"],
  "analysis": "You clearly enjoy hard sci-fi with complex worldbuilding and strong world-building elements. You consistently dislike horror and explicit gore.",
  "confidence": 0.87,
  "feedback_count": 12,
  "books_analyzed": [
    "Foundation",
    "Dune",
    "The Fifth Season",
    "Neuromancer",
    "1984"
  ]
}
```

**When to call:**
- After user has voted on 5+ books
- User explicitly asks for recommendations based on their reading history
- Periodically (e.g., after every 10 new votes)

---

### 2. Confirm Suggestions

```http
POST /user-profile/patterns/confirm
```

**Request:**
```json
{
  "user_email": "user@example.com",
  "liked_genres": ["Cyberpunk", "Hard Science Fiction"],
  "liked_authors": ["William Gibson"],
  "disliked_genres": ["Horror"],
  "disliked_authors": null
}
```

**Response:**
```json
{
  "user_email": "user@example.com",
  "liked_books": [],
  "disliked_books": [],
  "liked_authors": ["Asimov", "Frank Herbert", "William Gibson"],
  "liked_genres": ["Science Fiction", "Cyberpunk", "Hard Science Fiction"],
  "disliked_authors": [],
  "disliked_genres": ["Horror"],
  "updated_at": "2026-09-15T15:30:45.123456+00:00"
}
```

**Notes:**
- User can selectively accept/reject each suggestion
- Suggestions are merged with existing preferences (no duplicates)
- User can pass `null` for fields to skip (reject them)
- Confirmed preferences are immediately used for personalization

---

## Algorithm

### Pattern Detection with Claude

**Input:** 
- All liked books from `interaction_log`
- All disliked books from `interaction_log`
- Current explicit preferences (to avoid suggesting what's already known)

**Process:**
1. Check if user has ≥5 voted books (minimum for patterns)
2. Send books to Claude with prompt asking to:
   - Identify common genres/themes in liked books
   - Identify common genres/themes in disliked books
   - Suggest authors they haven't voted on yet but might enjoy
   - Estimate confidence in suggestions

3. Claude returns JSON with:
   - `suggested_liked_genres[]`
   - `suggested_liked_authors[]`
   - `suggested_disliked_genres[]`
   - `suggested_disliked_authors[]`
   - `analysis` (explanation)
   - `confidence` (0.0-1.0)

**Edge Cases:**
- **Too few votes (<5)**: Returns empty suggestions with explanation
- **Claude error**: Returns error message with available data
- **No patterns found**: Returns empty arrays with confidence=0

---

## Example Flow

### Scenario: New User Learning Loop

**Step 1: User sets initial preferences**
```http
POST /user-profile/preferences
{
  "user_email": "reader@example.com",
  "liked_genres": ["Fantasy"],
  "liked_authors": ["Brandon Sanderson"]
}
```

**Step 2: User gets recommendations**
```http
POST /recommend
{
  "query": "I like epic fantasy",
  "user_email": "reader@example.com"
}
```
Backend personalizes query with "You like Fantasy, especially Brandon Sanderson"

**Step 3: User votes (3 sessions)**
- Session 1: Likes "Mistborn", dislikes "The Name of the Wind"
- Session 2: Likes "The Way of Kings", "Dune"
- Session 3: Likes "The Fifth Season", dislikes "1984"

Each session logged to `interaction_log`.

**Step 4: User requests pattern detection**
```http
GET /user-profile/patterns?user_email=reader@example.com
```

Claude analyzes 5 books:
```json
{
  "suggested_liked_genres": ["Epic Fantasy", "Science Fiction", "Grimdark"],
  "suggested_liked_authors": ["N.K. Jemisin", "Frank Herbert"],
  "suggested_disliked_genres": ["Dystopian", "Psychological Thriller"],
  "suggested_disliked_authors": [],
  "analysis": "Your preferences show strong interest in complex worldbuilding (Sanderson, Jemisin, Herbert). You avoid introspective, pessimistic narratives.",
  "confidence": 0.82,
  "feedback_count": 5
}
```

**Step 5: User confirms suggestions**
```http
POST /user-profile/patterns/confirm
{
  "user_email": "reader@example.com",
  "liked_genres": ["Epic Fantasy", "Science Fiction"],
  "liked_authors": ["N.K. Jemisin"],
  "disliked_genres": ["Dystopian"]
}
```

**Step 6: Updated preferences applied**
Now future recommendations include:
- "You like Epic Fantasy, Science Fiction, and N.K. Jemisin's work"
- Filters out books tagged as Dystopian

---

## Implementation Details

### Minimum Feedback Threshold

Pattern detection requires ≥5 voted books to reduce false positives:
```python
def detect_patterns(user_id: str):
    liked_count = len(liked_books)
    disliked_count = len(disliked_books)
    
    if liked_count + disliked_count < 5:
        return empty_response_with_threshold_message
```

### Confidence Scoring

Claude provides confidence (0.0-1.0) for each suggestion:
- **0.9+**: Very confident (>5 books support this pattern)
- **0.7-0.9**: Confident (clear pattern across multiple books)
- **0.5-0.7**: Moderate (pattern present but some variance)
- **<0.5**: Weak (not enough evidence or conflicting signals)

---

## Testing

Run pattern detection tests:
```bash
pytest test_pattern_detection.py -v
```

Includes:
- Pattern detection with sufficient feedback
- Handling insufficient feedback gracefully
- Confirming and merging suggestions
- Avoiding duplicate preferences
- Partial acceptance (user selects only some suggestions)

---

## Future Enhancements

### 1. Confidence-based UI
Show suggestions sorted by confidence:
```
Highly Confident (0.85+)
├─ Genre: Cyberpunk
├─ Author: William Gibson
├─ Theme: Dystopian futures

Moderate Confidence (0.65-0.85)
├─ Genre: Hard Science Fiction
└─ Author: N.K. Jemisin

Low Confidence (0.5-0.65)
└─ Genre: Military Science Fiction
```

### 2. Explanation Engine
Return detailed reasoning:
```
"Cyberpunk (confidence: 0.88)"
  Why: You enjoyed Neuromancer, Snow Crash, and Pattern Recognition
  Similar to: William Gibson's entire catalog
```

### 3. Automatic Threshold
Trigger pattern detection automatically:
```python
# After every 10 votes
if total_votes % 10 == 0:
    patterns = detect_patterns(user_id)
    notify_user_of_suggestions(patterns)
```

### 4. Pattern History
Track how suggestions evolve over time:
```
Pattern Detection History:
- 2026-09-15: Suggested Cyberpunk (0.88)
- 2026-09-22: Confirmed Cyberpunk → used in queries
- 2026-10-01: Suggested Military SF (0.72)
```

### 5. Genre/Author Extraction
Extract genres from Google Books API instead of asking Claude:
```python
# For each book in liked_books:
book_data = google_books_api.get(book_title)
genres = book_data['categories']  # Already structured
```

---

## Schema Notes

**Tables Used:**
- `interaction_log`: Source of episodic memory (what user voted on)
- `user_preferences`: Target for learned semantic memory (what Claude suggested + user confirmed)

**Never stored in DB:**
- Individual pattern detection requests (too transient)
- Claude suggestions before user confirmation (would need separate table)
- Confidence scores (recalculated as needed)

All are computed on-the-fly when user requests patterns, ensuring always fresh analysis.

---

## Troubleshooting

### "Need at least 5 votes"
User hasn't voted on enough books yet. Guide them to query and vote.

### Claude timeout
Try again in a moment, or reduce the number of books analyzed:
```python
# Instead of all feedback:
interactions = get_recent_interactions(user_id, limit=20)  # Last 20 interactions
```

### Empty suggestions
Books don't show clear pattern. Might need more feedback, or user's tastes are eclectic.

### Low confidence suggestions
User can safely ignore low-confidence (<0.6) suggestions and ask for more votes first.

