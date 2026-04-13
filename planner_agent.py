"""Weekly Planner Agent — orchestrates content generation for the upcoming week.

Generates 5 posts across 3 days (Tue/Thu/Sat), both LinkedIn and Twitter,
with dynamic theme assignment based on available content.
"""

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional

import config
import storage
from content_agent import generate_post
from learning_loop import get_latest_insight_for_prompt
from notify import send_drafts
from project_agent import build_project_context, scan_repos
from reviewer_agent import review_with_retry
from trend_agent import get_trending_summary


# --- Schedule Template ---
# Each day slot has: (day_name, weekday_offset_from_monday, platforms, primary_modes, fallback_modes)
# weekday: 0=Mon, 1=Tue, 3=Thu, 5=Sat

DAY_SLOTS = [
    {
        "day": "Tuesday",
        "weekday": 1,
        "posts": [
            {"platform": "linkedin", "primary": "build_diary", "fallbacks": ["thought_leadership", "short_linkedin"]},
            {"platform": "twitter", "primary": "short_twitter", "fallbacks": ["short_twitter"]},
        ],
        "shared_theme": True,  # Both posts draw from same project/topic
    },
    {
        "day": "Thursday",
        "weekday": 3,
        "posts": [
            {"platform": "linkedin", "primary": "news_reaction", "fallbacks": ["thought_leadership", "cross_project_learnings"]},
            {"platform": "twitter", "primary": "short_twitter", "fallbacks": ["short_twitter"]},
        ],
        "shared_theme": False,  # Different themes per platform
    },
    {
        "day": "Saturday",
        "weekday": 5,
        "posts": [
            {"platform": "linkedin", "primary": "cross_project_learnings", "fallbacks": ["short_linkedin", "thought_leadership"]},
        ],
        "shared_theme": False,
    },
]


def _next_weekday(start: datetime, weekday: int) -> datetime:
    """Find the next occurrence of a weekday (0=Mon) from start date."""
    days_ahead = weekday - start.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return start + timedelta(days=days_ahead)


def build_weekly_schedule(
    has_project_activity: bool,
    has_trending: bool,
    num_repos: int,
    week_start: Optional[datetime] = None,
) -> list[dict]:
    """Build a weekly schedule with dynamic mode assignment.

    Returns a list of dicts: {day, date, platform, content_mode, shared_theme}
    """
    if week_start is None:
        week_start = datetime.now()

    schedule = []

    for slot in DAY_SLOTS:
        post_date = _next_weekday(week_start, slot["weekday"])
        date_str = post_date.strftime("%Y-%m-%d")

        for post_spec in slot["posts"]:
            # Pick the best available mode
            mode = _pick_mode(
                post_spec["primary"],
                post_spec["fallbacks"],
                has_project_activity=has_project_activity,
                has_trending=has_trending,
                num_repos=num_repos,
            )

            schedule.append({
                "day": slot["day"],
                "date": date_str,
                "platform": post_spec["platform"],
                "content_mode": mode,
                "shared_theme": slot["shared_theme"],
            })

    return schedule


def _pick_mode(
    primary: str,
    fallbacks: list[str],
    has_project_activity: bool,
    has_trending: bool,
    num_repos: int,
) -> str:
    """Pick the best content mode based on available inputs."""
    candidates = [primary] + fallbacks

    for mode in candidates:
        if mode == "build_diary" and not has_project_activity:
            continue
        if mode == "news_reaction" and not has_trending:
            continue
        if mode == "cross_project_learnings" and num_repos < 2:
            continue
        return mode

    # Ultimate fallback
    return "short_linkedin" if "linkedin" in primary else "short_twitter"


async def run_weekly_plan(days: int = 90) -> Optional[str]:
    """Run the full weekly planning pipeline.

    1. Scan repos + fetch trends + get learning insight
    2. Build schedule
    3. Generate all posts in parallel
    4. Review all posts in parallel
    5. Save to DB with scheduled_date
    6. Write plan file

    Returns the plan file path, or None on failure.
    """
    print("[PLANNER] Starting weekly content plan...")

    # Step 1: Gather inputs
    repo_paths = config.PROJECT_REPOS
    print(f"[PLANNER] Scanning {len(repo_paths)} project(s)...")
    project_context = await build_project_context(repo_paths, days=days)

    has_activity = not project_context.startswith("No recent")
    repos = scan_repos(repo_paths, days=days)

    print("[PLANNER] Fetching trending topics...")
    trending = get_trending_summary(limit=15)

    insight = get_latest_insight_for_prompt()
    if insight:
        print("[PLANNER] Using learning insights from previous analysis.")

    # Pick spotlight project for build_diary posts
    spotlight_project = None
    if repos:
        rotation_weights = storage.get_project_rotation_weights(
            [r["repo_name"] for r in repos]
        )
        for repo in repos:
            repo["combined_score"] = (
                repo["postability_score"] * 0.6
                + rotation_weights.get(repo["repo_name"], 1.0) * 0.4
            )
        repos.sort(key=lambda r: r["combined_score"], reverse=True)
        spotlight_project = repos[0]["repo_name"]
        print(f"[PLANNER] Spotlight project: {spotlight_project}")

    # Step 2: Build schedule
    schedule = build_weekly_schedule(
        has_project_activity=has_activity,
        has_trending=trending is not None,
        num_repos=len(repos),
    )

    print(f"[PLANNER] Schedule: {len(schedule)} posts across {len(set(s['date'] for s in schedule))} days")
    for s in schedule:
        print(f"  {s['day']} ({s['date']}): {s['platform']} — {s['content_mode']}")

    # Step 3: Generate all posts in parallel
    print("[PLANNER] Generating posts...")
    gen_tasks = []
    for entry in schedule:
        hot_take = trending if entry["content_mode"] == "news_reaction" else None
        gen_tasks.append(
            generate_post(
                project_context=project_context,
                platform=entry["platform"],
                content_mode=entry["content_mode"],
                hot_take=hot_take,
                insight=insight,
            )
        )
    gen_results = await asyncio.gather(*gen_tasks)

    # Step 4: Review all posts in parallel
    posts_to_review = []
    for entry, content in zip(schedule, gen_results):
        if content:
            posts_to_review.append((entry, content))

    if not posts_to_review:
        print("[PLANNER] No posts generated. Check API key and project context.")
        return None

    print(f"[PLANNER] Reviewing {len(posts_to_review)} drafts...")
    review_tasks = [
        review_with_retry(
            draft=content,
            platform=entry["platform"],
            project_context=project_context,
            content_mode=entry["content_mode"],
        )
        for entry, content in posts_to_review
    ]
    review_results = await asyncio.gather(*review_tasks)

    # Step 5: Save to DB
    results = []
    for (entry, _), review_result in zip(posts_to_review, review_results):
        project_name = spotlight_project if entry["content_mode"] == "build_diary" else None

        post_id = storage.save_post(
            content=review_result["final_draft"],
            platform=entry["platform"],
            content_mode=entry["content_mode"],
            project_name=project_name,
            reviewer_score=review_result["review"].get("score"),
            reviewer_notes=review_result["review"].get("feedback"),
            scheduled_date=entry["date"],
        )

        if project_name:
            storage.record_project_feature(project_name, entry["content_mode"], post_id)

        results.append({
            **review_result,
            **entry,
            "post_id": post_id,
            "project_name": project_name,
        })

    # Step 6: Write plan file
    filepath = write_plan_file(results)
    print(f"\n[PLANNER] Weekly plan written to {filepath}")

    for r in results:
        score = r["review"].get("score", "?")
        status = "PASS" if r["review"].get("passed") else "REVIEW"
        print(f"  #{r['post_id']} {r['day']} [{r['platform']}] {r['content_mode']} — {score}/5 ({status})")

    # Send to Telegram
    dates = sorted(set(r["date"] for r in results))
    week_label = dates[0] if dates else "this week"
    await send_drafts(results, label=f"Weekly Plan — {week_label}")

    return filepath


def write_plan_file(results: list[dict]) -> str:
    """Write the weekly plan to a markdown file."""
    now = datetime.now()
    # Find the first scheduled date to name the file
    dates = sorted(set(r["date"] for r in results))
    week_label = dates[0] if dates else now.strftime("%Y-%m-%d")

    filepath = os.path.join(config.PLANS_DIR, f"week-of-{week_label}.md")

    lines = [
        f"# Content Plan — Week of {week_label}",
        f"Generated {now.strftime('%A, %B %d at %I:%M %p')} | {len(results)} posts scheduled\n",
    ]

    current_day = None
    for r in sorted(results, key=lambda x: (x["date"], x["platform"])):
        if r["day"] != current_day:
            current_day = r["day"]
            lines.append(f"\n## {r['day']}, {r['date']}")
            lines.append("")

        score = r["review"].get("score", "?")
        status = "Ready to post" if r["review"].get("passed") else "Needs review"
        retries = r.get("retries", 0)
        retry_note = f" ({retries} retries)" if retries > 0 else ""

        lines.append(f"### {r['platform'].title()} — {r['content_mode']}")
        lines.append(f"**Score:** {score}/5 — {status}{retry_note}")
        lines.append(f"**Post ID:** #{r['post_id']}")

        if r.get("project_name"):
            lines.append(f"**Project:** {r['project_name']}")

        if r["review"].get("suggestions"):
            lines.append(f"**Suggestions:** {'; '.join(r['review']['suggestions'])}")

        lines.append(f"\n{r['final_draft']}\n")
        lines.append("---")

    lines.append(
        "\n*To score a post after publishing:* "
        "`python3 main.py score <post_id> --likes N --comments N --shares N --impressions N`"
    )

    content = "\n".join(lines)
    with open(filepath, "w") as f:
        f.write(content)

    return filepath
