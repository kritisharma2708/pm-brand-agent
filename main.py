"""PM Brand Agent — generates social media posts from your project activity."""

import argparse
import asyncio
import os
import sys
from datetime import datetime

import config
import storage
from content_agent import generate_post, generate_posts
from learning_loop import analyze_engagement, get_latest_insight_for_prompt, score_post
from project_agent import build_project_context, scan_repos
from reviewer_agent import review_with_retry
from planner_agent import run_weekly_plan
from trend_agent import get_trending_summary


def write_drafts_file(results: list[dict]) -> str:
    """Write draft posts to a markdown file. Returns the file path."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M")
    filepath = os.path.join(config.DRAFTS_DIR, f"{date_str}-{time_str}.md")

    lines = [f"# Draft Posts — {datetime.now().strftime('%B %d, %Y at %I:%M %p')}\n"]

    for i, result in enumerate(results, 1):
        review = result["review"]
        score = review.get("score", "?")
        status = "Ready to post" if review.get("passed") else "Needs review"
        retries = result.get("retries", 0)
        retry_note = f" ({retries} retries)" if retries > 0 else ""

        lines.append(f"## {i}. {result['platform'].title()} ({result['content_mode']})")
        lines.append(f"**Score:** {score}/5 — {status}{retry_note}")
        lines.append(f"**Post ID:** {result['post_id']}")

        if review.get("suggestions"):
            lines.append(f"**Suggestions:** {'; '.join(review['suggestions'])}")
        if review.get("slop_detected"):
            lines.append(f"**Slop detected:** {', '.join(review['slop_detected'])}")

        lines.append(f"\n{result['final_draft']}\n")
        lines.append("---\n")

    lines.append(
        "\n*To score a post after publishing:* "
        "`python3 main.py --score <post_id> --likes N --comments N --shares N`"
    )

    content = "\n".join(lines)
    with open(filepath, "w") as f:
        f.write(content)

    return filepath


async def run_generate(args):
    """Generate draft posts from project activity."""
    # Build project context
    repo_paths = config.PROJECT_REPOS
    if args.project:
        # Filter to specific project
        repo_paths = [p for p in repo_paths if os.path.basename(p) == args.project]
        if not repo_paths:
            # Try as a direct path or relative to workspace
            candidate = os.path.join(os.path.dirname(__file__), "..", args.project)
            if os.path.isdir(candidate):
                repo_paths = [os.path.abspath(candidate)]
            else:
                print(f"[ERROR] Project '{args.project}' not found in configured repos.")
                sys.exit(1)

    print(f"[INFO] Scanning {len(repo_paths)} project(s)...")
    project_context = await build_project_context(repo_paths, days=args.days)

    if project_context.startswith("No recent"):
        print("[INFO] No recent project activity found.")
        if not args.hot_take:
            print("[INFO] Try --hot-take to generate a post from a thought instead.")
            return

    # Get learning insights if available
    insight = get_latest_insight_for_prompt()
    if insight:
        print("[INFO] Using learning insights from previous analysis.")

    # Determine content mode
    content_mode = "build_diary"
    if args.hot_take:
        content_mode = "hot_take"

    # Generate posts for both platforms in parallel
    print(f"[INFO] Generating {content_mode} posts...")
    posts = await generate_posts(
        project_context=project_context,
        content_mode=content_mode,
        hot_take=args.hot_take,
        insight=insight,
    )

    if not posts:
        print("[ERROR] No posts generated. Check your API key and project context.")
        return

    # Review each post (parallel across posts)
    print(f"[INFO] Reviewing {len(posts)} drafts...")
    review_tasks = [
        review_with_retry(
            draft=post["content"],
            platform=post["platform"],
            project_context=project_context,
            content_mode=content_mode,
        )
        for post in posts
    ]
    review_results = await asyncio.gather(*review_tasks)

    # Save to database and collect results
    results = []
    for post, review_result in zip(posts, review_results):
        post_id = storage.save_post(
            content=review_result["final_draft"],
            platform=post["platform"],
            content_mode=post["content_mode"],
            project_name=args.project,
            reviewer_score=review_result["review"].get("score"),
            reviewer_notes=review_result["review"].get("feedback"),
        )

        if args.project:
            storage.record_project_feature(args.project, post["content_mode"], post_id)

        results.append({
            **review_result,
            "platform": post["platform"],
            "content_mode": post["content_mode"],
            "post_id": post_id,
        })

    # Write drafts file
    filepath = write_drafts_file(results)
    print(f"\n[OK] {len(results)} drafts written to {filepath}")

    # Print summary
    for r in results:
        score = r["review"].get("score", "?")
        status = "PASS" if r["review"].get("passed") else "REVIEW"
        print(f"  #{r['post_id']} [{r['platform']}] Score: {score}/5 ({status})")


async def run_generate_mix(args):
    """Generate a diverse mix of post types in one run."""
    print(f"[INFO] Scanning {len(config.PROJECT_REPOS)} project(s)...")
    project_context = await build_project_context(config.PROJECT_REPOS, days=args.days)

    insight = get_latest_insight_for_prompt()
    if insight:
        print("[INFO] Using learning insights from previous analysis.")

    # Pick one project to spotlight using postability + rotation weights
    repos = scan_repos(config.PROJECT_REPOS, days=args.days)
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
        print(f"[INFO] Spotlight: {spotlight_project} (score: {repos[0]['combined_score']:.2f})")

    # Fetch trending news
    print("[INFO] Fetching trending topics...")
    trending = get_trending_summary(limit=15)

    # Define the mix: each entry is (content_mode, platform, description)
    mix_plan = []

    # Long-form posts
    if spotlight_project:
        mix_plan.append(("build_diary", "linkedin", f"Build diary: {spotlight_project}"))

    if trending:
        mix_plan.append(("news_reaction", "linkedin", "News reaction"))

    if len(repos) >= 2:
        mix_plan.append(("cross_project_learnings", "linkedin", "Cross-project learnings"))

    mix_plan.append(("thought_leadership", "twitter", "Thought leadership"))

    # Short-form posts
    mix_plan.append(("short_linkedin", "linkedin", "Short LinkedIn — one sharp insight"))
    mix_plan.append(("short_twitter", "twitter", "Short tweet — one-liner"))
    mix_plan.append(("short_twitter", "twitter", "Short tweet — one-liner #2"))

    if not mix_plan:
        print("[INFO] No content to generate. Try --hot-take instead.")
        return

    # Generate all posts in parallel
    print(f"[INFO] Generating {len(mix_plan)} posts across {len(set(m[0] for m in mix_plan))} modes...")
    gen_tasks = []
    for content_mode, platform, desc in mix_plan:
        hot_take = trending if content_mode == "news_reaction" else None
        gen_tasks.append(
            generate_post(
                project_context=project_context,
                platform=platform,
                content_mode=content_mode,
                hot_take=hot_take,
                insight=insight,
            )
        )

    gen_results = await asyncio.gather(*gen_tasks)

    # Review all posts in parallel
    posts_to_review = []
    for (content_mode, platform, desc), content in zip(mix_plan, gen_results):
        if content:
            posts_to_review.append((content_mode, platform, desc, content))

    if not posts_to_review:
        print("[ERROR] No posts generated.")
        return

    print(f"[INFO] Reviewing {len(posts_to_review)} drafts...")
    review_tasks = [
        review_with_retry(
            draft=content,
            platform=platform,
            project_context=project_context,
            content_mode=content_mode,
        )
        for content_mode, platform, desc, content in posts_to_review
    ]
    review_results = await asyncio.gather(*review_tasks)

    # Save and collect results
    results = []
    for (content_mode, platform, desc, _), review_result in zip(posts_to_review, review_results):
        project_name = spotlight_project if content_mode == "build_diary" else None
        post_id = storage.save_post(
            content=review_result["final_draft"],
            platform=platform,
            content_mode=content_mode,
            project_name=project_name,
            reviewer_score=review_result["review"].get("score"),
            reviewer_notes=review_result["review"].get("feedback"),
        )
        if project_name:
            storage.record_project_feature(project_name, content_mode, post_id)
        results.append({
            **review_result,
            "platform": platform,
            "content_mode": content_mode,
            "post_id": post_id,
        })

    filepath = write_drafts_file(results)
    print(f"\n[OK] {len(results)} drafts written to {filepath}")
    for r in results:
        score = r["review"].get("score", "?")
        status = "PASS" if r["review"].get("passed") else "REVIEW"
        print(f"  #{r['post_id']} [{r['platform']}] {r['content_mode']} — Score: {score}/5 ({status})")


async def run_analyze():
    """Run engagement analysis on recent posts."""
    print("[INFO] Analyzing engagement data...")
    insight = await analyze_engagement()
    if insight:
        print(f"\n[OK] Key insight: {insight.get('key_insight', 'N/A')}")
        print(f"  Top format: {insight.get('top_format', 'N/A')}")
        print(f"  Top topic: {insight.get('top_topic', 'N/A')}")
        print(f"  Top tone: {insight.get('top_tone', 'N/A')}")
    else:
        print("[INFO] Not enough data for analysis. Score more posts first.")


def run_score(args):
    """Score a published post with engagement data."""
    score_post(args.score, args.likes, args.comments, args.shares)


def run_list():
    """List recent posts with their IDs and scores."""
    posts = storage.get_recent_posts(days=30)
    if not posts:
        print("[INFO] No posts found.")
        return

    print(f"\n{'ID':>4}  {'Platform':<10}  {'Mode':<12}  {'Score':>5}  {'Status':<10}  {'Engagement':<20}  {'Preview'}")
    print("-" * 100)
    for p in posts:
        eng = ""
        if p["status"] == "published":
            eng = f"L:{p['engagement_likes']} C:{p['engagement_comments']} S:{p['engagement_shares']}"
        preview = p["content"][:40].replace("\n", " ") + "..."
        r_score = f"{p['reviewer_score']}/5" if p["reviewer_score"] else "—"
        print(f"  {p['id']:>3}  {p['platform']:<10}  {p['content_mode'] or '—':<12}  {r_score:>5}  {p['status']:<10}  {eng:<20}  {preview}")


def main():
    parser = argparse.ArgumentParser(description="PM Brand Agent — generate posts from your projects")
    subparsers = parser.add_subparsers(dest="command")

    # Generate command (default)
    gen = subparsers.add_parser("generate", help="Generate draft posts")
    gen.add_argument("--project", "-p", help="Specific project name to focus on")
    gen.add_argument("--hot-take", "-t", help="Ad-hoc thought or reaction to generate a post from")
    gen.add_argument("--days", "-d", type=int, default=7, help="Days of git history to scan (default: 7)")

    # Mix command — generates diverse post types in one run
    mix = subparsers.add_parser("mix", help="Generate a diverse mix of post types (build diary, news, learnings, thought leadership)")
    mix.add_argument("--days", "-d", type=int, default=90, help="Days of git history to scan (default: 90)")

    # Score command
    sc = subparsers.add_parser("score", help="Score a published post with engagement data")
    sc.add_argument("post_id", type=int, help="Post ID to score")
    sc.add_argument("--likes", "-l", type=int, default=0)
    sc.add_argument("--comments", "-c", type=int, default=0)
    sc.add_argument("--shares", "-s", type=int, default=0)

    # Plan command — generate a full week of content
    plan = subparsers.add_parser("plan", help="Generate a weekly content plan (Tue/Thu/Sat)")
    plan.add_argument("--days", "-d", type=int, default=90, help="Days of git history to scan (default: 90)")

    # Analyze command
    subparsers.add_parser("analyze", help="Run weekly engagement analysis")

    # List command
    subparsers.add_parser("list", help="List recent posts")

    args = parser.parse_args()

    # Initialize database
    storage.init_db()

    if args.command == "plan":
        asyncio.run(run_weekly_plan(days=args.days))
    elif args.command == "mix":
        asyncio.run(run_generate_mix(args))
    elif args.command == "score":
        score_post(args.post_id, args.likes, args.comments, args.shares)
    elif args.command == "analyze":
        asyncio.run(run_analyze())
    elif args.command == "list":
        run_list()
    else:
        # Default to generate
        if not args.command:
            args = parser.parse_args(["generate"] + sys.argv[1:])
        asyncio.run(run_generate(args))


if __name__ == "__main__":
    main()
