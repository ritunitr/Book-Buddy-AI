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


class BackendError(Exception):
    """Raised when the backend is unreachable or returns an error response."""
    pass


def get_recommendations(query: str) -> dict:
    """
    Call the backend's /recommend endpoint.

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
