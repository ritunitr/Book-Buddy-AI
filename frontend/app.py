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


def handle_query(query: str, progress=gr.Progress()) -> str:
    """Gradio event handler: query string -> Markdown to display."""
    progress(0, desc="🔍 Understanding your request...")
    try:
        response = get_recommendations(query)
        progress(0.9, desc="✨ Putting together your recommendations...")
        return format_recommendations(response)
    except BackendError as e:
        return format_error(str(e))


with gr.Blocks(title="Book-Buddy-AI") as demo:
    gr.Markdown("# 📚 Book-Buddy-AI\nAsk for book recommendations in plain language.")

    gr.Markdown("**What can I help you find today?**")
    with gr.Row():
        query_input = gr.Textbox(
            show_label=False,
            placeholder="e.g. My 4 year old loves dinosaurs, what books would she enjoy?",
            lines=2,
            scale=4,
        )
        submit_btn = gr.Button("Get Recommendations", variant="primary", size="sm", scale=1)

    gr.Examples(examples=EXAMPLE_QUERIES, inputs=query_input)

    output = gr.Markdown(label="Recommendations")

    submit_btn.click(fn=handle_query, inputs=query_input, outputs=output)
    query_input.submit(fn=handle_query, inputs=query_input, outputs=output)


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
