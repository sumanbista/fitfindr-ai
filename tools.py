"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# Groq model used by the two LLM-backed tools.
GROQ_MODEL = "llama-3.3-70b-versatile"


def _chat(messages: list[dict], temperature: float) -> str:
    """
    Send a chat completion to Groq and return the response text.

    Returns a stripped string on success, or an empty string on any failure
    (missing key, network error, empty/blank response). Callers treat an empty
    string as the failure signal — this never raises, so a flaky LLM call can't
    crash the agent.
    """
    try:
        client = _get_groq_client()
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return ""


# ── helpers ───────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Lowercase `text` and split it into alphanumeric word tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _describe_item(new_item: dict) -> str:
    """Render a listing dict as a one-line description for an LLM prompt."""
    title = new_item.get("title", "an item")
    category = new_item.get("category", "unknown")
    style = ", ".join(new_item.get("style_tags", [])) or "n/a"
    colors = ", ".join(new_item.get("colors", [])) or "n/a"
    return f"{title} (category: {category}; style: {style}; colors: {colors})"


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Description keywords, lowercased and de-duplicated.
    keywords = {tok for tok in _tokenize(description) if tok}

    scored: list[tuple[int, dict]] = []
    for listing in listings:
        # Price filter (inclusive). Skip when no ceiling given.
        if max_price is not None and listing["price"] > max_price:
            continue

        # Size filter (case-insensitive substring, so "M" matches "S/M").
        if size is not None and size.strip().lower() not in listing["size"].lower():
            continue

        # Score by keyword overlap across title, description, and style_tags.
        # A keyword found in more fields scores higher, so multi-field matches
        # rank above incidental ones.
        title = listing["title"].lower()
        desc = listing["description"].lower()
        tags = " ".join(listing.get("style_tags", [])).lower()
        score = 0
        for kw in keywords:
            if kw in title:
                score += 1
            if kw in desc:
                score += 1
            if kw in tags:
                score += 1

        # Drop listings that matched no keywords at all.
        if score > 0:
            scored.append((score, listing))

    # Highest score first.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = _describe_item(new_item)
    items = wardrobe.get("items", []) if isinstance(wardrobe, dict) else []

    if not items:
        # Empty wardrobe → general styling advice, NOT an error.
        system = (
            "You are a thrift stylist. The user has no wardrobe entered yet, "
            "so give general styling advice for the item: what categories, "
            "colors, and vibes pair well with it. Suggest 1-2 complete looks in "
            "general terms. Keep it concise and concrete — no invented brand names."
        )
        user = (
            f"New thrifted item: {item_desc}\n\n"
            "The user hasn't added any wardrobe pieces yet. Suggest general ways "
            "to style this item."
        )
    else:
        # Populated wardrobe → specific combos naming real pieces.
        wardrobe_lines = "\n".join(
            f"- {it.get('name', 'unnamed')} — {it.get('category', '?')} — "
            f"{', '.join(it.get('style_tags', [])) or 'n/a'}"
            for it in items
        )
        system = (
            "You are a thrift stylist who builds outfits from pieces the user "
            "already owns. Suggest 1-2 complete head-to-toe looks. Only reference "
            "wardrobe items by their exact name as listed. Never invent items the "
            "user does not own. Keep it concise."
        )
        user = (
            f"New thrifted item: {item_desc}\n\n"
            f"The user's wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits built around the new item, naming the "
            "wardrobe pieces it pairs with."
        )

    return _chat(
        [{"role": "system", "content": system},
         {"role": "user", "content": user}],
        temperature=0.7,
    )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Defensive guard: no outfit to caption. Short-circuit before any LLM call.
    if not outfit or not outfit.strip():
        return "Can't create a fit card without an outfit suggestion."

    title = new_item.get("title", "this piece")
    price = new_item.get("price", "?")
    platform = new_item.get("platform", "a resale app")

    system = (
        "You write casual OOTD captions for social media — authentic, a little "
        "playful, never a product description. Rules: 2-4 sentences; mention the "
        "item name, its price, and the platform exactly once each; capture the "
        "outfit's specific vibe; no hashtag spam."
    )
    user = (
        f"Item: {title}, ${price}, found on {platform}\n\n"
        f"Outfit: {outfit}\n\n"
        "Write the caption."
    )

    # Higher temperature so captions vary across runs and inputs. Returns ""
    # on LLM/network failure, which the planning loop treats as a hard-stop.
    return _chat(
        [{"role": "system", "content": system},
         {"role": "user", "content": user}],
        temperature=0.9,
    )
