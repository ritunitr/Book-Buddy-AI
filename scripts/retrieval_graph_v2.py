"""
Retrieval Graph v2: Claude-driven tool-calling orchestration

Replaces the fixed tier1/tier2 retry logic with an agentic loop where Claude
autonomously decides which search tools to call based on user intent and
results, using Anthropic's native tools parameter.

Key differences from retrieval_graph.py:
- No hard-coded tier1/tier2 logic
- Claude calls tools via Anthropic's tools parameter (native tool-calling)
- Claude sees results and decides what to search next
- Bounded by MAX_ATTEMPTS to avoid runaway loops
- Simpler to reason about: Claude decides, not Python state machine
"""

from typing import TypedDict
import json
from langgraph.graph import StateGraph, END

try:
    from google_books_client import (
        _search_multi_query,
        _search_known_titles,
        _filter_books_by_intent,
        _is_likely_non_book,
    )
    from observability import traced_anthropic_client
except ImportError:
    from .google_books_client import (
        _search_multi_query,
        _search_known_titles,
        _filter_books_by_intent,
        _is_likely_non_book,
    )
    from .observability import traced_anthropic_client

from anthropic import Anthropic
import os
from dotenv import load_dotenv

load_dotenv()
anthropic_client = traced_anthropic_client(Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")))

MIN_CANDIDATES = 20
MAX_ATTEMPTS = 5  # Claude gets 5 tool-call rounds before we stop regardless


# Define the tools Claude can call
SEARCH_TOOLS = [
    {
        "name": "search_google_books",
        "description": "Search Google Books for titles matching themes, keywords, or genres. Returns books with metadata (title, authors, description, categories).",
        "input_schema": {
            "type": "object",
            "properties": {
                "themes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Topic keywords or themes to search (e.g., ['fantasy', 'dragons', 'adventure'])"
                },
                "subject": {
                    "type": "string",
                    "description": "Optional subject/genre filter (e.g., 'juvenile fiction', 'picture books')"
                },
                "format_marker": {
                    "type": "string",
                    "description": "Optional format (e.g., 'graphic novel', 'chapter book')"
                }
            },
            "required": ["themes"]
        }
    },
    {
        "name": "search_known_titles",
        "description": "Search for specific book titles directly by name. Use when user mentions a specific book they like or want to find similar books to.",
        "input_schema": {
            "type": "object",
            "properties": {
                "titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific book titles to search for (e.g., ['Percy Jackson', 'The Hobbit'])"
                }
            },
            "required": ["titles"]
        }
    }
]


SEARCH_ORCHESTRATION_PROMPT = """You are a book search orchestrator. Your job is to help find good book recommendations by intelligently using search tools.

Given a user query and extracted intent (themes, known titles, audience, genre), you will:
1. Decide which search tools to call and with what parameters
2. See the results from each search
3. Decide if you have enough results (~20+ books) to make good recommendations
4. If not, try different search strategies (different themes, broader terms, etc.)
5. Stop when you have a good pool of books OR have tried reasonable variations

Strategy:
- If the user mentioned specific books, search for those FIRST to validate they exist
- Then search for thematically similar books
- If results are thin, try progressively broader search terms
- If a search returns 0 results, interpret that as feedback and adjust your search
- Stop when you have at least 20 candidates OR have tried 5 different searches

Remember:
- You can see the results from each search - use that to inform your next decision
- Don't just blindly call tools - reason about what the results tell you
- A search that returns "only 3 results" means you should try a different approach
- Subject and format filters are relevance boosts, not hard filters
"""


class SearchState(TypedDict):
    """State that flows through the search orchestration graph."""
    original_query: str
    intent_data: dict  # From extract_intent: themes, known_titles, audience, genre, etc.

    # Mutable during search
    all_books: list  # Accumulated books from all searches
    search_history: list  # Track what we searched for (for debugging/context)

    # Bookkeeping
    attempt: int
    is_complete: bool
    completion_reason: str


def _merge_and_filter_books(books_list: list, intent_like: dict) -> list:
    """Dedupe and filter books from all searches."""
    deduped = {}
    for book in books_list:
        title = book.get("title", "Unknown")
        if title not in deduped:
            deduped[title] = book
    return list(deduped.values())


def _execute_search_tool(tool_name: str, tool_input: dict) -> dict:
    """
    Execute a search tool and return structured results for Claude to see.
    Claude will use this to decide what to search next.
    """
    if tool_name == "search_google_books":
        themes = tool_input.get("themes", [])
        subject = tool_input.get("subject")
        format_marker = tool_input.get("format_marker")

        theme_clusters = [[t] for t in themes]
        books, queries_used = _search_multi_query(
            theme_clusters,
            subject=subject,
            format_marker=format_marker
        )

        return {
            "tool": "search_google_books",
            "input": tool_input,
            "result_count": len(books),
            "books_found": books,
            "search_queries": queries_used,
            "summary": f"Found {len(books)} books matching themes: {', '.join(themes)}"
        }

    elif tool_name == "search_known_titles":
        titles = tool_input.get("titles", [])
        books = _search_known_titles(titles)

        return {
            "tool": "search_known_titles",
            "input": tool_input,
            "result_count": len(books),
            "books_found": books,
            "summary": f"Found {len(books)} books from {len(titles)} title(s): {', '.join(titles)}"
        }


def search_and_decide_node(state: SearchState) -> dict:
    """
    Claude sees the current state and decides which tools to call.
    Handles the agentic loop: Claude calls tools, sees results, decides next move.
    """
    attempt = state["attempt"]
    all_books_so_far = state["all_books"]
    search_history = state["search_history"]

    # Build context for Claude
    context = f"""
User Query: {state['original_query']}

Extracted Intent:
- Themes: {state['intent_data'].get('themes', [])}
- Known Titles: {state['intent_data'].get('known_titles', [])}
- Audience: {state['intent_data'].get('audience_range', 'not specified')}
- Genre: {state['intent_data'].get('genre', 'not specified')}

Search Progress:
- Searches completed: {attempt}
- Books found so far: {len(all_books_so_far)}
- Search history: {json.dumps(search_history, indent=2)}

Current Status:
- Need at least {MIN_CANDIDATES} books to have a good recommendation pool
- Have found: {len(all_books_so_far)}
- Still need: {max(0, MIN_CANDIDATES - len(all_books_so_far))}

Decide: Should you search for more books, or are you done? Call tools if you need to search, or just say "DONE" if you're satisfied.
"""

    # Claude decides what to do
    messages = [{"role": "user", "content": context}]

    response = anthropic_client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        tools=SEARCH_TOOLS,
        tool_choice="auto",  # Claude picks which tools, or none
        system=SEARCH_ORCHESTRATION_PROMPT,
        messages=messages
    )

    # Process Claude's response
    new_books = []
    tool_calls_made = []
    stop_reason = response.stop_reason

    for block in response.content:
        if block.type == "tool_use":
            # Claude decided to call a tool
            tool_name = block.name
            tool_input = block.input

            # Execute the tool
            tool_result = _execute_search_tool(tool_name, tool_input)
            new_books.extend(tool_result["books_found"])

            tool_calls_made.append({
                "tool": tool_name,
                "input": tool_input,
                "result_summary": tool_result["summary"]
            })

        elif block.type == "text":
            # Claude provided reasoning/explanation
            print(f"[Claude reasoning] {block.text}")

    # Update state
    all_books = all_books_so_far + new_books
    all_books_deduped = _merge_and_filter_books(all_books, {
        "genre": state["intent_data"].get("genre", "not_specified"),
        "format": state["intent_data"].get("format", "not_specified")
    })

    new_search_history = search_history + tool_calls_made

    # Decide if we should continue
    is_complete = False
    completion_reason = ""

    if stop_reason == "end_turn" and not tool_calls_made:
        # Claude said DONE (no tools called)
        is_complete = True
        completion_reason = "Claude decided search is complete"
    elif len(all_books_deduped) >= MIN_CANDIDATES:
        # We have enough books
        is_complete = True
        completion_reason = f"Reached {MIN_CANDIDATES}+ candidates"
    elif attempt >= MAX_ATTEMPTS:
        # Max attempts reached
        is_complete = True
        completion_reason = f"Reached max {MAX_ATTEMPTS} attempts"

    return {
        "all_books": all_books_deduped,
        "search_history": new_search_history,
        "attempt": attempt + 1,
        "is_complete": is_complete,
        "completion_reason": completion_reason
    }


def should_continue_searching(state: SearchState) -> str:
    """Conditional edge: should we keep searching or stop?"""
    if state["is_complete"]:
        return "end"
    return "search"


def _build_graph():
    """Build the agentic search orchestration graph."""
    graph = StateGraph(SearchState)

    graph.add_node("search", search_and_decide_node)
    graph.set_entry_point("search")

    graph.add_conditional_edges(
        "search",
        should_continue_searching,
        {"search": "search", "end": END}
    )

    return graph.compile()


_SEARCH_GRAPH = _build_graph()


def run_retrieval_agentic(
    original_query: str,
    intent_data: dict,
) -> dict:
    """
    Run the agentic search orchestration using Claude's tool-calling.

    Claude autonomously decides which search strategies to try based on:
    - The original user query
    - Extracted intent (themes, known titles, audience, genre)
    - Feedback from actual search results

    Args:
        original_query: Raw user query
        intent_data: Output from extract_intent() with themes, known_titles, etc.

    Returns:
        {
            "books": [...candidate pool...],
            "search_history": [...what searches were performed...],
            "attempts_used": int,
            "completion_reason": str
        }
    """
    initial_state: SearchState = {
        "original_query": original_query,
        "intent_data": intent_data,
        "all_books": [],
        "search_history": [],
        "attempt": 0,
        "is_complete": False,
        "completion_reason": ""
    }

    final_state = _SEARCH_GRAPH.invoke(initial_state)

    return {
        "books": final_state["all_books"],
        "search_history": final_state["search_history"],
        "attempts_used": final_state["attempt"],
        "completion_reason": final_state["completion_reason"]
    }
