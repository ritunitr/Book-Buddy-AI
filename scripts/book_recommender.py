"""
Book Recommender Module

Takes candidate books and uses Claude to select and rank the most relevant recommendations.
Handles both general and progression queries.
"""

import json
import os
from dotenv import load_dotenv
from anthropic import Anthropic
try:
    from prompts import BOOK_RECOMMENDATION_SYSTEM_PROMPT_BASE
    from observability import traced_anthropic_client
except ImportError:
    from .prompts import BOOK_RECOMMENDATION_SYSTEM_PROMPT_BASE
    from .observability import traced_anthropic_client

load_dotenv()

# Traces every messages.create() call (latency, input/output tokens, model)
# to LangSmith automatically. No-ops safely if LANGSMITH_API_KEY isn't set.
anthropic_client = traced_anthropic_client(Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")))


def extract_text(message) -> str:
    """Get text content from a Claude response."""
    for block in message.content:
        if block.type == "text":
            return block.text
    raise ValueError(f"No text block found — got: {[b.type for b in message.content]}")


def filter_questionable_books(books: list) -> list:
    """
    Filter out likely self-published or low-quality books.

    Removes books that:
    - Have no page count or suspiciously low page count (<10 pages for children's books)
    - Have no publication date or "unknown" date
    - Have empty description
    """
    filtered = []

    for book in books:
        # Check page count - children's books typically 10+ pages
        page_count = book.get("page_count")
        if page_count and page_count < 10:
            continue  # Skip very short books (likely self-published)

        # Check publication date - books should have a date
        pub_date = book.get("published_date", "").strip()
        if not pub_date or pub_date.lower() == "unknown":
            continue  # Skip books with no publication date

        # Check description - questionable books often lack descriptions
        description = book.get("description", "").strip()
        if not description or len(description) < 20:
            continue  # Skip books with minimal/no description

        filtered.append(book)

    return filtered


def format_books_for_prompt(books: list) -> str:
    """Format candidate books as a numbered list for the prompt."""
    formatted = ""
    for i, book in enumerate(books, 1):
        authors = ", ".join(book['authors']) if book['authors'] else "Unknown"
        categories = ", ".join(book['categories']) if book['categories'] else "N/A"
        description = book['description'][:200] if book['description'] else "No description"
        canonical_tag = " [WELL-KNOWN/CANONICAL WORK]" if book.get("is_canonical") else ""
        cluster_tag = f" [CATEGORY: {book['source_cluster']}]" if book.get("source_cluster") else ""

        formatted += f"{i}. {book['title']} by {authors}{canonical_tag}{cluster_tag}\n"
        formatted += f"   Categories: {categories}\n"
        formatted += f"   Description: {description}...\n\n"

    return formatted


def generate_recommendations(user_query: str, candidates: list, request_type: str) -> dict:
    """
    Use Claude to select and rank the most relevant books from candidates.

    Args:
        user_query: Original user query
        candidates: List of candidate books
        request_type: "general", "exploration", "follow_up", or "progression"

    Returns:
        {"recommendations": [{"title": ..., "authors": ..., "why_recommended": ..., "notes": ...}], "overall_notes": "..."}
    """
    if not candidates:
        return {"recommendations": [], "overall_notes": "No books found matching your query."}

    # Filter out likely self-published or low-quality books
    candidates = filter_questionable_books(candidates)

    if not candidates:
        return {"recommendations": [], "overall_notes": "No verified books found matching your query."}

    candidates_text = format_books_for_prompt(candidates)

    if request_type == "progression":
        instruction = """Select up to 10 books that work well as a reading progression from simplest to most complex.
Explain why each book fits in that sequence and how it builds on the previous one."""
    elif request_type == "exploration":
        instruction = """Based on their stated interest, suggest books in DIFFERENT but related areas they might enjoy.

Each candidate is tagged [CATEGORY: ...] showing which search cluster it came from - these
clusters were deliberately built to be genuinely different categories (not synonyms of each
other), so use this tag directly to check your own diversity:
- Your final selection MUST include books from AT LEAST 3 DIFFERENT [CATEGORY: ...] tags,
  not just whichever category happened to return the most/best-looking candidates.
- Do not let one category (even if it has the most or highest-quality candidates) dominate
  the list. If category A has 20 strong candidates and category B has 3 weaker ones, still
  pick from B rather than filling every slot from A - the user explicitly asked what ELSE
  they might enjoy, so a list that's secretly still 80% the original category fails the
  actual request even if each individual book is a good match.
- If a category's candidates are all genuinely poor fits (wrong age, wrong format, clearly
  irrelevant), it's fine to skip it - but don't skip a category just because another one is
  more convenient or has more options.

Explain the connection between their interest and each recommendation."""
    else:  # general or follow_up
        instruction = """Select up to 10 of the best books that match their interest or need.
Explain why each book is a good fit."""

    system_prompt = BOOK_RECOMMENDATION_SYSTEM_PROMPT_BASE.format(instruction=instruction)

    user_prompt = f"""User's request: "{user_query}"

Available books from our catalog:

{candidates_text}

Select up to 10 of the best books and return ONLY valid JSON with your recommendations."""

    message = anthropic_client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt
    )

    response_text = extract_text(message).strip()

    try:
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]

        recommendations = json.loads(response_text.strip())
        return recommendations
    except json.JSONDecodeError as e:
        print(f"Error parsing recommendations: {e}")
        return {
            "recommendations": [],
            "overall_notes": "Error generating recommendations"
        }


def recommend_books(user_query: str, candidates_data: dict) -> dict:
    """
    Main function to generate recommendations from candidate books.

    Args:
        user_query: Original user query
        candidates_data: Output from fetch_candidate_books.fetch_candidate_books()

    Returns:
        For general: {"query": ..., "request_type": ..., "recommendations": [...], "overall_notes": "..."}
        For progression: {"query": ..., "request_type": "progression", "levels": [...]}
    """
    request_type = candidates_data.get("request_type", "general")

    if request_type == "progression":
        return _recommend_progression(user_query, candidates_data)
    else:
        return _recommend_general(user_query, candidates_data, request_type)


def _recommend_general(user_query: str, candidates_data: dict, request_type: str) -> dict:
    """Generate recommendations for general/exploration/follow_up queries."""
    books = candidates_data.get("books", [])

    recommendations = generate_recommendations(user_query, books, request_type)

    result = {
        "query": user_query,
        "request_type": request_type,
        "search_query": candidates_data.get("search_query", ""),
        "audience_range": candidates_data.get("audience_range", ""),
        "candidates_found": candidates_data.get("total_results", 0),
        "recommendations": recommendations.get("recommendations", []),
        "overall_notes": recommendations.get("overall_notes", "")
    }
    # Phase 2 retry debug info - only present if a retry actually happened
    if candidates_data.get("retrieval_attempts"):
        result["retrieval_debug"] = candidates_data.get("retrieval_debug", [])
        result["retrieval_attempts"] = candidates_data["retrieval_attempts"]
    return result


def _recommend_progression(user_query: str, candidates_data: dict) -> dict:
    """Generate recommendations for progression queries, one per level."""
    levels = candidates_data.get("levels", [])

    results = {
        "query": user_query,
        "request_type": "progression",
        "age_context": candidates_data.get("age_context", ""),
        "levels": []
    }

    for level in levels:
        books = level.get("books", [])
        level_num = level.get("level", 0)
        level_description = level.get("description", "")

        recommendations = generate_recommendations(user_query, books, "progression")

        level_result = {
            "level": level_num,
            "description": level_description,
            "search_query": level.get("search_query", ""),
            "audience_range": level.get("audience_range", ""),
            "candidates_found": level.get("total_results", 0),
            "recommendations": recommendations.get("recommendations", []),
            "notes": recommendations.get("overall_notes", "")
        }
        # Phase 2 retry debug info - only present if this level actually retried
        if level.get("retrieval_attempts"):
            level_result["retrieval_debug"] = level.get("retrieval_debug", [])
            level_result["retrieval_attempts"] = level["retrieval_attempts"]
        results["levels"].append(level_result)

    return results

