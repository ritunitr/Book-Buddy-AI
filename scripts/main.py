"""
Book Recommendation Assistant - Main FastAPI Application
Provides natural-language book recommendations grounded in real book data.

Complete pipeline:
1. intent_extractor.extract_intent() - Extract structured recommendation intent
2. fetch_candidate_books.fetch_candidate_books() - Fetch candidate books (uses intent)
3. book_recommender.recommend_books() - Generate curated recommendations (respects intent)
"""
import os
import json
from datetime import datetime
from typing import List
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langsmith import traceable

from intent_extractor import extract_intent
from fetch_candidate_books import fetch_candidate_books
from book_recommender import recommend_books as generate_recommendations
from book_recommender import run_progression_concurrent
from user_profile_endpoints import (
    FeedbackRequest,
    FeedbackResponse,
    PreferencesRequest,
    PreferencesResponse,
    PatternSuggestions,
    ConfirmPatternsRequest,
    handle_feedback,
    handle_get_preferences,
    handle_update_preferences,
    handle_get_patterns,
    handle_confirm_patterns
)
from semantic_injection import (
    personalize_recommendation_prompt,
    filter_candidates_by_preferences
)

load_dotenv()

# Create runs directory for saving results (../runs from scripts/)
RUNS_DIR = Path(__file__).parent.parent / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Aggregated results file for all queries
AGGREGATED_FILE = RUNS_DIR / "aggregated_results.json"

# Lock for thread-safe file writes
import threading
WRITE_LOCK = threading.Lock()

app = FastAPI(
    title="Book Recommendation Assistant",
    description="Natural-language book recommendations grounded in real book data",
    version="0.1.0"
)


# Pydantic models
class RecommendationRequest(BaseModel):
    query: str = Field(..., description="Natural language book recommendation request")
    max_results: int = Field(default=20, ge=1, le=50, description="Deprecated, no longer used - the full quality-filtered candidate pool is always sent to the recommender. Kept for API/client backward compatibility.")
    save_results: bool = Field(default=False, description="Save intermediate results to runs/latest")
    user_email: str = Field(default=None, description="(Optional) User email to enable semantic profile injection and filtering")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "My son is into cars and trucks. Give me recommendations of books he'll enjoy.",
                "max_results": 30,
                "save_results": False,
                "user_email": "user@example.com"
            }
        }


class BookRecommendation(BaseModel):
    title: str
    authors: List[str]
    why_recommended: str
    notes: str


def append_to_aggregated(query: str, stage: str, data: dict, enabled: bool = True):
    """
    Append query result to aggregated JSON files.
    Creates 3 consolidated files:
    - all_themes_extracted.json
    - all_candidates_fetched.json
    - all_recommendations_generated.json
    """
    if not enabled:
        return

    with WRITE_LOCK:
        # Load existing aggregated data or start fresh
        agg_file = RUNS_DIR / f"all_{stage}.json"

        try:
            with open(agg_file, "r") as f:
                aggregated = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            aggregated = {}

        # Add this query's data
        aggregated[query] = data

        # Write back
        with open(agg_file, "w") as f:
            json.dump(aggregated, f, indent=2)

        print(f"[AGGREGATED] {agg_file.name}: added query")


def make_run_dir(query: str, enabled: bool = True) -> Path:
    """
    Create one timestamped directory for a single /recommend request.
    All 3 pipeline stages for that request are saved inside this same directory.
    """
    if not enabled:
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = RUNS_DIR / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    with open(run_dir / "00_request_summary.json", "w") as f:
        json.dump({"timestamp": timestamp, "query": query, "stages_saved": []}, f, indent=2)

    return run_dir


def save_results(run_dir: Path, stage: str, data: dict, enabled: bool = True) -> Path:
    """
    Save one pipeline stage's full output into the request's run directory.

    Args:
        run_dir: Directory created by make_run_dir() for this request
        stage: Stage name (e.g. "1_themes_extracted")
        data: Full data to save (not a summary)
        enabled: Whether to save (controlled by save_results flag)

    Returns:
        Path to saved file
    """
    if not enabled or run_dir is None:
        return None

    filepath = run_dir / f"{stage}.json"
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    # Track which stages have been saved in this run
    summary_path = run_dir / "00_request_summary.json"
    with open(summary_path, "r") as f:
        summary = json.load(f)
    if stage not in summary.get("stages_saved", []):
        summary["stages_saved"].append(stage)
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[SAVED] {filepath}")
    return filepath


@app.get("/", include_in_schema=False)
async def root():
    """Redirect the bare root path to the interactive API docs."""
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "message": "Book Recommendation Assistant is running"}


@app.post("/recommend")
@traceable(name="recommend_request")
async def recommend_books_endpoint(request: RecommendationRequest):
    """
    Get book recommendations based on natural language query.

    Complete flow:
    1. Extract themes/keywords from query
    2. Fetch candidate books from Google Books API
    3. Use Claude to select best recommendations

    Handles both general and progression queries.
    Saves all intermediate results if enabled.

    @traceable makes this the root LangSmith trace for the whole request -
    the wrapped Anthropic clients (intent_extractor, book_recommender) and
    the @traceable google_books_search calls all nest under it automatically,
    giving one trace per request with total latency, LLM call count, tool
    call count, and token usage all visible together.
    """
    try:
        # Step 0: Apply semantic personalization if user_email provided
        personalized_query = request.query
        filter_metadata = None

        if request.user_email:
            print(f"\n[Step 0] Personalizing with user profile ({request.user_email})...")
            personalized_query = personalize_recommendation_prompt(
                request.query,
                request.user_email
            )
            if personalized_query != request.query:
                print(f"  ✓ Query enhanced with semantic profile")

        # Only save to aggregated files, not individual run directories
        # Step 1: Extract structured recommendation intent
        print(f"\n[Step 1] Extracting recommendation intent...")
        intent = extract_intent(personalized_query)  # Use personalized query
        intent["original_query"] = request.query  # needed by Phase 2's tier-2 broaden call for context
        append_to_aggregated(request.query, "intent_extracted", intent, request.save_results)
        print(f"  ✓ Intent: {intent.get('recommendation_type')} - Genre: {intent.get('genre')} - Format: {intent.get('format')}")

        if intent.get("recommendation_type") == "progression":
            # Progression fuses fetch+recommend per level and runs all levels
            # concurrently (one thread per level, uncapped) - see
            # book_recommender.run_progression_concurrent for why. This
            # skips the separate "candidates_fetched" snapshot stage since
            # fetch and recommend now happen together inside each thread.
            print(f"\n[Step 2+3] Fetching + generating recommendations per level (concurrent)...")
            recommendations = run_progression_concurrent(request.query, intent)

            total_recs = sum(len(level.get("recommendations", [])) for level in recommendations.get("levels", []))
            append_to_aggregated(request.query, "recommendations_generated", recommendations, request.save_results)
            print(f"  ✓ Generated: {total_recs} recommendations")
        else:
            # Step 2: Fetch candidate books using intent (full filtered pool, no cap)
            print(f"\n[Step 2] Fetching candidate books...")
            candidates = fetch_candidate_books(intent)

            total_candidates = candidates.get("total_results", 0)
            append_to_aggregated(request.query, "candidates_fetched", candidates, request.save_results)
            print(f"  ✓ Fetched: {total_candidates} total candidates")

            # Step 2.5: Filter candidates by user's preferences if user_email provided
            if request.user_email:
                print(f"\n[Step 2.5] Filtering disliked books...")
                books = candidates.get("books", [])
                filtered_books, filter_metadata = filter_candidates_by_preferences(
                    request.user_email,
                    books
                )
                candidates["books"] = filtered_books
                candidates["total_results"] = len(filtered_books)
                removed = filter_metadata.get("filtered_out_count", 0)
                if removed > 0:
                    print(f"  ✓ Filtered out {removed} disliked books")

            # Step 3: Generate recommendations
            print(f"\n[Step 3] Generating recommendations...")
            recommendations = generate_recommendations(request.query, candidates)

            total_recs = len(recommendations.get("recommendations", []))
            append_to_aggregated(request.query, "recommendations_generated", recommendations, request.save_results)
            print(f"  ✓ Generated: {total_recs} recommendations")

        # Convert to appropriate response format
        request_type = recommendations.get("request_type", "general")

        if request_type == "progression":
            levels = []
            for level in recommendations.get("levels", []):
                level_out = {
                    "level": level["level"],
                    "description": level["description"],
                    "audience_range": level["audience_range"],
                    "candidates_found": level["candidates_found"],
                    "recommendations": [
                        {
                            "title": rec["title"],
                            "authors": rec["authors"],
                            "why_recommended": rec["why_recommended"],
                            "notes": rec.get("notes", "")
                        }
                        for rec in level["recommendations"]
                    ],
                    "notes": level.get("notes", "")
                }
                # Phase 2: only present if this level's retrieval actually retried
                if level.get("retrieval_attempts"):
                    level_out["retrieval_debug"] = level.get("retrieval_debug", [])
                    level_out["retrieval_attempts"] = level["retrieval_attempts"]
                levels.append(level_out)

            return {
                "query": request.query,
                "request_type": "progression",
                "age_context": recommendations.get("age_context", ""),
                "levels": levels
            }
        else:
            response = {
                "query": request.query,
                "request_type": request_type,
                "search_query": recommendations.get("search_query", ""),
                "audience_range": recommendations.get("audience_range", ""),
                "candidates_found": recommendations.get("candidates_found", 0),
                "recommendations": [
                    {
                        "title": rec["title"],
                        "authors": rec["authors"],
                        "why_recommended": rec["why_recommended"],
                        "notes": rec.get("notes", "")
                    }
                    for rec in recommendations.get("recommendations", [])
                ],
                "overall_notes": recommendations.get("overall_notes", "")
            }
            # Include filtering metadata if applied
            if filter_metadata:
                response["filter_metadata"] = filter_metadata
            # Phase 2: only present if retrieval actually retried
            if recommendations.get("retrieval_attempts"):
                response["retrieval_debug"] = recommendations.get("retrieval_debug", [])
                response["retrieval_attempts"] = recommendations["retrieval_attempts"]
            return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ============================================================================
# Milestone 2: User Profile Endpoints
# ============================================================================

@app.post("/feedback")
async def feedback_endpoint(request: FeedbackRequest) -> FeedbackResponse:
    """
    Accept user feedback on book recommendations.

    Records which books the user liked/rejected.
    Triggers Claude summarizer every Nth feedback to distill semantic + procedural profile.

    Request body:
    {
        "user_email": "user@example.com",
        "liked_book_titles": ["The Hobbit", "Dune"],
        "rejected_book_titles": ["1984"],
        "feedback_text": "Loved fantasy and sci-fi, dislike dystopia"
    }

    Returns feedback count and whether summarizer was triggered.
    """
    try:
        response = await handle_feedback(request)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Feedback error: {str(e)}")


@app.get("/user-profile")
async def get_user_profile_endpoint(user_email: str) -> PreferencesResponse:
    """
    Get user's current preferences.

    Query parameter:
    - user_email: User's email address

    Returns user's explicit preferences: liked/disliked books, authors, genres.
    """
    try:
        response = await handle_get_preferences(user_email)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profile error: {str(e)}")


@app.post("/user-profile/preferences")
async def update_preferences_endpoint(request: PreferencesRequest) -> PreferencesResponse:
    """
    Update user's preferences.

    Allows user to set or modify their explicit preferences.
    """
    try:
        response = await handle_update_preferences(request)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update error: {str(e)}")


# ============================================================================
# Pattern Detection Endpoints
# ============================================================================

@app.get("/user-profile/patterns")
async def get_patterns_endpoint(user_email: str) -> PatternSuggestions:
    """
    Detect patterns from user's feedback history.

    Analyzes all liked/disliked books and suggests new preferences (genres, authors).
    Uses Claude to identify patterns.

    Query parameter:
    - user_email: User's email address

    Returns suggested preferences with confidence scores.
    """
    try:
        response = await handle_get_patterns(user_email)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pattern detection error: {str(e)}")


@app.post("/user-profile/patterns/confirm")
async def confirm_patterns_endpoint(request: ConfirmPatternsRequest) -> PreferencesResponse:
    """
    Accept suggested patterns and update user preferences.

    User can selectively accept suggested genres, authors, etc. from pattern detection.
    Accepted suggestions are merged with existing preferences.

    Request body:
    {
        "user_email": "user@example.com",
        "liked_genres": ["Mystery", "Thriller"],
        "liked_authors": ["Agatha Christie"],
        "disliked_genres": ["Horror"],
        "disliked_authors": []
    }

    Returns updated user preferences.
    """
    try:
        response = await handle_confirm_patterns(request)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Confirm error: {str(e)}")
