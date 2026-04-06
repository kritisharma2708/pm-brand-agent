"""Tests for reviewer_agent module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import reviewer_agent


def test_build_review_prompt(sample_voice_profile):
    voice = reviewer_agent._load_voice_profile()
    prompt = reviewer_agent._build_review_prompt(voice, "linkedin")
    assert "quality reviewer" in prompt
    assert "linkedin" in prompt.lower()
    assert "I'm excited to announce" in prompt  # Anti-pattern from profile


def test_build_review_prompt_twitter(sample_voice_profile):
    voice = reviewer_agent._load_voice_profile()
    prompt = reviewer_agent._build_review_prompt(voice, "twitter")
    assert "twitter" in prompt.lower()


@pytest.mark.asyncio
async def test_review_draft_parses_valid_json(sample_voice_profile, sample_voice_samples):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "score": 4,
        "passed": True,
        "feedback": "Good voice match",
        "suggestions": [],
        "slop_detected": [],
    }))]

    with patch("reviewer_agent.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = await reviewer_agent.review_draft("Test post", "linkedin")

    assert result["score"] == 4
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_review_draft_handles_markdown_json(sample_voice_profile, sample_voice_samples):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='```json\n{"score": 3, "passed": false, "feedback": "Needs work", "suggestions": ["Add specifics"], "slop_detected": []}\n```')]

    with patch("reviewer_agent.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = await reviewer_agent.review_draft("Test post", "linkedin")

    assert result["score"] == 3
    assert result["passed"] is False


@pytest.mark.asyncio
async def test_review_draft_handles_malformed_response(sample_voice_profile, sample_voice_samples):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="This is not JSON at all")]

    with patch("reviewer_agent.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = await reviewer_agent.review_draft("Test post", "linkedin")

    assert result["score"] == 3  # Default fallback
    assert "Could not parse" in result["feedback"]


@pytest.mark.asyncio
async def test_review_draft_handles_api_error(sample_voice_profile, sample_voice_samples):
    import anthropic as anthropic_module

    with patch("reviewer_agent.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = anthropic_module.APIError(
            message="Rate limited", request=MagicMock(), body=None,
        )
        result = await reviewer_agent.review_draft("Test post", "twitter")

    assert result["score"] == 3
    assert "API error" in result["feedback"]


@pytest.mark.asyncio
async def test_review_with_retry_passes_on_high_score(sample_voice_profile, sample_voice_samples):
    with patch("reviewer_agent.review_draft", new_callable=AsyncMock) as mock_review:
        mock_review.return_value = {
            "score": 5, "passed": True, "feedback": "Perfect",
            "suggestions": [], "slop_detected": [],
        }
        result = await reviewer_agent.review_with_retry(
            "Great post", "linkedin", "context", "build_diary",
        )

    assert result["final_draft"] == "Great post"
    assert result["retries"] == 0
    assert result["review"]["score"] == 5


@pytest.mark.asyncio
async def test_review_with_retry_retries_on_low_score(sample_voice_profile, sample_voice_samples):
    call_count = 0

    async def mock_review(draft, platform):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            return {
                "score": 1, "passed": False,
                "feedback": "Too corporate",
                "suggestions": ["Add personality"],
                "slop_detected": ["I'm excited to share"],
            }
        return {
            "score": 4, "passed": True,
            "feedback": "Much better",
            "suggestions": [], "slop_detected": [],
        }

    with patch("reviewer_agent.review_draft", side_effect=mock_review):
        with patch("content_agent.generate_post", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "Improved post"
            result = await reviewer_agent.review_with_retry(
                "Bad post", "linkedin", "context", "build_diary",
            )

    assert result["retries"] == 1
    assert result["final_draft"] == "Improved post"
    # Verify feedback was passed to content agent
    mock_gen.assert_called_once()
    call_kwargs = mock_gen.call_args
    assert "Too corporate" in call_kwargs.kwargs.get("reviewer_feedback", "")


@pytest.mark.asyncio
async def test_review_with_retry_max_retries_exhausted(sample_voice_profile, sample_voice_samples):
    with patch("reviewer_agent.review_draft", new_callable=AsyncMock) as mock_review:
        mock_review.return_value = {
            "score": 1, "passed": False,
            "feedback": "Still bad",
            "suggestions": [], "slop_detected": [],
        }
        with patch("content_agent.generate_post", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "Still not great"
            result = await reviewer_agent.review_with_retry(
                "Bad post", "linkedin", "context", "build_diary", max_retries=2,
            )

    assert result["retries"] == 2
    assert "WARNING" in result["review"]["feedback"]
