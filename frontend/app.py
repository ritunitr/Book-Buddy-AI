"""
SmartyPants Gradio App

UI ONLY. This file wires Gradio components to api_client.py (which calls the
backend) and formatting.py (which renders the response). It contains no
recommendation logic itself - no keyword extraction, no Google Books calls,
no Claude calls, no filtering/ranking. If the backend is ever replaced, only
api_client.py should need to change.
"""

import gradio as gr

from api_client import get_recommendations, check_backend_health, BackendError
from formatting import format_recommendations, format_error

EXAMPLE_QUERIES = [
    "My 4 year old son is into cars and trucks. Give me recommendations of books he'll enjoy.",
    "My 8-year-old is a reluctant reader but loves graphic novels. What adventure series should I get them?",
    "My son likes cars. Recommend a progression of books so he learns about engineering gradually.",
    "Recommend a sci-fi book that deals heavily with artificial intelligence ethics and consciousness.",
    "I want some spiritual guidance that can give me peace and direction.",
]


def handle_query(query: str) -> str:
    """Gradio event handler: query string -> Markdown to display."""
    try:
        response = get_recommendations(query)
        return format_recommendations(response)
    except BackendError as e:
        return format_error(str(e))


with gr.Blocks(title="SmartyPants Book Recommendations") as demo:
    gr.Markdown("# 📚 SmartyPants\nAsk for book recommendations in plain language.")

    with gr.Row():
        query_input = gr.Textbox(
            label="What are you looking for?",
            placeholder="e.g. My 4 year old loves dinosaurs, what books would she enjoy?",
            lines=2,
            scale=4,
        )
        submit_btn = gr.Button("Get Recommendations", variant="primary", scale=1)

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
    demo.launch()
