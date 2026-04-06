"""Tests for learning_loop module."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

import learning_loop
import storage


def test_score_post_success(temp_db):
    post_id = storage.save_post(
        content="Test", platform="linkedin", content_mode="build_diary",
    )
    result = learning_loop.score_post(post_id, likes=10, comments=5, shares=2)
    assert result is True

    post = storage.get_post_by_id(post_id)
    assert post["engagement_likes"] == 10
    assert post["status"] == "published"


def test_score_post_not_found(temp_db):
    result = learning_loop.score_post(999, likes=1, comments=0, shares=0)
    assert result is False


def test_get_latest_insight_for_prompt_none(temp_db):
    assert learning_loop.get_latest_insight_for_prompt() is None


def test_get_latest_insight_for_prompt_with_data(temp_db):
    raw = json.dumps({
        "top_format": "thread",
        "top_topic": "AI tools",
        "top_tone": "witty",
        "key_insight": "Threads get 3x engagement",
        "recommendations": ["Use more threads"],
    })
    storage.save_learning_insight(
        posts_analyzed=10, top_format="thread", top_topic="AI tools",
        top_tone="witty", best_time_linkedin="Tue", best_time_twitter="Thu",
        raw_insight=raw,
    )

    result = learning_loop.get_latest_insight_for_prompt()
    assert result is not None
    assert "thread" in result
    assert "Threads get 3x engagement" in result


def test_build_analysis_prompt(temp_db):
    storage.save_post(content="Post 1", platform="linkedin", content_mode="build_diary")
    post_id = storage.save_post(content="Post 2", platform="twitter", content_mode="hot_take")
    storage.score_post(post_id, likes=20, comments=5, shares=3)

    posts = storage.get_recent_posts()
    prompt = learning_loop._build_analysis_prompt(posts)
    assert "Post #" in prompt
    assert "linkedin" in prompt
    assert "20 likes" in prompt


def test_write_insight_file(temp_output):
    insight = {
        "top_format": "numbered list",
        "top_topic": "building tools",
        "top_tone": "casual",
        "best_time_linkedin": "Tuesday",
        "best_time_twitter": "Thursday",
        "key_insight": "Lists perform best",
        "recommendations": ["Use more lists", "Post on Tuesday"],
        "avoid": ["Long essays"],
    }
    learning_loop._write_insight_file(insight, total_posts=10, published_posts=7)

    files = os.listdir(temp_output["insights"])
    assert len(files) == 1
    assert files[0].endswith("-analysis.md")

    with open(os.path.join(temp_output["insights"], files[0])) as f:
        content = f.read()
    assert "Lists perform best" in content
    assert "Use more lists" in content
    assert "Long essays" in content


@pytest.mark.asyncio
async def test_analyze_engagement_not_enough_data(temp_db):
    # Only 1 published post — needs at least 3
    post_id = storage.save_post(content="Test", platform="linkedin", content_mode="build_diary")
    storage.score_post(post_id, likes=10, comments=2, shares=1)

    result = await learning_loop.analyze_engagement()
    assert result is None


@pytest.mark.asyncio
async def test_analyze_engagement_success(temp_db, temp_output):
    # Create 3 published posts
    for i in range(3):
        pid = storage.save_post(
            content=f"Post {i}", platform="linkedin", content_mode="build_diary",
        )
        storage.score_post(pid, likes=10 * (i + 1), comments=i, shares=i)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "top_format": "thread",
        "top_topic": "AI",
        "top_tone": "witty",
        "best_time_linkedin": "Tue",
        "best_time_twitter": "Thu",
        "key_insight": "Numbered lists win",
        "recommendations": ["Post more lists"],
        "avoid": ["Long text"],
    }))]

    with patch("learning_loop.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = await learning_loop.analyze_engagement()

    assert result is not None
    assert result["key_insight"] == "Numbered lists win"

    # Check DB was updated
    db_insight = storage.get_latest_insight()
    assert db_insight["top_format"] == "thread"

    # Check insight file was written
    files = os.listdir(temp_output["insights"])
    assert len(files) == 1
