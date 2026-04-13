"""Project Agent — extracts narratives from git repos with smart classification."""

import asyncio
import fnmatch
import os
import re
import subprocess
from typing import Optional

import anthropic

import config


# --- Commit Classification ---

# File patterns that indicate non-narrative commit types
CONFIG_PATTERNS = [
    "*.config.*", "tsconfig*", "package.json", "package-lock.json",
    "requirements.txt", "*.lock", ".env*", "Dockerfile", "docker-compose*",
    ".github/*", "*.toml", "setup.py", "setup.cfg", "Makefile",
    ".eslintrc*", ".prettierrc*", "babel.config*", "vite.config*",
    "webpack.config*", "render.yaml", "fly.toml", "vercel.json",
    "Procfile", ".gitignore", ".dockerignore",
]
DOCS_PATTERNS = ["README*", "docs/*", "*.md", "CHANGELOG*", "LICENSE*"]
TEST_PATTERNS = ["test_*", "*_test.*", "*_spec.*", "tests/*", "__tests__/*", "conftest.py"]

# Message prefixes (case-insensitive)
MESSAGE_RULES = [
    (r"^(feat|feature)[\s:(]", "feature"),
    (r"^(add|implement|create)\s", "feature"),
    (r"^(fix|bugfix|hotfix)[\s:(]", "fix"),
    (r"^(refactor|cleanup|clean up)[\s:(]", "refactor"),
    (r"^(docs?|update readme|update docs)[\s:(]", "docs"),
    (r"^(test|add test)[\s:(]", "test"),
    (r"^(style|design|ui|ux)[\s:(]", "design"),
    (r"(config|tsconfig|eslint|prettier|lint|ci:|build:|chore:)", "config"),
]

# Keywords suggesting design work
DESIGN_KEYWORDS = ["button", "layout", "page", "component", "modal", "screen", "sidebar", "navbar", "menu", "form", "icon", "theme", "color", "font", "responsive"]


def classify_commit(message: str, files_changed: list[str]) -> str:
    """Classify a commit by type based on message and changed files.

    Returns one of: feature, fix, refactor, config, docs, design, test.
    """
    message_lower = message.lower().strip()

    # 1. File-path heuristics (if ALL changed files match a non-narrative pattern)
    if files_changed:
        all_config = all(
            any(fnmatch.fnmatch(f, p) or fnmatch.fnmatch(os.path.basename(f), p) for p in CONFIG_PATTERNS)
            for f in files_changed
        )
        if all_config:
            return "config"

        all_docs = all(
            any(fnmatch.fnmatch(f, p) or fnmatch.fnmatch(os.path.basename(f), p) for p in DOCS_PATTERNS)
            for f in files_changed
        )
        if all_docs:
            return "docs"

        all_tests = all(
            any(fnmatch.fnmatch(f, p) or fnmatch.fnmatch(os.path.basename(f), p) for p in TEST_PATTERNS)
            for f in files_changed
        )
        if all_tests:
            return "test"

    # 2. Commit message prefix heuristics
    for pattern, commit_type in MESSAGE_RULES:
        if re.search(pattern, message_lower):
            return commit_type

    # 3. Fallback: check for design keywords in message
    if any(kw in message_lower for kw in DESIGN_KEYWORDS):
        return "design"

    # 4. Default to feature (generous — better to surface than hide)
    return "feature"


# --- Interestingness Scoring ---

COMMIT_WEIGHTS = {
    "feature": 1.0,
    "design": 0.8,
    "fix": 0.5,
    "docs": 0.2,
    "refactor": 0.1,
    "config": 0.0,
    "test": 0.0,
}


def _staleness_factor(relative_date: str) -> float:
    """Return a multiplier (0.0-1.0) based on how recent a commit is.

    Parses git's --date=relative format (e.g. '3 days ago', '2 weeks ago').
    """
    match = re.search(r"(\d+)\s+(second|minute|hour|day|week|month|year)", relative_date.lower())
    if not match:
        return 0.5  # unknown format, mild penalty

    num = int(match.group(1))
    unit = match.group(2)
    days_map = {"second": 0, "minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}
    approx_days = num * days_map.get(unit, 1)

    if approx_days <= 7:
        return 1.0
    elif approx_days <= 30:
        return 0.7
    elif approx_days <= 60:
        return 0.4
    else:
        return 0.2


def score_project(repo_data: dict) -> float:
    """Score a project's postability from 0.0 to 1.0.

    Higher scores mean more interesting content for social posts.
    """
    commits = repo_data.get("commits", [])
    if not commits:
        return 0.0

    weighted_sum = 0.0
    for c in commits:
        commit_type = c.get("type", "feature")
        weight = COMMIT_WEIGHTS.get(commit_type, 0.0)
        # Verbose fix messages suggest a debugging story
        if commit_type == "fix" and len(c.get("message", "")) > 60:
            weight = 0.7
        weighted_sum += weight

    base_score = weighted_sum / len(commits)

    # Message quality multiplier
    avg_msg_len = sum(len(c.get("message", "")) for c in commits) / len(commits)
    if avg_msg_len > 40:
        base_score *= 1.2
    elif avg_msg_len < 20:
        base_score *= 0.8

    # Recency penalty: penalize repos where most recent commit is old
    most_recent_date = commits[0].get("date", "")
    base_score *= _staleness_factor(most_recent_date)

    return min(1.0, max(0.0, base_score))


# --- Git Scanning ---

COMMIT_SEP = "---COMMIT_SEP---"


def _parse_git_log(raw_output: str) -> list[dict]:
    """Parse git log output with COMMIT_SEP sentinel into structured commits."""
    commits = []
    blocks = raw_output.split(COMMIT_SEP)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split("\n")
        # First line is metadata: hash|message|author|date
        meta_line = lines[0].strip()
        if "|" not in meta_line:
            continue

        parts = meta_line.split("|", 3)
        if len(parts) < 2:
            continue

        # Remaining lines are file paths
        files_changed = [l.strip() for l in lines[1:] if l.strip()]

        message = parts[1].strip()
        commit_type = classify_commit(message, files_changed)

        commits.append({
            "hash": parts[0].strip(),
            "message": message,
            "author": parts[2].strip() if len(parts) > 2 else "",
            "date": parts[3].strip() if len(parts) > 3 else "",
            "files_changed": files_changed,
            "type": commit_type,
        })

    return commits


def scan_repo(repo_path: str, days: int = 7) -> Optional[dict]:
    """Scan a single git repo and extract classified commit data.

    Returns a dict with repo name, classified commits, interesting commits,
    postability score, and README excerpt. Returns None if repo is invalid
    or has no recent activity.
    """
    if not os.path.isdir(repo_path):
        return None

    git_dir = os.path.join(repo_path, ".git")
    if not os.path.isdir(git_dir):
        return None

    repo_name = os.path.basename(repo_path)

    # Get recent commits with file lists
    try:
        log_output = subprocess.run(
            [
                "git", "log",
                f"--since={days} days ago",
                f"--pretty=format:{COMMIT_SEP}%h|%s|%an|%ad",
                "--date=relative",
                "--name-only",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if log_output.returncode != 0 or not log_output.stdout.strip():
        return None

    commits = _parse_git_log(log_output.stdout)
    if not commits:
        return None

    # Read README for project context
    readme_content = ""
    for readme_name in ["README.md", "readme.md", "README.txt"]:
        readme_path = os.path.join(repo_path, readme_name)
        if os.path.isfile(readme_path):
            try:
                with open(readme_path, "r") as f:
                    readme_content = f.read()[:1000]
            except OSError:
                pass
            break

    # Filter interesting commits
    interesting = [c for c in commits if c["type"] in ("feature", "fix", "design")]

    repo_data = {
        "repo_name": repo_name,
        "commits": commits,
        "commit_count": len(commits),
        "interesting_commits": interesting,
        "readme_excerpt": readme_content,
    }

    repo_data["postability_score"] = score_project(repo_data)

    return repo_data


def scan_repos(repo_paths: list[str], days: int = 7) -> list[dict]:
    """Scan multiple repos and return those with recent activity."""
    results = []
    for path in repo_paths:
        result = scan_repo(path, days)
        if result:
            results.append(result)
    return results


# --- Narrative Extraction ---

async def extract_narrative(repo_data: dict) -> str:
    """Use Claude Haiku to summarize interesting commits into a narrative.

    Falls back to heuristic summary on API failure.
    """
    interesting = repo_data.get("interesting_commits", [])
    repo_name = repo_data["repo_name"]
    readme = repo_data.get("readme_excerpt", "")

    if not interesting:
        return f"{repo_name}: maintenance work only (config, tests, refactoring)."

    # Build commit summary for Claude
    commit_lines = []
    for c in interesting[:15]:  # Cap at 15 to keep prompt short
        commit_lines.append(f"- [{c['type']}] {c['message']} ({c['date']})")

    commit_text = "\n".join(commit_lines)
    about = f"\nProject description: {readme.split(chr(10))[0].strip('# ')}" if readme else ""

    prompt = f"""Summarize this project's recent activity as a narrative for a social media ghostwriter.
Focus on: what changed for the user, what was challenging or interesting, what's the story here.
Write 3-5 sentences. Be specific — name features, not just "improvements".
Do NOT list commits. Tell the story.

Project: {repo_name}{about}

Recent commits:
{commit_text}"""

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        # Fallback: heuristic summary from top commits
        top = interesting[:3]
        summaries = ", ".join(c["message"] for c in top)
        return f"{repo_name}: recent work includes {summaries}."


# --- Build Project Context ---

async def build_project_context(repo_paths: list[str], days: int = 7) -> str:
    """Build a narrative-enriched project context string for the Content Agent.

    Scans repos, classifies commits, scores interestingness, and uses Claude
    to generate narratives. Returns a markdown string sorted by postability.
    """
    repos = scan_repos(repo_paths, days)

    if not repos:
        return "No recent project activity in the last week."

    # Sort by postability (most interesting first)
    repos.sort(key=lambda r: r["postability_score"], reverse=True)

    # Extract narratives concurrently
    narratives = await asyncio.gather(*(extract_narrative(r) for r in repos))

    sections = []
    for repo, narrative in zip(repos, narratives):
        score = repo["postability_score"]
        interesting = repo["interesting_commits"]

        # Commit type summary
        type_counts = {}
        for c in interesting:
            type_counts[c["type"]] = type_counts.get(c["type"], 0) + 1
        type_summary = ", ".join(f"{count} {t}" for t, count in type_counts.items())

        section = f"""### {repo['repo_name']} [Postability: {score:.2f}]
**What happened:** {narrative}
"""
        if type_summary:
            section += f"**Key commits ({type_summary}):**\n"
            for c in interesting[:5]:
                section += f"  - {c['type']}: {c['message']} ({c['date']})\n"

        if repo["readme_excerpt"]:
            first_line = repo["readme_excerpt"].split("\n")[0].strip("# ")
            section += f"\n**About:** {first_line}\n"

        sections.append(section)

    return f"## Recent Project Activity\n\n" + "\n---\n".join(sections)
