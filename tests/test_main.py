"""Tests for main.py orchestrator — integration and output formatting."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import main
import storage


def test_write_drafts_file(temp_output):
    results = [
        {
            "platform": "linkedin",
            "content_mode": "build_diary",
            "post_id": 1,
            "final_draft": "I built insight-clips and learned about YouTube APIs.",
            "review": {"score": 4, "passed": True, "feedback": "Good", "suggestions": [], "slop_detected": []},
            "retries": 0,
        },
        {
            "platform": "twitter",
            "content_mode": "build_diary",
            "post_id": 2,
            "final_draft": "Just shipped a YouTube insight extractor. The API was pain.",
            "review": {"score": 3, "passed": False, "feedback": "Needs more personality", "suggestions": ["Add humor"], "slop_detected": []},
            "retries": 1,
        },
    ]

    filepath = main.write_drafts_file(results)
    assert os.path.isfile(filepath)

    with open(filepath) as f:
        content = f.read()

    assert "Linkedin" in content or "LinkedIn" in content
    assert "Twitter" in content
    assert "4/5" in content
    assert "3/5" in content
    assert "1 retries" in content
    assert "insight-clips" in content
    assert "--score" in content  # CLI hint
    assert "Post ID:** 1" in content


def test_write_drafts_file_with_suggestions(temp_output):
    results = [
        {
            "platform": "linkedin",
            "content_mode": "hot_take",
            "post_id": 1,
            "final_draft": "Hot take here",
            "review": {
                "score": 3, "passed": False,
                "feedback": "Needs specifics",
                "suggestions": ["Add project name", "Include a number"],
                "slop_detected": ["I'm excited to share"],
            },
            "retries": 0,
        },
    ]

    filepath = main.write_drafts_file(results)
    with open(filepath) as f:
        content = f.read()

    assert "Add project name" in content
    assert "I'm excited to share" in content


def test_run_list_empty(temp_db, capsys):
    main.run_list()
    captured = capsys.readouterr()
    assert "No posts found" in captured.out


def test_run_list_with_posts(temp_db, capsys):
    storage.save_post(content="Test post content here", platform="linkedin", content_mode="build_diary")
    main.run_list()
    captured = capsys.readouterr()
    assert "linkedin" in captured.out
    assert "build_diary" in captured.out


def test_run_score(temp_db, capsys):
    post_id = storage.save_post(content="Test", platform="linkedin", content_mode="build_diary")

    args = MagicMock()
    args.score = post_id
    args.likes = 25
    args.comments = 3
    args.shares = 2
    main.run_score(args)

    post = storage.get_post_by_id(post_id)
    assert post["engagement_likes"] == 25
    assert post["status"] == "published"
