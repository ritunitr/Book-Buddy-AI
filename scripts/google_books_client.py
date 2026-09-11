"""
Google Books Client

Low-level Google Books API primitives: query building, the raw search call,
canonical title lookup, and post-search filtering/diversification. Kept
separate from fetch_candidate_books.py (which owns the higher-level
per-query-type orchestration) and retrieval_graph.py (which owns the Phase 2
retry loop) so both can import these primitives without a circular import
between them.

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
import re
import httpx
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from langsmith import traceable

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
        "themes": list(themes[:3]),
        "subject": get_subject_filter(audience_range, genre),
        "format_marker": FORMAT_MARKERS.get(format_type),
        "genre": genre,
        "format": format_type
    }


@traceable(run_type="tool", name="google_books_search")
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


# A short proper-name-shaped run of words (1-4 capitalized tokens, allowing
# initials like "J.R.R."), used to recognize an author name embedded in a
# possessive or dash-separated entry without over-matching arbitrary prose.
_NAME_PATTERN = r"[A-Z][\w.]*(?:\s+[A-Z][\w.]*){0,3}"

# Straight (') and curly/smart (’, what most LLM output actually uses
# for apostrophes) in one character class, so possessive matching doesn't
# silently miss whichever form Claude happened to generate.
_APOSTROPHE = r"['’]"

# Tried in order. Each must capture (title, author) or (author, title) - the
# code below knows which is which per-pattern. Only the first match wins, so
# order matters: our own documented "Title by Author" format is checked
# first, most specific/reliable patterns before looser ones.
#
# Both the "by" and dash patterns use a GREEDY first group (.+, not .+?) so
# a title that itself contains " by " or a hyphen splits on the LAST
# occurrence, not the first - e.g. "Driven by Data by John Doe" must split
# into title="Driven by Data" / author="John Doe", not title="Driven" /
# author="Data by John Doe".
_KNOWN_TITLE_PATTERNS = [
    # "Title by Author" - our documented, preferred format
    (re.compile(r"^(.+)\s+by\s+(.+)$", re.IGNORECASE), "title_author"),
    # "Author's Title" - possessive. s? because names already ending in s
    # take a bare apostrophe ("Billy Collins' Sailing Alone..."), not 's
    # ("Collins's"). Author must look like a short proper name so we don't
    # misfire on a bare title that happens to contain an apostrophe-s with
    # no author prefix at all (e.g. a title like "America's Story").
    (re.compile(rf"^({_NAME_PATTERN}){_APOSTROPHE}s?\s+(.+)$"), "author_title"),
    # "Title - Author" / "Title — Author" (dash/em-dash separator)
    (re.compile(rf"^(.+)\s*[-–—]\s*({_NAME_PATTERN})$"), "title_author"),
]

# Strips a leading possessive author fragment ("Rupi Kaur's ", "Billy
# Collins' ") from a string that didn't match any pattern above cleanly.
# Safety net so a malformed entry we didn't anticipate still never reaches
# intitle: as a literal "Author's Title" phrase - that phrase essentially
# never matches a real Google Books title (Google's title field holds "The
# Sun and Her Flowers", never "Rupi Kaur's The Sun and Her Flowers").
_LEADING_POSSESSIVE = re.compile(rf"^{_NAME_PATTERN}{_APOSTROPHE}s?\s+")

# Wrapping quote pairs to strip before parsing - Claude occasionally wraps
# a whole entry in quotes ("'Milk and Honey by Rupi Kaur'"), which would
# otherwise end up glued onto the parsed title or author.
_QUOTE_PAIRS = [("'", "'"), ('"', '"'), ("‘", "’"), ("“", "”")]


def _strip_wrapping_quotes(entry: str) -> str:
    for open_q, close_q in _QUOTE_PAIRS:
        if len(entry) > 1 and entry.startswith(open_q) and entry.endswith(close_q):
            return entry[len(open_q):-len(close_q)].strip()
    return entry


def _parse_known_title_entry(entry: str) -> tuple:
    """
    Parse a known_titles entry into (title, author_or_None).

    Claude doesn't always use the "Title by Author" format we document and
    give examples for - Test 16's postmortem found it wrote "Author's Title"
    (possessive) for every entry in that run, which a naive " by " split
    left completely unparsed, sending the literal possessive phrase to
    intitle: where it matched nothing at all. Tries several common phrasings
    in order; if none match, falls back to treating the whole entry as the
    title with no separated author, but still strips a leading possessive
    fragment first so that fallback can't reintroduce the same failure.
    """
    entry = _strip_wrapping_quotes(entry.strip())

    for pattern, shape in _KNOWN_TITLE_PATTERNS:
        m = pattern.match(entry)
        if not m:
            continue
        first, second = m.group(1).strip(), m.group(2).strip()
        if shape == "title_author":
            return first, second
        else:  # author_title
            return second, first

    return _LEADING_POSSESSIVE.sub("", entry).strip(), None


def _normalize_title(title: str) -> str:
    """Lowercase and strip all whitespace/punctuation for loose title comparison."""
    return "".join(ch for ch in title.lower() if ch.isalnum())


def _is_title_match(requested_title: str, candidate_title: str) -> bool:
    """
    True if candidate_title is genuinely the requested book (allowing for
    subtitle/edition variants, e.g. "The Way Things Work" matching "The Way
    Things Work Now"), not just a title that shares enough words to satisfy
    Google's fuzzy intitle: matching.

    Google's intitle:"exact phrase" does NOT do phrase containment - it's
    token-based, so intitle:"National Geographic Little Kids First Big Book
    of Animals" also returns "...Big Book of Baby Animals", "...of Pets",
    "...of Space", and 16 other unrelated series-mates that merely share the
    franchise prefix. Requiring one title to be a substring of the other
    (after normalizing case/punctuation/whitespace) keeps genuine matches
    and editions while rejecting same-franchise, different-subject books.
    """
    requested = _normalize_title(requested_title)
    candidate = _normalize_title(candidate_title)
    if not requested or not candidate:
        return False
    return requested in candidate or candidate in requested


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
        stages (recommender prompt) can treat them as a trusted signal. Only
        genuine title matches (see _is_title_match) - Google's own fuzzy
        intitle: matching is filtered down after the fact.

    Different titles are looked up concurrently (one thread per title) since
    they're fully independent searches - only the title+author call and its
    title-only fallback stay sequential (the fallback needs to know the first
    call came back empty), and that's still true per title, just no longer
    serialized across titles.
    """
    entries = [e for e in known_titles if e]
    if not entries:
        return []

    def _search_one_title(entry: str) -> list:
        title_part, author_part = _parse_known_title_entry(entry)

        title_query = f'intitle:"{title_part}"'
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

        matched = []
        for book in results:
            if not _is_title_match(title_part, book.get("title", "")):
                continue
            book["is_canonical"] = True
            matched.append(book)
        return matched

    with ThreadPoolExecutor(max_workers=len(entries)) as executor:
        per_title_results = executor.map(_search_one_title, entries)
        all_books = [book for title_books in per_title_results for book in title_books]

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

    Each cluster's search is a fully independent Google Books call, so they
    run concurrently (one thread per cluster) instead of one after another -
    testing showed Google Books doesn't throttle on concurrent requests (20
    fired at once all succeeded), so there's no reason to serialize these.
    """
    if not theme_clusters:
        return [], []

    sub_queries = [
        build_google_books_query(cluster, subject=subject, format_marker=format_marker)
        for cluster in theme_clusters
    ]

    with ThreadPoolExecutor(max_workers=len(theme_clusters)) as executor:
        # executor.map preserves input order, so cluster_results[i] lines up
        # with theme_clusters[i] / sub_queries[i] below.
        cluster_results = list(executor.map(search_google_books, sub_queries))

    all_books = []
    for cluster, cluster_books in zip(theme_clusters, cluster_results):
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
