"""Tests for planner_agent module."""

import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
import planner_agent
import storage


# --- build_weekly_schedule tests ---


def test_schedule_has_5_posts_with_all_inputs():
    """With activity + trends + multiple repos, generates 5 posts."""
    schedule = planner_agent.build_weekly_schedule(
        has_project_activity=True,
        has_trending=True,
        num_repos=3,
    )
    assert len(schedule) == 5


def test_schedule_posts_on_tue_thu_sat():
    """All posts should be on Tuesday, Thursday, or Saturday."""
    schedule = planner_agent.build_weekly_schedule(
        has_project_activity=True,
        has_trending=True,
        num_repos=3,
    )
    days = {s["day"] for s in schedule}
    assert days == {"Tuesday", "Thursday", "Saturday"}


def test_schedule_platforms():
    """Should have LinkedIn and Twitter posts."""
    schedule = planner_agent.build_weekly_schedule(
        has_project_activity=True,
        has_trending=True,
        num_repos=3,
    )
    platforms = {s["platform"] for s in schedule}
    assert "linkedin" in platforms
    assert "twitter" in platforms


def test_schedule_tuesday_has_shared_theme():
    """Tuesday posts should have shared_theme=True."""
    schedule = planner_agent.build_weekly_schedule(
        has_project_activity=True,
        has_trending=True,
        num_repos=3,
    )
    tuesday_posts = [s for s in schedule if s["day"] == "Tuesday"]
    assert len(tuesday_posts) == 2
    assert all(s["shared_theme"] for s in tuesday_posts)


def test_schedule_fallback_no_activity():
    """Without project activity, build_diary should fall back."""
    schedule = planner_agent.build_weekly_schedule(
        has_project_activity=False,
        has_trending=True,
        num_repos=0,
    )
    modes = [s["content_mode"] for s in schedule]
    assert "build_diary" not in modes


def test_schedule_fallback_no_trends():
    """Without trending news, news_reaction should fall back."""
    schedule = planner_agent.build_weekly_schedule(
        has_project_activity=True,
        has_trending=False,
        num_repos=3,
    )
    modes = [s["content_mode"] for s in schedule]
    assert "news_reaction" not in modes


def test_schedule_fallback_single_repo():
    """With only 1 repo, cross_project_learnings should fall back."""
    schedule = planner_agent.build_weekly_schedule(
        has_project_activity=True,
        has_trending=True,
        num_repos=1,
    )
    modes = [s["content_mode"] for s in schedule]
    assert "cross_project_learnings" not in modes


def test_schedule_dates_are_future():
    """Scheduled dates should be in the future."""
    now = datetime.now()
    schedule = planner_agent.build_weekly_schedule(
        has_project_activity=True,
        has_trending=True,
        num_repos=3,
    )
    for s in schedule:
        date = datetime.strptime(s["date"], "%Y-%m-%d")
        assert date > now


def test_schedule_with_explicit_week_start():
    """Dates should be relative to the provided week_start."""
    start = datetime(2026, 4, 5)  # A Sunday
    schedule = planner_agent.build_weekly_schedule(
        has_project_activity=True,
        has_trending=True,
        num_repos=3,
        week_start=start,
    )
    dates = {s["date"] for s in schedule}
    assert "2026-04-07" in dates  # Tuesday
    assert "2026-04-09" in dates  # Thursday
    assert "2026-04-11" in dates  # Saturday


# --- _pick_mode tests ---


def test_pick_mode_primary_available():
    mode = planner_agent._pick_mode(
        "build_diary", ["thought_leadership"],
        has_project_activity=True, has_trending=True, num_repos=3,
    )
    assert mode == "build_diary"


def test_pick_mode_fallback_no_activity():
    mode = planner_agent._pick_mode(
        "build_diary", ["thought_leadership", "short_linkedin"],
        has_project_activity=False, has_trending=True, num_repos=3,
    )
    assert mode == "thought_leadership"


def test_pick_mode_fallback_no_trends():
    mode = planner_agent._pick_mode(
        "news_reaction", ["thought_leadership"],
        has_project_activity=True, has_trending=False, num_repos=3,
    )
    assert mode == "thought_leadership"


def test_pick_mode_fallback_single_repo():
    mode = planner_agent._pick_mode(
        "cross_project_learnings", ["short_linkedin", "thought_leadership"],
        has_project_activity=True, has_trending=True, num_repos=1,
    )
    assert mode == "short_linkedin"


# --- write_plan_file tests ---


def test_write_plan_file(temp_output):
    results = [
        {
            "day": "Tuesday",
            "date": "2026-04-07",
            "platform": "linkedin",
            "content_mode": "build_diary",
            "post_id": 1,
            "project_name": "insight-clips",
            "final_draft": "I built a thing and learned stuff about YouTube APIs.",
            "review": {"score": 4, "passed": True, "feedback": "Good", "suggestions": [], "slop_detected": []},
            "retries": 0,
        },
        {
            "day": "Tuesday",
            "date": "2026-04-07",
            "platform": "twitter",
            "content_mode": "short_twitter",
            "post_id": 2,
            "project_name": None,
            "final_draft": "YouTube APIs are pain. But the clips are worth it.",
            "review": {"score": 5, "passed": True, "feedback": "Great", "suggestions": [], "slop_detected": []},
            "retries": 0,
        },
    ]

    # Ensure plans dir exists
    plans_dir = os.path.join(temp_output["drafts"].replace("drafts", "plans"))
    os.makedirs(plans_dir, exist_ok=True)
    import config as cfg
    cfg.PLANS_DIR = plans_dir

    filepath = planner_agent.write_plan_file(results)
    assert os.path.isfile(filepath)

    with open(filepath) as f:
        content = f.read()

    assert "Week of 2026-04-07" in content
    assert "Tuesday" in content
    assert "build_diary" in content
    assert "short_twitter" in content
    assert "insight-clips" in content
    assert "4/5" in content
    assert "5/5" in content
    assert "#1" in content
    assert "#2" in content
    assert "score" in content  # CLI scoring hint


def test_write_plan_file_with_suggestions(temp_output):
    results = [
        {
            "day": "Thursday",
            "date": "2026-04-09",
            "platform": "linkedin",
            "content_mode": "thought_leadership",
            "post_id": 3,
            "project_name": None,
            "final_draft": "Hot take about AI.",
            "review": {
                "score": 3, "passed": False, "feedback": "Needs specifics",
                "suggestions": ["Add a concrete example"],
                "slop_detected": [],
            },
            "retries": 1,
        },
    ]

    plans_dir = os.path.join(temp_output["drafts"].replace("drafts", "plans"))
    os.makedirs(plans_dir, exist_ok=True)
    import config as cfg
    cfg.PLANS_DIR = plans_dir

    filepath = planner_agent.write_plan_file(results)
    with open(filepath) as f:
        content = f.read()

    assert "Needs review" in content
    assert "1 retries" in content
    assert "Add a concrete example" in content


# --- run_weekly_plan integration test ---


@pytest.mark.asyncio
async def test_run_weekly_plan_no_repos(temp_db, temp_output, monkeypatch):
    """With no repos configured, planner should still produce a plan."""
    monkeypatch.setattr(config, "PROJECT_REPOS", [])

    plans_dir = os.path.join(temp_output["drafts"].replace("drafts", "plans"))
    os.makedirs(plans_dir, exist_ok=True)
    monkeypatch.setattr(config, "PLANS_DIR", plans_dir)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="A thought leadership post about AI.")]

    with patch("content_agent.anthropic.Anthropic") as mock_content, \
         patch("reviewer_agent.anthropic.Anthropic") as mock_reviewer:
        mock_content.return_value.messages.create.return_value = mock_response

        review_response = MagicMock()
        review_response.content = [MagicMock(text='{"score": 4, "passed": true, "feedback": "Good", "suggestions": [], "slop_detected": []}')]
        mock_reviewer.return_value.messages.create.return_value = review_response

        filepath = await planner_agent.run_weekly_plan(days=90)

    assert filepath is not None
    assert os.path.isfile(filepath)
