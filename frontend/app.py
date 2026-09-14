"""
Book-Buddy-AI Gradio App

UI ONLY. This file wires Gradio components to api_client.py (which calls the
backend) and formatting.py (which renders the response). It contains no
recommendation logic itself - no keyword extraction, no Google Books calls,
no Claude calls, no filtering/ranking. If the backend is ever replaced, only
api_client.py should need to change.

Milestone 3 Enhancement: Feedback UI
- Users can rate recommendations (thumbs up/down)
- Feedback is sent to /feedback endpoint
- User profile is built from feedback patterns
"""

import os
import json

import gradio as gr

from api_client import get_recommendations, check_backend_health, BackendError, submit_feedback
from formatting import format_recommendations, format_error

EXAMPLE_QUERIES = [
    "My 4 year old son is into cars and trucks. Give me recommendations of books he'll enjoy.",
    "My 8-year-old is a reluctant reader but loves graphic novels. What adventure series should I get them?",
    "My son likes cars. Recommend a progression of books so he learns about engineering gradually.",
    "Recommend a sci-fi book that deals heavily with artificial intelligence ethics and consciousness.",
    "I want some spiritual guidance that can give me peace and direction.",
]


def handle_query(query: str, user_email: str, progress=gr.Progress()) -> tuple:
    """
    Gradio event handler: query string + email -> recommendations + feedback state.
    Returns: (formatted_recommendations, state_with_books)
    """
    progress(0, desc="🔍 Understanding your request...")
    try:
        response = get_recommendations(query)
        progress(0.9, desc="✨ Putting together your recommendations...")
        formatted = format_recommendations(response)

        # Extract book titles from response for feedback
        books = []
        if response.get("request_type") == "progression":
            for level in response.get("levels", []):
                for rec in level.get("recommendations", []):
                    books.append(rec.get("title", "Unknown"))
        else:
            for rec in response.get("recommendations", []):
                books.append(rec.get("title", "Unknown"))

        return formatted, {"books": books, "user_email": user_email, "query": query}
    except BackendError as e:
        return format_error(str(e)), {"books": [], "user_email": user_email, "query": query}


def handle_feedback(liked: list, rejected: list, feedback_text: str, state: dict) -> str:
    """
    Submit feedback to backend.

    Args:
        liked: List of liked book titles (selected)
        rejected: List of rejected book titles (selected)
        feedback_text: Optional user feedback
        state: Contains user_email and book list

    Returns:
        Confirmation message
    """
    if not state or not state.get("user_email"):
        return "❌ Please enter your email to submit feedback."

    if not liked and not rejected:
        return "ℹ️ Select at least one book you liked or rejected to give feedback."

    try:
        response = submit_feedback(
            user_email=state["user_email"],
            liked_titles=liked,
            rejected_titles=rejected,
            feedback_text=feedback_text
        )

        if response.get("success"):
            msg = f"✅ Feedback recorded! ({response.get('feedback_count', 0)} total feedbacks)"
            if response.get("summarizer_triggered"):
                msg += "\n🧠 Your profile is being updated..."
            return msg
        else:
            return f"❌ Error: {response.get('message', 'Unknown error')}"
    except BackendError as e:
        return f"❌ Error: {str(e)}"


with gr.Blocks(title="Book-Buddy-AI") as demo:
    gr.Markdown("# 📚 Book-Buddy-AI\nAsk for book recommendations in plain language.")

    # State to store current recommendations and user email
    state = gr.State({"books": [], "user_email": "", "query": ""})

    gr.Markdown("**What can I help you find today?**")
    with gr.Row():
        query_input = gr.Textbox(
            show_label=False,
            placeholder="e.g. My 4 year old loves dinosaurs, what books would she enjoy?",
            lines=2,
            scale=3,
        )
        user_email = gr.Textbox(
            show_label=False,
            placeholder="your@email.com (for personalized recommendations)",
            scale=1,
        )
        submit_btn = gr.Button("Get Recommendations", variant="primary", size="sm", scale=1)

    gr.Examples(examples=EXAMPLE_QUERIES, inputs=query_input)

    output = gr.Markdown(label="Recommendations")

    # Feedback section
    gr.Markdown("---\n### 📝 Rate These Recommendations")
    with gr.Row():
        liked_books = gr.Checkboxgroup(
            label="👍 I liked these",
            choices=[],
            interactive=True
        )
        rejected_books = gr.Checkboxgroup(
            label="👎 Not for me",
            choices=[],
            interactive=True
        )

    feedback_text = gr.Textbox(
        label="📝 Optional feedback (why you liked/rejected them)",
        placeholder="e.g., Too dark for my taste, or loved the fantasy element!",
        lines=2,
    )

    with gr.Row():
        feedback_btn = gr.Button("Submit Feedback", variant="secondary")
        clear_feedback_btn = gr.Button("Clear Feedback", variant="secondary", size="sm")

    feedback_output = gr.Textbox(
        label="Status",
        interactive=False,
        value=""
    )

    # Event handlers
    def update_feedback_choices(state_dict):
        """Update feedback checkboxes when new recommendations are fetched."""
        books = state_dict.get("books", [])
        return gr.Checkboxgroup(choices=books), gr.Checkboxgroup(choices=books)

    submit_btn.click(
        fn=handle_query,
        inputs=[query_input, user_email],
        outputs=[output, state]
    ).then(
        fn=update_feedback_choices,
        inputs=state,
        outputs=[liked_books, rejected_books]
    )

    query_input.submit(
        fn=handle_query,
        inputs=[query_input, user_email],
        outputs=[output, state]
    ).then(
        fn=update_feedback_choices,
        inputs=state,
        outputs=[liked_books, rejected_books]
    )

    feedback_btn.click(
        fn=handle_feedback,
        inputs=[liked_books, rejected_books, feedback_text, state],
        outputs=feedback_output
    )

    clear_feedback_btn.click(
        fn=lambda: ("", "", "", ""),
        outputs=[liked_books, rejected_books, feedback_text, feedback_output]
    )


if __name__ == "__main__":
    if not check_backend_health():
        print(
            "WARNING: backend health check failed. Make sure the backend is "
            "running (see scripts/main.py) and BACKEND_URL is set correctly "
            "if it's not on http://localhost:8000."
        )
    # Explicit queue() so the gr.Progress() indicator in handle_query renders
    # reliably regardless of the resolved Gradio version (requirements.txt
    # only pins >=4.0.0, and queuing defaults differ across versions).
    demo.queue()

    # 0.0.0.0 + $PORT: required for hosted platforms (Render, HF Spaces, etc.)
    # where the platform assigns the port dynamically and expects the app to
    # bind on all interfaces, not just localhost. Defaults (127.0.0.1:7860)
    # still apply for local dev when PORT isn't set.
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
    )
