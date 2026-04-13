"""Learning Loop — analyze engagement data and surface insights."""

import json
import os
from datetime import datetime
from typing import Optional

import anthropic

import config
import storage


def score_post(post_id: int, likes: int, comments: int, shares: int, impressions: int = 0):
    """Record engagement metrics for a post via CLI."""
    post = storage.get_post_by_id(post_id)
    if not post:
        print(f"[ERROR] Post #{post_id} not found.")
        return False

    storage.score_post(post_id, likes, comments, shares, impressions)
    total = likes + comments * 3 + shares * 5  # Weighted engagement
    eng_rate = f" ({total / impressions * 100:.1f}% engagement rate)" if impressions > 0 else ""
    print(f"[OK] Post #{post_id} scored: {likes} likes, {comments} comments, {shares} shares, {impressions} impressions (weighted: {total}){eng_rate}")
    return True


def _build_analysis_prompt(posts: list[dict]) -> str:
    """Build the prompt for weekly engagement analysis."""
    post_summaries = []
    for p in posts:
        engagement = ""
        if p["status"] == "published":
            total = p["engagement_likes"] + p["engagement_comments"] * 3 + p["engagement_shares"] * 5
            impressions = p.get("engagement_impressions", 0)
            eng_rate = f", engagement rate: {total / impressions * 100:.1f}%" if impressions > 0 else ""
            engagement = (
                f"  Engagement: {p['engagement_likes']} likes, "
                f"{p['engagement_comments']} comments, "
                f"{p['engagement_shares']} shares, "
                f"{impressions} impressions (weighted: {total}{eng_rate})"
            )
        else:
            engagement = "  Engagement: not yet tracked"

        post_summaries.append(
            f"Post #{p['id']} [{p['platform']}] ({p['content_mode']}) — "
            f"Project: {p['project_name'] or 'N/A'}\n"
            f"  Status: {p['status']}\n"
            f"{engagement}\n"
            f"  Content preview: {p['content'][:200]}..."
        )

    return "\n\n".join(post_summaries)


async def analyze_engagement() -> Optional[dict]:
    """Run weekly engagement analysis on recent posts.

    Returns the insight dict, or None on failure.
    """
    posts = storage.get_recent_posts(days=30)

    if not posts:
        print("[INFO] No posts found for analysis.")
        return None

    published = [p for p in posts if p["status"] == "published"]
    if len(published) < 3:
        print(f"[INFO] Only {len(published)} published posts with engagement data. Need at least 3 for meaningful analysis.")
        return None

    post_summaries = _build_analysis_prompt(posts)

    system_prompt = """You are an engagement analyst for a PM's social media brand.
Analyze the posts and engagement data below. Find patterns in what works and what doesn't.

Respond with ONLY valid JSON:
{
    "top_format": "<which post structure gets most engagement>",
    "top_topic": "<which topic/theme resonates most>",
    "top_tone": "<which tone/style performs best>",
    "best_time_linkedin": "<best posting time if discernible, or 'insufficient data'>",
    "best_time_twitter": "<best posting time if discernible, or 'insufficient data'>",
    "key_insight": "<the single most actionable insight from this data>",
    "recommendations": [
        "<specific recommendation 1>",
        "<specific recommendation 2>",
        "<specific recommendation 3>"
    ],
    "avoid": ["<what to avoid based on low performers>"]
}

Be specific. Reference actual post examples. Don't give generic social media advice."""

    user_message = f"""Analyze these {len(posts)} posts ({len(published)} with engagement data):

{post_summaries}"""

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        insight = json.loads(raw)

        # Save to database
        storage.save_learning_insight(
            posts_analyzed=len(posts),
            top_format=insight.get("top_format", ""),
            top_topic=insight.get("top_topic", ""),
            top_tone=insight.get("top_tone", ""),
            best_time_linkedin=insight.get("best_time_linkedin", ""),
            best_time_twitter=insight.get("best_time_twitter", ""),
            raw_insight=json.dumps(insight, indent=2),
        )

        # Write to insights file
        _write_insight_file(insight, len(posts), len(published))

        return insight

    except (json.JSONDecodeError, IndexError) as e:
        print(f"[ERROR] Could not parse analysis response: {e}")
        return None
    except anthropic.APIError as e:
        print(f"[ERROR] Learning Loop API error: {e}")
        return None


def _write_insight_file(insight: dict, total_posts: int, published_posts: int):
    """Write insight to a markdown file in output/insights/."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    filepath = os.path.join(config.INSIGHTS_DIR, f"{date_str}-analysis.md")

    recs = "\n".join(f"- {r}" for r in insight.get("recommendations", []))
    avoids = "\n".join(f"- {a}" for a in insight.get("avoid", []))

    content = f"""# Engagement Analysis — {date_str}

**Posts analyzed:** {total_posts} ({published_posts} with engagement data)

## Key Insight
{insight.get('key_insight', 'N/A')}

## What Works
- **Best format:** {insight.get('top_format', 'N/A')}
- **Best topic:** {insight.get('top_topic', 'N/A')}
- **Best tone:** {insight.get('top_tone', 'N/A')}
- **Best time (LinkedIn):** {insight.get('best_time_linkedin', 'N/A')}
- **Best time (Twitter):** {insight.get('best_time_twitter', 'N/A')}

## Recommendations
{recs}

## Avoid
{avoids}
"""
    with open(filepath, "w") as f:
        f.write(content)

    print(f"[OK] Insight written to {filepath}")


def get_latest_insight_for_prompt() -> Optional[str]:
    """Get the latest learning insight formatted for the Content Agent prompt."""
    insight = storage.get_latest_insight()
    if not insight or not insight.get("raw_insight"):
        return None

    try:
        data = json.loads(insight["raw_insight"])
        parts = [
            f"Top performing format: {data.get('top_format', 'N/A')}",
            f"Top topic: {data.get('top_topic', 'N/A')}",
            f"Best tone: {data.get('top_tone', 'N/A')}",
            f"Key insight: {data.get('key_insight', 'N/A')}",
        ]
        recs = data.get("recommendations", [])
        if recs:
            parts.append("Recommendations: " + "; ".join(recs))
        return "\n".join(parts)
    except (json.JSONDecodeError, KeyError):
        return None
