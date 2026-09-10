# SmartyPants

Claude-powered book recommendation backend with a canonical-search stage to
surface well-known titles that keyword search alone misses, plus a Gradio
frontend. Recommendations are grounded in real books retrieved from the
Google Books API — Claude ranks and explains candidates, it never invents
titles.

## How it works

A query goes through three stages:

1. **Intent extraction** (`scripts/intent_extractor.py`) — a Claude call turns
   the raw query into structured intent: themes, audience age range, genre,
   format, query type (general / progression / exploration), and — when the
   topic has an established canon — specific well-known titles to search for
   by name.
2. **Candidate retrieval** (`scripts/fetch_candidate_books.py`) — builds
   targeted Google Books queries from that intent across three signals that
   feed one merged candidate pool:
   - **Semantic search** — one query per extracted theme, so no single
     keyword's results dominate the pool
   - **Canonical search** — the named well-known titles looked up directly
     by title/author, so they aren't at the mercy of keyword-ranking luck
     (this is what lets *Do Androids Dream of Electric Sheep?* or *Little
     Blue Truck* surface even when generic topic keywords wouldn't rank them)
   - **Format/subject filters** — bias results toward books that actually
     *are* the requested format (e.g. a graphic novel), not books *about*
     that format (e.g. a librarian's guide to graphic novels)

   This stage also caps how much one prolific series/author can dominate the
   pool, and filters out non-books and format/genre mismatches.
3. **Recommendation generation** (`scripts/book_recommender.py`) — a second
   Claude call selects and explains the best matches from the candidate
   pool, judging fit holistically rather than by keyword-match count, and
   avoiding over-representing any one series.

Three query shapes are supported: general topic requests, multi-level
reading progressions (each level searched independently, with its own
canonical titles when applicable), and exploration queries (each candidate
category searched and tagged independently, so results are required to
span multiple genuinely different categories).

## Project structure

```
scripts/            FastAPI backend
  main.py             API entrypoint (/recommend, /health)
  intent_extractor.py Structured intent extraction (Claude)
  fetch_candidate_books.py  Google Books retrieval (semantic + canonical + format search)
  book_recommender.py Recommendation generation (Claude)
  prompts.py          All system prompts
  judge.py            Evaluation harness
  requirements.txt

frontend/           Gradio UI, talks to the backend only over HTTP
  app.py              UI wiring
  api_client.py        Backend HTTP client (the only file that knows the API contract)
  formatting.py        Response -> Markdown rendering
  requirements.txt

golden_dataset.json  48 evaluation test cases 
runs/                Aggregated evaluation run output
```

## Setup

Requires Python 3.10+, an [Anthropic API key](https://console.anthropic.com/),
and a [Google Books API key](https://developers.google.com/books).

```bash
git clone <repo-url>
cd SmartyPants
python3 -m venv venv
source venv/bin/activate
pip install -r scripts/requirements.txt

cp .env.example .env
# edit .env and fill in ANTHROPIC_API_KEY and GOOGLE_BOOKS_API_KEY
```

## Running the backend

```bash
cd scripts
uvicorn main:app --host 0.0.0.0 --port 8000
```

```bash
curl -X POST http://localhost:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{"query": "My 4 year old loves cars and trucks. What books would he enjoy?"}'
```

## Running the frontend

In a separate terminal, with the backend already running:

```bash
cd frontend
pip install -r requirements.txt
python app.py
```

Open the local URL Gradio prints (usually `http://127.0.0.1:7860`). See
`frontend/README.md` for configuring `BACKEND_URL` and deploying to
Hugging Face Spaces.

## Evaluation

```bash
python scripts/judge.py golden_dataset.json --save-intermediate
```

Runs the first 20 cases in `golden_dataset.json` (of 48 total) through the
live `/recommend` API,
then has a separate, stronger Claude model score the response 1-5 on
relevance, real-book verification, and selection quality — deliberately a
different model tier than production, so evaluation isn't grading its own
homework.
