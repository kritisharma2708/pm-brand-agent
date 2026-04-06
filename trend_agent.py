"""Trend Agent (lightweight) — fetches trending topics from HackerNews."""

import json
import urllib.request
from typing import Optional


def fetch_hackernews_top(limit: int = 15) -> list[dict]:
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


def get_trending_summary(limit: int = 10) -> Optional[str]:
    """Get a formatted summary of trending topics for the Content Agent.

    Returns a string suitable for the news_reaction content mode,
    or None if no trends could be fetched.
    """
    stories = fetch_hackernews_top(limit=limit)
    if not stories:
        return None

    # Filter for AI/tech/product relevant stories by keyword
    keywords = [
        "ai", "llm", "gpt", "claude", "agent", "product", "startup",
        "saas", "api", "developer", "engineer", "pm", "build", "ship",
        "automation", "machine learning", "ml", "open source", "oss",
        "launch", "funding", "hiring", "remote", "coding", "programming",
    ]

    relevant = []
    for story in stories:
        title_lower = story["title"].lower()
        if any(kw in title_lower for kw in keywords):
            relevant.append(story)

    # If no keyword matches, just take the top 5 by score
    if not relevant:
        relevant = sorted(stories, key=lambda s: s["score"], reverse=True)[:5]

    lines = ["Here are today's trending topics on HackerNews:\n"]
    for i, s in enumerate(relevant[:5], 1):
        lines.append(f"{i}. {s['title']} (score: {s['score']})")

    lines.append("\nPick the ONE topic that's most relevant to AI, product management, "
                 "or building with technology. React to it with a genuine opinion.")

    return "\n".join(lines)
