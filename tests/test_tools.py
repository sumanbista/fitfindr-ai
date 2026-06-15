"""
Unit tests for the three FitFindr tools.

Run from the project root (fitfindr-ai/):
    pytest

search_listings is pure/local, so it's tested against the real dataset.
suggest_outfit and create_fit_card call Groq, so their LLM call (`tools._chat`)
is monkeypatched — that keeps the tests deterministic, offline, and able to
assert on each tool's branching logic and failure modes rather than on
nondeterministic model text.
"""

import tools
from tools import search_listings, suggest_outfit, create_fit_card


# A minimal listing dict, enough for the LLM tools to build their prompts.
ITEM = {
    "id": "lst_006",
    "title": "Graphic Tee — 2003 Tour Bootleg Style",
    "price": 24.0,
    "platform": "depop",
    "category": "tops",
    "style_tags": ["graphic tee", "vintage"],
    "colors": ["black"],
}


# ── search_listings (pure, no LLM) ──────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Failure mode: nothing matches → empty list, never an exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter():
    # "M" should match sizes like "S/M" (case-insensitive substring).
    results = search_listings("tee", size="M", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_ranks_best_match_first():
    results = search_listings("vintage graphic tee", max_price=30)
    assert results[0]["id"] == "lst_006"


# ── suggest_outfit (LLM mocked) ─────────────────────────────────────────────────

def test_suggest_outfit_empty_wardrobe_gives_general_advice(monkeypatch):
    # Failure mode: empty wardrobe is NOT an error — the general-advice prompt
    # is used and a non-empty string is returned.
    captured = {}

    def fake_chat(messages, temperature):
        captured["messages"] = messages
        return "Pairs well with neutral basics."

    monkeypatch.setattr(tools, "_chat", fake_chat)

    out = suggest_outfit(ITEM, {"items": []})

    assert out == "Pairs well with neutral basics."
    # The empty-wardrobe system prompt is the one that was used.
    assert "no wardrobe" in captured["messages"][0]["content"].lower()


def test_suggest_outfit_populated_wardrobe_names_real_pieces(monkeypatch):
    captured = {}

    def fake_chat(messages, temperature):
        captured["messages"] = messages
        return "Pair it with your Baggy jeans."

    monkeypatch.setattr(tools, "_chat", fake_chat)

    wardrobe = {"items": [
        {"name": "Baggy jeans", "category": "bottoms", "style_tags": ["denim"]},
    ]}
    out = suggest_outfit(ITEM, wardrobe)

    assert out
    # The real wardrobe piece is fed into the user prompt by name.
    assert "Baggy jeans" in captured["messages"][1]["content"]


def test_suggest_outfit_llm_failure_returns_empty(monkeypatch):
    # Failure mode: LLM/network error → "" so the planning loop hard-stops.
    monkeypatch.setattr(tools, "_chat", lambda messages, temperature: "")
    assert suggest_outfit(ITEM, {"items": []}) == ""


# ── create_fit_card (LLM mocked) ────────────────────────────────────────────────

def test_fit_card_empty_outfit_guard_skips_llm(monkeypatch):
    # Failure mode: missing/empty outfit → descriptive message, NO LLM call.
    def boom(*args, **kwargs):
        raise AssertionError("_chat must not be called for an empty outfit")

    monkeypatch.setattr(tools, "_chat", boom)

    for bad in ["", "   ", None]:
        assert (
            create_fit_card(bad, ITEM)
            == "Can't create a fit card without an outfit suggestion."
        )


def test_fit_card_success_returns_caption(monkeypatch):
    monkeypatch.setattr(tools, "_chat", lambda messages, temperature: "Cute fit!")
    assert create_fit_card("baggy jeans + combat boots", ITEM) == "Cute fit!"


def test_fit_card_llm_failure_returns_empty(monkeypatch):
    # Failure mode: LLM/network error → "" so the planning loop hard-stops.
    monkeypatch.setattr(tools, "_chat", lambda messages, temperature: "")
    assert create_fit_card("baggy jeans + combat boots", ITEM) == ""
