---
title: Book-Buddy-AI
emoji: 📚
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 4.44.0
app_file: app.py
pinned: false
---

# Book-Buddy-AI Frontend

A Gradio UI for the Book-Buddy-AI book recommendation backend.

## Architecture

This directory is a self-contained frontend that talks to the backend
(`../scripts/main.py`) exclusively over HTTP, via `api_client.py`. It holds
no recommendation logic of its own:

- `api_client.py` — the only file that knows the backend's URL and request/response
  shape. If the backend is ever replaced or moved, this is the only file that
  should need to change.
- `formatting.py` — pure functions that turn a backend JSON response into
  Markdown for display. No decisions about which books to show or how to
  rank them - that's entirely the backend's job.
- `app.py` — Gradio UI wiring only.

## Running locally

1. Start the backend first (from the project root):
   ```
   cd scripts && uvicorn main:app --host 0.0.0.0 --port 8000
   ```
2. In a separate terminal, install frontend dependencies and run the app:
   ```
   cd frontend
   pip install -r requirements.txt
   python app.py
   ```
3. Open the local URL Gradio prints (usually http://127.0.0.1:7860).

## Configuration

Set `BACKEND_URL` if the backend isn't running on `http://localhost:8000`:
```
export BACKEND_URL=https://your-backend-host
python app.py
```

## Deploying to Hugging Face Spaces

This directory is structured to be pushed directly as a Space (the YAML
frontmatter above is Spaces' config format). The backend must be reachable
from wherever the Space runs - set `BACKEND_URL` as a Space secret to point
at your deployed backend.
