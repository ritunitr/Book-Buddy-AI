"""
Fetch Candidate Books Module

Fetches books from Google Books API based on structured recommendation intent.

Query strategy: build a single Google Books query per search using:
- OR-combined theme keywords (broadens topic coverage in one call, instead of
  firing multiple AND-combination searches)
- An explicit quoted format marker (e.g. "graphic novel") when a specific
  visual/structural format was requested
- A `subject:"..."` field filter based on audience_range + genre, which acts
  as a relevance boost (not a hard filter - Google Books still returns some
  noise) toward books actually classified in that category

Both signals matter: `subject:"picture books"` alone still lets some non-book
noise through, and format markers alone (e.g. "graphic novel" with no subject
filter) surface meta-books ABOUT that format (library guides, teaching
references) as often as real ones. Combined, they consistently rank real
matches above both kinds of noise.
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

GOOGLE_BOOKS_API_URL = "https://www.googleapis.com/books/v1/volumes"
GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")


# subject: filter based on audience_range + genre. This is a relevance boost,
# not a hard filter - Google Books still returns some non-matching items - so
# callers must still post-filter (see _is_likely_non_book / _filter_books_by_intent).
def get_subject_filter(audience_range: str, genre: str) -> str:
    if audience_range in ("toddler", "preschool"):
        # BUG (fixed): this used to ignore genre entirely and always return
        # "picture books", which biases toward narrative/fiction category even
        # for an explicitly nonfiction/instructional request (e.g. "teach him
        # cooking" -> genre=nonfiction). A children's cookbook is rarely
        # classified "Picture books" in Google Books metadata, so the old
        # unconditional filter was actively excluding the instructional
        # content the user asked for in favor of narrative picture books
        # that merely mention the topic.
        return "juvenile nonfiction" if genre == "nonfiction" else "picture books"
    if audience_range in ("early_reader", "middle_grade", "young_adult"):
        return "juvenile nonfiction" if genre == "nonfiction" else "juvenile fiction"
    # adult / not_specified
    if genre == "fiction":
        return "fiction"
    return None  # adult nonfiction/mixed is too broad for one subject: value


# Explicit quoted keyword added to the query when a specific format was
# requested. Combined with subject:, this reliably surfaces actual books of
# that format rather than books ABOUT that format (see module docstring).
#
# "guide" is deliberately EXCLUDED (mapped to None): unlike "graphic novel" or
# "picture book", which are specific enough to reliably identify real books of
# that format, "guide" is a generic word that self-published/low-quality
# nonfiction titles use heavily ("The Ultimate Guide to X"), while genuine
# canonical nonfiction rarely has it in the title (e.g. "AI Engineering",
# "Designing Machine Learning Systems", "Tao Te Ching", "The Untethered Soul" -
# none contain "guide"). Forcing it into every search for format=guide queries
# was filtering the classics OUT and the junk IN.
FORMAT_MARKERS = {
    "graphic_novel": "graphic novel",
    "picture_book": "picture book",
    "chapter_book": "chapter book",
    "novel": "novel",
    "guide": None,
    "anthology": "anthology",
    "not_specified": None
}

# Categories that indicate a book ABOUT a format/subject (teaching guides,
# library science, writer's references, encyclopedias) rather than a book that
# actually IS that format. subject: + format marker greatly reduce these, but
# don't eliminate them, so still excluded post-search.
META_CATEGORIES = [
    "language arts & disciplines", "education", "reference",
    "literary criticism", "library", "social science",
    "antiques & collectibles", "bibliography", "book industries",
]


def build_google_books_query(themes: list, subject: str = None, format_marker: str = None) -> str:
    """
    Build a single Google Books API query string:
        (theme1 OR theme2 OR ...) ["format marker"] subject:"category"

    Deliberately excludes literal age numbers (e.g. "ages 9-12") as a query
    term: age is a ranking/filtering signal for how well a result fits the
    reader, not a retrieval constraint - Google Books metadata doesn't
    consistently carry age ranges in title/description text, so forcing it
    into the query narrows results without reliably improving them. The
    subject: filter (picture books / juvenile fiction / fiction) already
    carries the coarse audience signal needed at retrieval time.
    """
    theme_terms = [f'"{t}"' if " " in t else t for t in themes if t]
    query = " OR ".join(theme_terms)

    if format_marker:
        query += f' "{format_marker}"'

    if subject:
        query += f' subject:"{subject}"'

    return query.strip()


def translate_intent_to_search_params(intent: dict) -> dict:
    """
    Translate abstract intent fields into a Google Books query builder's inputs.

    Returns dict with:
    - themes: topic keywords (OR-combined by build_google_books_query)
    - subject: subject: filter string, or None
    - format_marker: quoted format keyword, or None
    - genre / format: passthrough for post-search filtering
    """
    themes = intent.get("themes", [])
    audience_range = intent.get("audience_range", "not_specified")
    genre = intent.get("genre", "not_specified")
    format_type = intent.get("format", "not_specified")

    return {
        "themes": list(themes[:5]),
        "subject": get_subject_filter(audience_range, genre),
        "format_marker": FORMAT_MARKERS.get(format_type),
        "genre": genre,
        "format": format_type
    }


def search_google_books(query: str) -> list:
    """
    Run a single Google Books API search for a pre-built query string.

    Returns the FULL diversified pool (up to Google's 40-per-call max), not
    truncated to any caller-specified limit. The recommender should see every
    candidate that survives quality/genre/format filtering, not a pre-filter
    slice picked by Google's raw term-overlap ranking - Claude's holistic
    judgment at the recommendation stage is a better final filter than an
    early numeric cap that can discard good candidates before they're ever
    evaluated for fit.

    Returns:
        List of deduplicated, author-diversified book dictionaries.
    """
    if not query or not GOOGLE_BOOKS_API_KEY:
        return []

    params = {
        "q": query,
        "maxResults": 40,  # Google Books API's own per-call maximum
        "printType": "books",
        "langRestrict": "en",
        "key": GOOGLE_BOOKS_API_KEY
    }


    try:
        response = httpx.get(GOOGLE_BOOKS_API_URL, params=params, timeout=10.0)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Error fetching books for '{query}': {e}")
        return []

    books = {}  # Use dict to deduplicate by title
    for item in data.get("items", []):
        info = item.get("volumeInfo", {})
        title = info.get("title", "Unknown")
        if title not in books:
            books[title] = {
                "title": title,
                "authors": info.get("authors", []),
                "description": info.get("description", "")[:400],
                "categories": info.get("categories", []),
                "maturity_rating": info.get("maturityRating", "NOT_MATURE"),
                "page_count": info.get("pageCount"),
                "published_date": info.get("publishedDate", ""),
                "google_books_url": item.get("selfLink", "")
            }

    return _diversify_by_author(list(books.values()), max_per_author=2)


def _search_known_titles(known_titles: list) -> list:
    """
    Canonical Search stage: look up specific, named titles directly via
    Google Books' intitle:/inauthor: operators, rather than hoping they
    happen to rank for generic topic keywords.

    This exists because topical keyword search (the Semantic Search stage)
    systematically misses well-known/canonical works: their titles are often
    abstract or metaphorical and don't share vocabulary with generic topic
    terms (e.g. "artificial intelligence novel" doesn't surface "Do Androids
    Dream of Electric Sheep?"), while lower-quality books that happen to
    literally contain the search keywords crowd them out. Searching by name
    directly sidesteps that entirely.

    Args:
        known_titles: entries like "Title" or "Title by Author", as produced
                      by intent_extractor's "known_titles" field.

    Returns:
        List of book dicts, each tagged with is_canonical=True so downstream
        stages (recommender prompt) can treat them as a trusted signal.
    """
    all_books = []
    for entry in known_titles:
        if not entry:
            continue
        if " by " in entry:
            title_part, author_part = entry.rsplit(" by ", 1)
        else:
            title_part, author_part = entry, None

        title_query = f'intitle:"{title_part.strip()}"'
        results = []
        if author_part:
            # Try the precise title+author match first, but don't let a
            # mismatched author (wrong person, or a publisher name mistaken
            # for one - e.g. "Ryland Peters & Small") silently zero out an
            # otherwise-real title. inauthor: + intitle: is an AND in Google's
            # query syntax, so a wrong author returns nothing even when the
            # title exists under a different author.
            results = search_google_books(f'{title_query} inauthor:"{author_part.strip()}"')
        if not results:
            results = search_google_books(title_query)

        for book in results:
            book["is_canonical"] = True
            all_books.append(book)

    return all_books


def _diversify_by_author(books: list, max_per_author: int = 2) -> list:
    """
    Cap how many books from the same author (a cheap proxy for "same series")
    can appear in the pool, while preserving Google's relevance order overall.
    Without this, a prolific series (Geronimo Stilton, etc.) can occupy most of
    the top-N slots on term-overlap alone, crowding out a differently-worded
    but equally or more relevant single title (e.g. Wings of Fire).
    """
    author_counts = {}
    diversified = []
    overflow = []

    for book in books:
        authors = book.get("authors", [])
        author_key = authors[0] if authors else None
        count = author_counts.get(author_key, 0)
        if author_key is None or count < max_per_author:
            diversified.append(book)
            author_counts[author_key] = count + 1
        else:
            overflow.append(book)

    # Keep overflow available at the end rather than dropping it, so a search
    # that's genuinely dominated by one series still returns results.
    return diversified + overflow


def fetch_candidate_books(intent: dict) -> dict:
    """
    Fetch candidate books based on structured recommendation intent.
    Handles both general and progression queries.

    Returns the full quality-filtered candidate pool (no artificial cap) - see
    search_google_books() for why the recommender should see everything that
    survives filtering rather than a pre-truncated slice.

    Args:
        intent: Output from intent_extractor.extract_intent()

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


def _is_likely_non_book(book: dict) -> bool:
    """Check if item is likely a government document, journal, or non-book publication."""
    title = book.get("title", "").lower()
    authors = book.get("authors", [])
    description = book.get("description", "").lower()
    categories = book.get("categories", [])

    red_flag_titles = [
        "annual report", "journal of", "proceedings of",
        "standard", "guide for", "patent", "survey",
        "classification", "record of", "manual of",
        "report on", "act of", "statute", "code"
    ]
    for flag in red_flag_titles:
        if flag in title:
            return True

    if not description or len(description) < 30:
        return True

    # Large lists of authors often indicate non-books (journals, technical standards)
    if len(authors) > 5:
        return True

    categories_str = " ".join(categories).lower()
    if any(x in categories_str for x in ["journal", "periodical", "report", "government", "standard"]):
        return True

    return False


def _filter_books_by_intent(books: list, intent: dict) -> list:
    """
    Post-search safety net. subject:/format-marker in the query boost relevance
    but don't hard-filter, so this still needs to catch:
    - Non-books (government docs, journals, technical manuals)
    - Nonfiction slipping into a fiction-only request
    - Meta-books ABOUT a requested format rather than books that ARE it
    """
    if not books:
        return books

    genre = intent.get("genre")
    format_type = intent.get("format")

    filtered = []
    for book in books:
        if _is_likely_non_book(book):
            continue

        categories = book.get("categories", [])
        categories_str = " ".join(categories).lower()

        if genre == "fiction":
            # NOTE: check "nonfiction" BEFORE "fiction" - the substring "fiction"
            # is literally contained in "nonfiction", so a naive `"fiction" in
            # categories_str` check wrongly treats "Juvenile Nonfiction" as a match.
            is_nonfiction = "nonfiction" in categories_str or "non-fiction" in categories_str
            if is_nonfiction:
                continue
            has_fiction_marker = "fiction" in categories_str or "novel" in categories_str or "literature" in categories_str
            if not has_fiction_marker:
                if any(x in categories_str for x in ["textbook", "reference", "academic", "scholarly"]):
                    continue

        if format_type and format_type != "not_specified":
            if any(term in categories_str for term in META_CATEGORIES):
                continue

        filtered.append(book)

    return filtered


def _search_multi_query(theme_clusters: list, subject: str = None, format_marker: str = None, tag_clusters: bool = False) -> tuple:
    """
    Search each theme cluster INDEPENDENTLY rather than OR-combining them into
    one query, then aggregate. A single big OR query doesn't let you control
    recall/diversity per keyword: ranking is dominated by whichever keyword
    happens to match the most items, so a keyword with fewer but perfectly
    on-topic matches can get crowded out of the result set entirely. Separate
    searches guarantee every keyword/cluster gets its own slice of results.

    Args:
        tag_clusters: when True, tags each book with source_cluster (the
            cluster's keywords, joined) so downstream stages (recommendation
            prompt) can see which category a candidate came from and enforce
            real cross-category diversity - not just avoiding duplicate
            titles, but avoiding a final selection that's all from one
            cluster even though several were searched. Used by exploration;
            general queries don't need this since they aren't trying to
            span distinct categories.

    Returns (books, sub_queries) - sub_queries is kept for the response's
    search_query field so the actual API calls made are visible/debuggable.
    """
    all_books = []
    sub_queries = []
    for cluster in theme_clusters:
        query = build_google_books_query(cluster, subject=subject, format_marker=format_marker)
        sub_queries.append(query)
        cluster_books = search_google_books(query)
        if tag_clusters:
            cluster_label = " / ".join(cluster)
            for book in cluster_books:
                book["source_cluster"] = cluster_label
        all_books.extend(cluster_books)

    # Dedupe by title across all searches (a book can legitimately surface
    # under more than one cluster), then diversify by author so no single
    # prolific series/keyword-match dominates the aggregated pool.
    deduped = {}
    for book in all_books:
        title = book.get("title", "Unknown")
        if title not in deduped:
            deduped[title] = book

    books = _diversify_by_author(list(deduped.values()), max_per_author=2)
    return books, sub_queries


def _fetch_general_books(intent: dict) -> dict:
    """
    Fetch books for general queries from three independent stages, merged
    into one candidate pool:
    - Semantic Search: each extracted theme keyword searched independently
      (via _search_multi_query) - covers the topical long tail
    - Canonical Search: known_titles looked up directly by title/author (via
      _search_known_titles) - guarantees well-known works are considered
      even when their titles don't share vocabulary with topic keywords
    - Format/Goal signals (subject:/format marker) are applied as modifiers
      within the Semantic Search stage's queries, not a separate call

    See _search_multi_query and _search_known_titles docstrings for why each
    stage exists independently rather than folding into one big query.
    """
    recommendation_type = intent.get("recommendation_type", "general")
    audience_range = intent.get("audience_range", "not_specified")
    known_titles = intent.get("known_titles", []) if intent.get("use_canonical_search") else []

    params = translate_intent_to_search_params(intent)
    theme_clusters = [[theme] for theme in params["themes"]]  # one keyword per search

    # No max_results cap here - the full quality-filtered pool goes to the
    # recommender. Claude's holistic judgment at the recommendation stage is
    # the right place to narrow down to 4-6 picks, not an early numeric
    # truncation that could discard good candidates before they're evaluated.
    semantic_books, sub_queries = _search_multi_query(
        theme_clusters,
        subject=params["subject"],
        format_marker=params["format_marker"]
    )

    canonical_books = _search_known_titles(known_titles)
    canonical_queries = [f'intitle:"{t.split(" by ")[0].strip()}"' for t in known_titles]

    # Canonical titles are explicitly named/vetted by the intent extractor
    # (not organic keyword matches), so they skip the genre/meta-category
    # filtering applied to semantic search results - only the basic non-book
    # check applies. Semantic results still go through full filtering.
    semantic_filtered = _filter_books_by_intent(semantic_books, intent)
    canonical_filtered = [b for b in canonical_books if not _is_likely_non_book(b)]

    # Merge, dedupe by title (canonical entries take precedence so
    # is_canonical=True survives if a title appears in both stages)
    merged = {}
    for book in semantic_filtered:
        merged[book.get("title", "Unknown")] = book
    for book in canonical_filtered:
        merged[book.get("title", "Unknown")] = book

    books = list(merged.values())

    return {
        "request_type": recommendation_type,
        "search_query": " | ".join(sub_queries + canonical_queries),
        "audience_range": audience_range,
        "genre": params["genre"],
        "format": params["format"],
        "total_results": len(books),
        "books": books
    }


def _fetch_exploration_books(intent: dict) -> dict:
    """
    Fetch books for exploration queries by searching each theme cluster in
    intent["exploration_themes"] independently (via _search_multi_query), so
    each category gets its own guaranteed slice of results rather than
    competing against the others in one ranked pool.
    """
    audience_range = intent.get("audience_range", "not_specified")
    genre = intent.get("genre", "not_specified")
    format_type = intent.get("format", "not_specified")
    theme_clusters = intent.get("exploration_themes", [])

    subject = get_subject_filter(audience_range, genre)
    format_marker = FORMAT_MARKERS.get(format_type)

    books, sub_queries = _search_multi_query(theme_clusters, subject=subject, format_marker=format_marker, tag_clusters=True)
    books = _filter_books_by_intent(books, intent)

    return {
        "request_type": "exploration",
        "search_query": " | ".join(sub_queries),
        "audience_range": audience_range,
        "genre": genre,
        "format": format_type,
        "total_results": len(books),
        "books": books
    }


def _fetch_progression_books(intent: dict) -> dict:
    """Fetch books for progression queries using structured levels from intent."""
    levels = intent.get("levels", [])
    top_level_genre = intent.get("genre", "not_specified")

    if not levels:
        return {
            "request_type": "progression",
            "age_context": intent.get("audience_range", "not specified"),
            "levels": []
        }

    results = {
        "request_type": "progression",
        "age_context": intent.get("audience_range", "not specified"),
        "levels": []
    }

    for level in levels:
        keywords = level.get("keywords", [])
        audience_range = level.get("audience_range", "not_specified")
        known_titles = level.get("known_titles", [])

        subject = get_subject_filter(audience_range, top_level_genre)
        query = build_google_books_query(keywords, subject=subject)

        semantic_books = search_google_books(query)
        semantic_filtered = _filter_books_by_intent(semantic_books, {"genre": top_level_genre, "format": "not_specified"})

        # Canonical Search per level: a canonical title's fit is level-specific
        # (an engineering classic fits a middle-grade level, not a toddler
        # level), so known_titles is read from each level object rather than
        # the top-level intent field. Skips genre/meta-category filtering
        # like the general-query path, for the same reason - these are
        # already vetted by name, not organic keyword matches.
        canonical_queries = []
        canonical_filtered = []
        if known_titles:
            canonical_books = _search_known_titles(known_titles)
            canonical_filtered = [b for b in canonical_books if not _is_likely_non_book(b)]
            canonical_queries = [f'intitle:"{t.split(" by ")[0].strip()}"' for t in known_titles]

        merged = {}
        for book in semantic_filtered:
            merged[book.get("title", "Unknown")] = book
        for book in canonical_filtered:
            merged[book.get("title", "Unknown")] = book
        books = list(merged.values())

        results["levels"].append({
            "level": level.get("level"),
            "description": level.get("description", ""),
            "search_query": " | ".join([query] + canonical_queries),
            "audience_range": audience_range,
            "total_results": len(books),
            "books": books
        })

    return results
