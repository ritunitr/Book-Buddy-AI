"""
Observability helpers (Phase 1a: LangSmith tracing).

Shared by intent_extractor.py and book_recommender.py, the two modules that
create Anthropic clients.
"""

from types import SimpleNamespace
from langsmith.wrappers import wrap_anthropic


def traced_anthropic_client(client):
    """
    Wrap an Anthropic client so every messages.create() call is traced to
    LangSmith (latency, input/output tokens, model). No-ops safely if
    LangSmith isn't configured (no LANGSMITH_API_KEY) - tracing is always
    optional, never required for the app to function.

    Works around a bug in langsmith==0.12.4's wrap_anthropic: it
    unconditionally accesses client.completions.create (the legacy,
    pre-Messages-API Completions endpoint) without checking hasattr first -
    unlike the client.beta.messages block right next to it, which does check.
    anthropic>=1.2.0 has fully removed that attribute, so wrap_anthropic
    crashes on the current SDK pairing. We never call the legacy API, so a
    harmless placeholder that satisfies the attribute-existence check is
    sufficient; nothing about our actual traced calls (messages.create) is
    affected.
    """
    if not hasattr(client, "completions"):
        client.completions = SimpleNamespace(create=lambda *a, **kw: None)
    return wrap_anthropic(client)
