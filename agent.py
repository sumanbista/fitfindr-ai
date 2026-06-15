"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parsing ───────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract search parameters from a natural-language query using regex.

    Deterministic (no LLM) so the parse step is fast, offline, and testable.
    Pulls out an optional price ceiling ("under $30", "$25", "below 40") and an
    optional size ("size M", "in size 8"), then treats the remaining words —
    with the price/size phrases and common lead-in filler stripped — as the
    free-text description fed to search_listings.

    Returns a dict: {"description": str, "size": str | None, "max_price": float | None}.
    """
    text = query.strip()

    # Price ceiling: "under $30" / "below 40" / "less than 25" / a bare "$30".
    max_price = None
    price_match = re.search(
        r"(?:under|below|less than|max(?:imum)?|<=?)\s*\$?\s*(\d+(?:\.\d+)?)",
        text, re.I,
    ) or re.search(r"\$\s*(\d+(?:\.\d+)?)", text)
    if price_match:
        max_price = float(price_match.group(1))

    # Size: "size M" / "in size 8" / "size XXS" / "size S/M".
    size = None
    size_match = re.search(r"\bsize\s+([a-z0-9/]+)", text, re.I)
    if size_match:
        size = size_match.group(1).upper()

    # Description: drop the price/size phrases and common lead-in filler.
    desc = re.sub(
        r"(?:under|below|less than|max(?:imum)?|<=?)\s*\$?\s*\d+(?:\.\d+)?",
        "", text, flags=re.I,
    )
    desc = re.sub(r"\$\s*\d+(?:\.\d+)?", "", desc)
    desc = re.sub(r"\b(?:in\s+)?size\s+[a-z0-9/]+", "", desc, flags=re.I)
    desc = re.sub(
        r"\b(?:i'?m\s+|i\s+am\s+)?(?:looking for|searching for|search for|"
        r"show me|find me|find|want)\b",
        "", desc, flags=re.I,
    )
    desc = re.sub(r"\s+", " ", desc).strip(" ,.-")

    return {"description": desc, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1 — initialize session state.
    session = _new_session(query, wardrobe)

    # Step 2 — parse the query into search parameters.
    parsed = _parse_query(query)
    session["parsed"] = parsed
    description = parsed["description"]
    if not description or not description.strip():
        session["error"] = "Tell me what kind of item you're looking for."
        return session

    # Step 3 — search. Branch on the result: no matches ends the run early,
    # so suggest_outfit is never called with empty input.
    results = search_listings(description, parsed["size"], parsed["max_price"])
    session["search_results"] = results
    if not results:
        criteria = [f"'{description}'"]
        if parsed["size"]:
            criteria.append(f"size {parsed['size']}")
        if parsed["max_price"] is not None:
            criteria.append(f"under ${parsed['max_price']:.0f}")
        session["error"] = (
            f"No listings matched {' '.join(criteria)} — try raising the price, "
            "removing the size filter, or using broader keywords."
        )
        return session

    # Step 4 — select the top-ranked listing and store it on the session.
    session["selected_item"] = results[0]

    # Step 5 — suggest an outfit. An empty/whitespace return signals an LLM
    # failure (the tool's convention); an empty wardrobe is handled inside the
    # tool and is NOT a failure here.
    outfit = suggest_outfit(session["selected_item"], wardrobe)
    session["outfit_suggestion"] = outfit
    if not outfit or not outfit.strip():
        session["error"] = (
            "Couldn't generate an outfit suggestion right now — please try again."
        )
        return session

    # Step 6 — create the shareable fit card. Empty/whitespace signals failure.
    fit_card = create_fit_card(outfit, session["selected_item"])
    session["fit_card"] = fit_card
    if not fit_card or not fit_card.strip():
        session["error"] = (
            "Couldn't generate a fit card right now — please try again."
        )
        return session

    # Step 7 — success: all three tools ran and the session is fully populated.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
