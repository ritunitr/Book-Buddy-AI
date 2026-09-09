import json
import os
import sys
import re
import time
import anthropic
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize the Anthropic client
client = anthropic.Anthropic()

# API endpoint
API_BASE_URL = "http://localhost:8000"

# Use a strong, current model for judging — deliberately different tier from
# the production model (claude-haiku-4-5) so the judge isn't grading its own homework.
JUDGE_MODEL = "claude-sonnet-5"

# Judge prompt
JUDGE_SYSTEM_PROMPT = """You are an objective AI evaluation judge assessing a book recommendation system.
You will be given a user query, the system's generated response, and the expected behavior/criteria.

Evaluate the response on three diagnostic metrics using a score from 1 to 5 each:

1. **Relevance**: Does the response directly address the user's query and needs?
   - General queries: Are books related to the stated interest?
   - Progression queries: Is the progression appropriate (simple to complex)?
   - Exploration queries: Are books in adjacent/related areas?
   Score 5: Excellent match; 4: Good match; 3: Adequate; 2: Weak; 1: Off-topic

2. **Real Books**: Are the recommended books actual, published works (no hallucinations)?
   - All recommended books come from Google Books API, so all titles should be real/verified
   - Check for logical coherence: does the title, author, and description match? (e.g., not misattributing books)
   - Note: Some books may be obscure or recent and not in your training data, but if they come from Google Books they are real
   - IMPORTANT: if a title coincides with a more famous book you recognize but the author differs, consider that
     these may be two distinct real books sharing a similar title, rather than assuming the system misattributed
     a well-known work. Only flag as misattribution if you have strong reason to believe it's the same book.
   Score 5: All real with accurate metadata; 4: All real, minor metadata issues; 3: Mostly real but some confusion; 2: Some misattributed; 1: Many hallucinated

3. **Selection Quality**:
   - Progression queries: Do levels build logically from simple to complex? Are audience ranges appropriate?
   - General/exploration queries: Is the selection diverse, high-quality, and free of redundant series repetition?
   Score 5: Excellent execution; 4: Good execution; 3: Adequate; 2: Weak; 1: Poor

Then give an **overall_score** (1-5): your holistic judgment of this response's
quality for the user who asked the question - not simply the average of the
three metrics above, but weighted by what actually matters most for this
specific query. For example, a response with perfect relevance and real books
but a glaring omission of well-known, expected titles for the topic should
not automatically score a 5 overall, even if the three sub-scores look strong -
completeness against what a domain expert would produce matters too.

5 = Excellent, matches what a knowledgeable librarian would recommend
4 = Good, solid and trustworthy, minor gaps (e.g. missing an iconic title)
3 = Adequate, on-topic but noticeably incomplete or has real gaps
2 = Weak, significant relevance/quality problems
1 = Poor, off-topic, hallucinated, or unusable

Output your evaluation strictly in valid JSON format with EXACTLY these keys:
{
  "relevance_score": <1-5>,
  "real_books_score": <1-5>,
  "selection_quality_score": <1-5>,
  "overall_score": <1-5>,
  "feedback": "<brief explanation (1-2 sentences) focusing on any issues or strengths>"
}

Be consistent and deterministic: apply the same scoring standard every time you see
the same or similar input, so repeated evaluation runs are directly comparable.

Return ONLY the JSON, no markdown or explanation."""


def _extract_text(message) -> str:
    """Get the text content from a Claude response, regardless of block order.

    Adaptive thinking (on by default on current models) can return a
    ThinkingBlock before the TextBlock, so content[0] is not reliably text.
    Always select by type instead.
    """
    for block in message.content:
        if block.type == "text":
            return block.text
    raise ValueError("No text block found in response — only got: "
                      f"{[b.type for b in message.content]}")


def _extract_json(raw_text: str) -> dict:
    """Robustly pull a JSON object out of a model response, whether or not
    it's wrapped in markdown code fences or has surrounding whitespace."""
    text = raw_text.strip()

    # Strip ```json ... ``` or ``` ... ``` fences regardless of exact spacing
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    return json.loads(text)


def evaluate_response(user_query: str, system_response: str, expected_behavior: str) -> dict:
    """Sends the test case and response to Claude to judge performance."""
    prompt = f"""
User Query: {user_query}
Expected Behavior / Criteria: {expected_behavior}
System Response to Evaluate: {system_response}
"""

    # Note: temperature/top_p/top_k are no longer accepted for current models
    # (SDK v1.0+, Aug 2026) — determinism is now requested via the system
    # prompt itself instead of a sampling parameter. See the note at the
    # bottom of JUDGE_SYSTEM_PROMPT.
    message = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=2000,
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        timeout=30.0
    )
    try:
        result_text = _extract_text(message)
        return _extract_json(result_text)
    except Exception as e:
        return {"overall_score": None, "feedback": f"Failed to parse judge output: {e}"}


def get_recommendation_from_api(query: str, conversation_history=None, save_results: bool = False) -> dict:
    """Call the /recommend API endpoint."""
    payload = {
        "query": query,
        "save_results": save_results,  # Enable saving of intermediate data
        "max_results": 20  # Must be <= 20 per API validation
    }
    # NOTE: the current /recommend endpoint does not yet accept conversation
    # history. This is passed through so the call is ready the moment the
    # backend supports it, but today it will simply be ignored server-side.
    if conversation_history:
        payload["conversation_history"] = conversation_history

    try:
        response = requests.post(
            f"{API_BASE_URL}/recommend",
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        return {"success": True, "data": response.json()}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)}


def format_response_for_evaluation(api_response: dict) -> str:
    """Format API response for Claude evaluation. Handles both general and progression responses."""
    if not api_response.get("success"):
        return f"ERROR: {api_response.get('error')}"

    data = api_response.get("data", {})
    request_type = data.get('request_type', 'unknown')
    lines = [f"Request Type: {request_type}", ""]

    if request_type == "progression":
        # Handle progression response (multiple levels)
        age_context = data.get('age_context', 'not specified')
        lines.append(f"Age Context: {age_context}")
        lines.append("")

        levels = data.get('levels', [])
        lines.append(f"Reading Progression ({len(levels)} levels):")

        for level in levels:
            lines.append("")
            lines.append(f"Level {level.get('level', '?')}: {level.get('description', '')}")
            lines.append(f"  Audience: {level.get('audience_range', 'N/A')}")

            recommendations = level.get('recommendations', [])
            lines.append(f"  Recommendations ({len(recommendations)}):")

            for i, rec in enumerate(recommendations, 1):
                lines.append(f"    {i}. {rec.get('title', 'Unknown')}")
                if rec.get('authors'):
                    lines.append(f"       Authors: {', '.join(rec.get('authors', []))}")
                lines.append(f"       Why: {rec.get('why_recommended', '')}")
                if rec.get('notes'):
                    lines.append(f"       Notes: {rec.get('notes', '')}")

            if level.get('notes'):
                lines.append(f"  Level Notes: {level.get('notes', '')}")
    else:
        # Handle general/exploration/follow_up response (single level)
        audience = data.get('audience_range', 'not specified')
        search_query = data.get('search_query', '')
        candidates = data.get('candidates_found', 0)

        lines.append(f"Audience: {audience}")
        if search_query:
            lines.append(f"Search Query: {search_query}")
        lines.append(f"Candidates Found: {candidates}")
        lines.append("")

        recommendations = data.get("recommendations", [])
        lines.append(f"Recommendations ({len(recommendations)}):")

        for i, rec in enumerate(recommendations, 1):
            lines.append("")
            lines.append(f"{i}. {rec.get('title', 'Unknown')}")
            if rec.get('authors'):
                lines.append(f"   Authors: {', '.join(rec.get('authors', ['Unknown']))}")
            lines.append(f"   Why: {rec.get('why_recommended', '')}")
            if rec.get('notes'):
                lines.append(f"   Notes: {rec.get('notes', '')}")

        if data.get("overall_notes"):
            lines.append("")
            lines.append(f"Overall Notes: {data.get('overall_notes')}")

    return "\n".join(lines)


def run_evaluation_harness(dataset_path: str, save_responses: bool = True, output_path: str = None, save_intermediate: bool = False):
    """
    Run evaluation on golden dataset.

    Args:
        dataset_path: Path to golden_dataset.json
        save_responses: Save evaluation results to file
        output_path: Where to save evaluation results
        save_intermediate: Save intermediate data (themes, candidates, recommendations) to runs/
    """
    # Default to evaluation_run_result directory if not specified
    if output_path is None:
        import os
        # scripts/ is one level down, so ../runs/evaluation_run_result/
        eval_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runs", "evaluation_run_result")
        os.makedirs(eval_dir, exist_ok=True)
        output_path = os.path.join(eval_dir, "evaluation_results.json")

    with open(dataset_path, "r") as f:
        dataset = json.load(f)

    # Restrict to the first 20 tests for evaluation
    dataset = dataset[:20]

    print(f"\n{'=' * 80}")
    print(f"Running evaluation on {len(dataset)} test cases from {dataset_path}")
    print(f"API: {API_BASE_URL}")
    if save_intermediate:
        print(f"Saving intermediate data to: runs/")
    print(f"{'=' * 80}\n")

    errored = []
    skipped = []
    all_results = []
    scores = []

    for idx, item in enumerate(dataset, 1):
        test_id = item["id"]
        query = item["user_query"]
        expected = item["expected_behavior"]
        category = item.get("category", "unknown")
        conversation_history = item.get("conversation_history")

        print(f"[{idx}/{len(dataset)}] ID:{test_id} | {category}", flush=True)
        print(f"Q: {query[:70]}...", flush=True)
        test_start = time.time()

        # Flag (don't silently fail) known-unsupported multi-turn cases so the
        # summary distinguishes "known gap" from "real regression."
        if category == "multi_turn":
            print("   (skipped: backend does not yet support conversation_history)\n", flush=True)
            skipped.append({"test_id": test_id, "reason": "conversation_history not supported by API yet"})
            all_results.append({"test_id": test_id, "status": "skipped"})
            continue

        # Call API
        api_response = get_recommendation_from_api(query, conversation_history, save_results=save_intermediate)
        elapsed_api = time.time() - test_start

        if not api_response.get("success"):
            error_msg = api_response.get('error', 'Unknown error')
            print(f"ERROR (API error: {error_msg}, {elapsed_api:.1f}s)\n", flush=True)
            errored.append({"test_id": test_id, "reason": f"API call failed: {error_msg}"})
            all_results.append({"test_id": test_id, "status": "error", "reason": "api_error", "error": error_msg})
            continue

        # Note: intermediate data is now saved to aggregated files in runs/
        # (per-query run directories disabled)

        # Evaluate
        formatted = format_response_for_evaluation(api_response)
        judge_start = time.time()
        eval_result = evaluate_response(query, formatted, expected)
        elapsed_total = time.time() - test_start
        elapsed_judge = time.time() - judge_start

        overall = eval_result.get("overall_score")

        if overall is None:
            print(
                f"ERROR - {eval_result.get('feedback')} "
                f"— api {elapsed_api:.1f}s, judge {elapsed_judge:.1f}s, total {elapsed_total:.1f}s\n",
                flush=True,
            )
            errored.append({"test_id": test_id, "evaluation": eval_result})
            all_results.append({
                "test_id": test_id,
                "status": "error",
                "query": query,
                "api_response": api_response.get("data"),
                "evaluation": eval_result,
                "elapsed_s": round(elapsed_total, 1)
            })
        else:
            scores.append(overall)
            print(
                f"SCORE: {overall}/5  (relevance {eval_result.get('relevance_score')}, "
                f"real_books {eval_result.get('real_books_score')}, "
                f"selection_quality {eval_result.get('selection_quality_score')}) "
                f"— {eval_result.get('feedback', '')}\n"
                f"   api {elapsed_api:.1f}s, judge {elapsed_judge:.1f}s, total {elapsed_total:.1f}s\n",
                flush=True,
            )
            all_results.append({
                "test_id": test_id,
                "status": "scored",
                "query": query,
                "api_response": api_response.get("data"),  # Full /recommend API response with recommendations
                "evaluation": eval_result,
                "elapsed_s": round(elapsed_total, 1)
            })

    # Summary
    scored = len(dataset) - len(skipped)
    avg_score = round(sum(scores) / len(scores), 2) if scores else None
    print(f"{'=' * 80}")
    if avg_score is not None:
        print(f"RESULTS: average score {avg_score}/5 across {len(scores)} scored tests "
              f"({len(errored)} errored, {len(skipped)} skipped: known gaps)")
        print(f"Score distribution: " + ", ".join(f"{s}: {scores.count(s)}" for s in sorted(set(scores), reverse=True)))
    else:
        print(f"RESULTS: no tests scored ({len(errored)} errored, {len(skipped)} skipped)")
    print(f"{'=' * 80}")

    if save_intermediate:
        print("\nIntermediate data saved to aggregated files in runs/:")
        print("  - all_themes_extracted.json")
        print("  - all_candidates_fetched.json")
        print("  - all_recommendations_generated.json")

    if save_responses:
        output = {
            "summary": {
                "total": len(dataset),
                "scored": scored,
                "average_score": avg_score,
                "score_distribution": {str(s): scores.count(s) for s in sorted(set(scores), reverse=True)},
                "errored": len(errored),
                "skipped": len(skipped),
            },
            "errored": errored,
            "skipped": skipped,
            "all_results": all_results,
        }
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults saved to: {output_path}\n")


if __name__ == "__main__":
    # Pass the dataset path as an argument, or default to the root project directory.
    # (scripts/ is one level down, so ../golden_dataset.json)
    dataset_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "golden_dataset.json"
    )

    # Check for --save-intermediate flag
    save_intermediate = "--save-intermediate" in sys.argv

    print(f"Dataset: {dataset_file}")
    print(f"Save Intermediate Data: {save_intermediate}\n")

    run_evaluation_harness(dataset_file, save_intermediate=save_intermediate)