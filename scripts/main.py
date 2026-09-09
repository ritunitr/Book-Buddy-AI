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
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from intent_extractor import extract_intent
from fetch_candidate_books import fetch_candidate_books
from book_recommender import recommend_books as generate_recommendations

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

    class Config:
        json_schema_extra = {
            "example": {
                "query": "My son is into cars and trucks. Give me recommendations of books he'll enjoy.",
                "max_results": 30,
                "save_results": False
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


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "message": "Book Recommendation Assistant is running"}


@app.post("/recommend")
async def recommend_books_endpoint(request: RecommendationRequest):
    """
    Get book recommendations based on natural language query.

    Complete flow:
    1. Extract themes/keywords from query
    2. Fetch candidate books from Google Books API
    3. Use Claude to select best recommendations

    Handles both general and progression queries.
    Saves all intermediate results if enabled.
    """
    try:
        # Only save to aggregated files, not individual run directories
        # Step 1: Extract structured recommendation intent
        print(f"\n[Step 1] Extracting recommendation intent...")
        intent = extract_intent(request.query)
        append_to_aggregated(request.query, "intent_extracted", intent, request.save_results)
        print(f"  ✓ Intent: {intent.get('recommendation_type')} - Genre: {intent.get('genre')} - Format: {intent.get('format')}")

        # Step 2: Fetch candidate books using intent (full filtered pool, no cap)
        print(f"\n[Step 2] Fetching candidate books...")
        candidates = fetch_candidate_books(intent)

        total_candidates = candidates.get("total_results", 0) if candidates.get("request_type") != "progression" \
            else sum(level.get("total_results", 0) for level in candidates.get("levels", []))

        append_to_aggregated(request.query, "candidates_fetched", candidates, request.save_results)
        print(f"  ✓ Fetched: {total_candidates} total candidates")

        # Step 3: Generate recommendations
        print(f"\n[Step 3] Generating recommendations...")
        recommendations = generate_recommendations(request.query, candidates)

        total_recs = len(recommendations.get("recommendations", [])) if recommendations.get("request_type") != "progression" \
            else sum(len(level.get("recommendations", [])) for level in recommendations.get("levels", []))

        append_to_aggregated(request.query, "recommendations_generated", recommendations, request.save_results)
        print(f"  ✓ Generated: {total_recs} recommendations")

        # Convert to appropriate response format
        request_type = recommendations.get("request_type", "general")

        if request_type == "progression":
            levels = []
            for level in recommendations.get("levels", []):
                levels.append({
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
                })

            return {
                "query": request.query,
                "request_type": "progression",
                "age_context": recommendations.get("age_context", ""),
                "levels": levels
            }
        else:
            return {
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

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
