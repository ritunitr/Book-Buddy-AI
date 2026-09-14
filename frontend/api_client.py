"""
API Client

The ONLY module in the frontend that knows the backend's contract (its URL
and request/response shape). Everything else in frontend/ talks to the
backend through this module, never directly via requests/httpx.

This is deliberate: the backend may be replaced or moved (a different
service, a different host, a different framework entirely) without touching
any other frontend code, as long as this module's public functions keep the
same return shape.

Contains NO recommendation logic - no keyword extraction, no filtering, no
ranking. It sends a query string and returns whatever JSON the backend gives
back, un-interpreted.
"""

import os
import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
REQUEST_TIMEOUT = 120  # seconds - progression queries can take a while
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"  # Set DEMO_MODE=true to use static responses


class BackendError(Exception):
    """Raised when the backend is unreachable or returns an error response."""
    pass


def _get_demo_recommendations() -> dict:
    """Return static demo recommendations for UI testing without calling backend."""
    return {
        "query": "Find fantasy books",
        "request_type": "general",
        "search_query": "fantasy adventure",
        "audience_range": "young_adult",
        "candidates_found": 42,
        "recommendations": [
            {
                "title": "The Hobbit",
                "authors": ["J.R.R. Tolkien"],
                "why_recommended": "Classic fantasy adventure with strong worldbuilding",
                "notes": ""
            },
            {
                "title": "Dune",
                "authors": ["Frank Herbert"],
                "why_recommended": "Epic sci-fi with political intrigue and adventure",
                "notes": ""
            },
            {
                "title": "The Name of the Wind",
                "authors": ["Patrick Rothfuss"],
                "why_recommended": "Modern fantasy with rich prose and magic system",
                "notes": ""
            },
            {
                "title": "Mistborn: The Final Empire",
                "authors": ["Brandon Sanderson"],
                "why_recommended": "Fast-paced fantasy with unique magic system",
                "notes": ""
            },
            {
                "title": "The Way of Kings",
                "authors": ["Brandon Sanderson"],
                "why_recommended": "Epic fantasy with multiple perspectives and deep worldbuilding",
                "notes": ""
            }
        ],
        "overall_notes": "These are demo recommendations. Set DEMO_MODE=false in .env to use the backend."
    }


def get_recommendations(query: str) -> dict:
    """
    Call the backend's /recommend endpoint (or return demo data if DEMO_MODE=true).

    Args:
        query: Natural language book recommendation request.

    Returns:
        The backend's JSON response, unmodified. Shape depends on
        request_type (general/exploration vs progression) - see
        formatting.py for how each shape is rendered.

    Raises:
        BackendError: if the backend is unreachable, times out, or returns
                      a non-2xx response.
    """
    if not query or not query.strip():
        raise BackendError("Please enter a query.")

    # Demo mode for UI testing (no backend calls)
    if DEMO_MODE:
        return _get_demo_recommendations()

    try:
        response = requests.post(
            f"{BACKEND_URL}/recommend",
            json={"query": query.strip(), "save_results": False},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        raise BackendError("The backend took too long to respond. Please try again.")
    except requests.exceptions.ConnectionError:
        raise BackendError(
            f"Could not reach the backend at {BACKEND_URL}. Is it running?"
        )
    except requests.exceptions.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            pass
        raise BackendError(f"Backend error: {detail or str(e)}")


def check_backend_health() -> bool:
    """Returns True if the backend's /health endpoint responds successfully."""
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def submit_feedback(
    user_email: str,
    liked_titles: list,
    rejected_titles: list,
    feedback_text: str = ""
) -> dict:
    """
    Submit user feedback on recommendations (or simulate if DEMO_MODE=true).

    Args:
        user_email: User's email address
        liked_titles: List of book titles user liked
        rejected_titles: List of book titles user rejected
        feedback_text: Optional user feedback text

    Returns:
        Response dict with success status and feedback count

    Raises:
        BackendError: if the backend is unreachable or returns an error
    """
    if not user_email or not user_email.strip():
        raise BackendError("User email is required for feedback.")

    # Demo mode for UI testing
    if DEMO_MODE:
        return {
            "success": True,
            "message": "Feedback recorded successfully (DEMO MODE)",
            "feedback_count": 1,
            "summarizer_triggered": False
        }

    try:
        response = requests.post(
            f"{BACKEND_URL}/feedback",
            json={
                "user_email": user_email.strip(),
                "liked_book_titles": liked_titles,
                "rejected_book_titles": rejected_titles,
                "feedback_text": feedback_text or None
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        raise BackendError("The backend took too long to respond. Please try again.")
    except requests.exceptions.ConnectionError:
        raise BackendError(
            f"Could not reach the backend at {BACKEND_URL}. Is it running?"
        )
    except requests.exceptions.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            pass
        raise BackendError(f"Backend error: {detail or str(e)}")
