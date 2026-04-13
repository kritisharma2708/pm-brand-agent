"""Trend Agent (lightweight) — fetches trending topics from HackerNews."""

import json
import re
import urllib.request
from typing import Optional

import anthropic

import config

# AI/PM-specific terms — strong signal
INCLUDE_KEYWORDS = [
    "ai", "llm", "gpt", "claude", "gemini", "copilot", "agent", "rag",
    "machine learning", "ml", "deep learning", "neural",
    "product management", "saas", "startup", "launch",
    "open source", "oss", "developer tools", "devtools",
    "automation", "workflow", "no-code", "low-code",
]

# Broad terms — only count if story is high-scoring (>200)
WEAK_KEYWORDS = ["build", "api", "engineer", "developer", "funding", "hiring"]

# Skip these topics entirely
EXCLUDE_KEYWORDS = [
    "crypto", "bitcoin", "ethereum", "nft", "blockchain",
    "gaming", "game", "esports",
    "politics", "election", "congress", "supreme court",
    "sports", "nba", "nfl", "fifa",
    "celebrity", "hollywood",
]


def fetch_hackernews_top(limit: int = 30) -> list[dict]:
    """Fetch top stories from HackerNews. No auth needed."""
    try:
        req = urllib.request.urlopen(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=10,
        )
        story_ids = json.loads(req.read())[:limit]
    except Exception as e:
        print(f"[WARN] HackerNews fetch failed: {e}")
        return []

    stories = []
    for story_id in story_ids:
        try:
            req = urllib.request.urlopen(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                timeout=5,
            )
            item = json.loads(req.read())
            if item and item.get("title"):
                stories.append({
                    "title": item["title"],
                    "url": item.get("url", ""),
                    "score": item.get("score", 0),
                    "source": "hackernews",
                })
        except Exception:
            continue

    return stories


def _filter_stories(stories: list[dict]) -> list[dict]:
    """Two-pass keyword filter: exclude junk, then match by relevance."""
    relevant = []
    for story in stories:
        title_lower = story["title"].lower()

        # Skip excluded topics
        if any(kw in title_lower for kw in EXCLUDE_KEYWORDS):
            continue

        # Strong match
        if any(kw in title_lower for kw in INCLUDE_KEYWORDS):
            relevant.append(story)
            continue

        # Weak match — only if high-scoring
        if any(kw in title_lower for kw in WEAK_KEYWORDS) and story["score"] > 200:
            relevant.append(story)

    return relevant


def _rerank_with_claude(stories: list[dict]) -> list[dict]:
    """Use Claude Haiku to pick the most relevant stories for an AI/PM audience."""
    if not config.ANTHROPIC_API_KEY or len(stories) <= 2:
        return stories

    titles = "\n".join(
        f"{i+1}. {s['title']} (score: {s['score']})" for i, s in enumerate(stories)
    )

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": (
                    "Pick the 3 most relevant stories for someone who writes about "
                    "AI, product management, and building software products. "
                    "Return ONLY the numbers, comma-separated.\n\n"
                    f"{titles}"
                ),
            }],
        )
        text = response.content[0].text.strip()
        nums = [int(n) for n in re.findall(r"\d+", text)]
        picked = [stories[n - 1] for n in nums if 1 <= n <= len(stories)]
        return picked if picked else stories[:3]
    except Exception:
        return stories[:3]


def get_trending_summary(limit: int = 30) -> Optional[str]:
    """Get a formatted summary of trending topics for the Content Agent.

    Returns a string suitable for the news_reaction content mode,
    or None if no relevant trends could be found.
    """
    stories = fetch_hackernews_top(limit=limit)
    if not stories:
        return None

    relevant = _filter_stories(stories)
    if not relevant:
        return None

    # Rerank with Claude if we have enough candidates
    if len(relevant) > 3:
        relevant = _rerank_with_claude(relevant)

    lines = ["Here are today's trending topics on HackerNews:\n"]
    for i, s in enumerate(relevant[:5], 1):
        lines.append(f"{i}. {s['title']} (score: {s['score']})")

    lines.append("\nPick the ONE topic that's most relevant to AI, product management, "
                 "or building with technology. React to it with a genuine opinion.")

    return "\n".join(lines)
