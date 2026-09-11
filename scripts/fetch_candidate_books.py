"""
Fetch Candidate Books Module

High-level, per-query-type orchestration: takes structured intent and
returns a candidate book pool. The actual Google Books mechanics (query
building, the raw search call, canonical title lookup, filtering) live in
google_books_client.py; the Phase 2 bounded-retry logic lives in
retrieval_graph.py. Split this way to avoid a circular import between this
module and retrieval_graph.py, which needs the same low-level primitives.
"""

from concurrent.futures import ThreadPoolExecutor

try:
    from google_books_client import get_subject_filter, FORMAT_MARKERS, translate_intent_to_search_params
    from retrieval_graph import run_retrieval
except ImportError:
    from .google_books_client import get_subject_filter, FORMAT_MARKERS, translate_intent_to_search_params
    from .retrieval_graph import run_retrieval

# Caps how many progression levels' Google Books searches run at once - keeps
# concurrent request volume down to avoid the throttling seen when batch-
# running the golden dataset without pacing.
MAX_CONCURRENT_LEVELS = 3


def fetch_candidate_books(intent: dict) -> dict:
    """
    Fetch candidate books based on structured recommendation intent.
    Handles general, exploration, and progression queries.

    Returns the full quality-filtered candidate pool (no artificial cap) -
    Claude's holistic judgment at the recommendation stage is a better final
    filter than an early numeric cap that could discard good candidates
    before they're ever evaluated for fit.

    Args:
        intent: Output from intent_extractor.extract_intent(), with
                "original_query" set by the caller (main.py) for the Phase 2
                retry loop's tier-2 broaden call, which needs the raw query
                text for context.

    Returns:
        For general/exploration: {"query": ..., "books": [...]}
        For progression: {"levels": [{"level": 1, "books": [...]}, ...]}
    """
    recommendation_type = intent.get("recommendation_type", "general")

    if recommendation_type == "progression":
        return _fetch_progression_books(intent)
    elif recommendation_type == "exploration" and intent.get("exploration_themes"):
        return _fetch_exploration_books(intent)
    else:
        return _fetch_general_books(intent)


def _fetch_general_books(intent: dict) -> dict:
    """
    Fetch books for general queries via the Phase 2 retrieval graph (Semantic
    Search + Canonical Search, with up to 2 bounded broaden-and-retry attempts
    if the result is bad - see retrieval_graph.py). Format/Goal signals
    (subject:/format marker) are applied as modifiers within the graph's
    search step, not a separate call.
    """
    recommendation_type = intent.get("recommendation_type", "general")
    audience_range = intent.get("audience_range", "not_specified")
    original_query = intent.get("original_query", "")
    known_titles = intent.get("known_titles", []) if intent.get("use_canonical_search") else []

    params = translate_intent_to_search_params(intent)

    result = run_retrieval(
        original_query=original_query,
        themes=params["themes"],
        known_titles=known_titles,
        subject=params["subject"],
        format_marker=params["format_marker"],
        genre=params["genre"],
        format_type=params["format"],
        audience_range=audience_range,
    )

    return {
        "request_type": recommendation_type,
        "search_query": " | ".join(result["search_queries_used"]),
        "audience_range": audience_range,
        "genre": params["genre"],
        "format": params["format"],
        "total_results": len(result["books"]),
        "books": result["books"],
        "retrieval_debug": result["debug_log"],
        "retrieval_attempts": result["attempts_used"],
    }


def _fetch_exploration_books(intent: dict) -> dict:
    """
    Fetch books for exploration queries by searching each theme cluster in
    intent["exploration_themes"] independently, so each category gets its
    own guaranteed slice of results rather than competing against the others
    in one ranked pool. Also runs through the Phase 2 retrieval graph, so a
    thin result set gets a chance to broaden before reaching the recommender.
    """
    audience_range = intent.get("audience_range", "not_specified")
    genre = intent.get("genre", "not_specified")
    format_type = intent.get("format", "not_specified")
    original_query = intent.get("original_query", "")
    theme_clusters = intent.get("exploration_themes", [])
    known_titles = intent.get("known_titles", []) if intent.get("use_canonical_search") else []

    subject = get_subject_filter(audience_range, genre)
    format_marker = FORMAT_MARKERS.get(format_type)

    result = run_retrieval(
        original_query=original_query,
        themes=[],
        known_titles=known_titles,
        subject=subject,
        format_marker=format_marker,
        genre=genre,
        format_type=format_type,
        audience_range=audience_range,
        exploration_clusters=theme_clusters,
    )

    return {
        "request_type": "exploration",
        "search_query": " | ".join(result["search_queries_used"]),
        "audience_range": audience_range,
        "genre": genre,
        "format": format_type,
        "total_results": len(result["books"]),
        "books": result["books"],
        "retrieval_debug": result["debug_log"],
        "retrieval_attempts": result["attempts_used"],
    }


def fetch_one_level(level: dict, top_level_genre: str, original_query: str) -> dict:
    """
    Run the Phase 2 retrieval graph for a single progression level.

    Public (no leading underscore) because book_recommender.py's
    run_progression_concurrent() imports this directly to fuse fetch+recommend
    per level into one thread, instead of running all levels' fetches to
    completion before any level's recommend can start.
    """
    keywords = level.get("keywords", [])
    audience_range = level.get("audience_range", "not_specified")
    known_titles = level.get("known_titles", [])

    subject = get_subject_filter(audience_range, top_level_genre)

    result = run_retrieval(
        original_query=original_query,
        themes=keywords,
        known_titles=known_titles,
        subject=subject,
        format_marker=None,
        genre=top_level_genre,
        format_type="not_specified",
        audience_range=audience_range,
    )

    level_entry = {
        "level": level.get("level"),
        "description": level.get("description", ""),
        "search_query": " | ".join(result["search_queries_used"]),
        "audience_range": audience_range,
        "total_results": len(result["books"]),
        "books": result["books"],
    }
    if result["attempts_used"] > 0:
        level_entry["retrieval_debug"] = result["debug_log"]
        level_entry["retrieval_attempts"] = result["attempts_used"]

    return level_entry


def _fetch_progression_books(intent: dict) -> dict:
    """
    Fetch books for progression queries using structured levels from intent.

    Each level runs its own Phase 2 retrieval graph independently - only a
    level that comes back bad retries (broaden tier 1/2), the other levels'
    results are untouched. This matters because progression is the most
    expensive query type (one recommendation-generation call per level), so
    retrying the whole progression on one bad level would multiply cost for
    no benefit to the levels that were already fine.

    Levels are fetched concurrently (capped pool, see MAX_CONCURRENT_LEVELS)
    since each level's Google Books search is fully independent - this is
    what makes progression queries (previously ~78s for 5 sequential levels)
    fast enough to not trip Render's gateway timeout.
    """
    levels = intent.get("levels", [])
    top_level_genre = intent.get("genre", "not_specified")
    original_query = intent.get("original_query", "")

    if not levels:
        return {
            "request_type": "progression",
            "age_context": intent.get("audience_range", "not specified"),
            "levels": []
        }

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_LEVELS) as executor:
        # executor.map preserves input order in the returned results,
        # regardless of which level finishes first.
        level_entries = list(executor.map(
            lambda level: fetch_one_level(level, top_level_genre, original_query),
            levels
        ))

    return {
        "request_type": "progression",
        "age_context": intent.get("audience_range", "not specified"),
        "levels": level_entries
    }
