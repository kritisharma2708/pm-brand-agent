"""Tests for content_agent module."""

import os

import pytest

import content_agent


def test_load_voice_profile_with_file(sample_voice_profile):
    profile = content_agent.load_voice_profile()
    assert "linkedin" in profile
    assert "twitter" in profile
    assert profile["voice_dna"]["identity"] == "PM who builds with AI"


def test_load_voice_profile_missing_file(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "VOICE_PROFILE_PATH", str(tmp_path / "nope.yaml"))
    profile = content_agent.load_voice_profile()
    assert "linkedin" in profile  # Falls back to defaults


def test_load_voice_samples(sample_voice_samples):
    samples = content_agent.load_voice_samples()
    assert "linkedin_01.md" in samples
    assert "I built a thing" in samples


def test_load_voice_samples_empty_dir(tmp_path, monkeypatch):
    import config
    empty_dir = str(tmp_path / "empty")
    os.makedirs(empty_dir)
    monkeypatch.setattr(config, "VOICE_SAMPLES_DIR", empty_dir)
    assert content_agent.load_voice_samples() == ""


def test_load_voice_samples_missing_dir(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "VOICE_SAMPLES_DIR", str(tmp_path / "nope"))
    assert content_agent.load_voice_samples() == ""


def test_build_system_prompt_linkedin(sample_voice_profile):
    voice = content_agent.load_voice_profile()
    samples = ""
    prompt = content_agent._build_system_prompt("linkedin", voice, samples)
    assert "ghostwriter" in prompt
    assert "PM who builds with AI" in prompt
    assert "I'm excited to announce" in prompt  # Anti-pattern


def test_build_system_prompt_twitter(sample_voice_profile):
    voice = content_agent.load_voice_profile()
    prompt = content_agent._build_system_prompt("twitter", voice, "")
    assert "Punchy and witty" in prompt


def test_build_system_prompt_with_insight(sample_voice_profile):
    voice = content_agent.load_voice_profile()
    prompt = content_agent._build_system_prompt("linkedin", voice, "", insight="Threads get 3x engagement")
    assert "Threads get 3x engagement" in prompt


def test_build_system_prompt_with_samples(sample_voice_profile, sample_voice_samples):
    voice = content_agent.load_voice_profile()
    samples = content_agent.load_voice_samples()
    prompt = content_agent._build_system_prompt("linkedin", voice, samples)
    assert "VOICE SAMPLES" in prompt


def test_build_user_prompt_build_diary():
    prompt = content_agent._build_user_prompt("Project context here", "build_diary")
    assert "build diary" in prompt.lower()
    assert "Project context here" in prompt


def test_build_user_prompt_hot_take():
    prompt = content_agent._build_user_prompt("Context", "hot_take", hot_take="AI is overrated")
    assert "AI is overrated" in prompt


def test_build_user_prompt_default():
    prompt = content_agent._build_user_prompt("Context", "showcase")
    assert "showcasing" in prompt.lower()


def test_build_user_prompt_with_reviewer_feedback(sample_voice_profile):
    """Test that reviewer feedback gets injected into retry prompts."""
    prompt = content_agent._build_user_prompt("Context", "build_diary")
    assert "PREVIOUS ATTEMPT" not in prompt

    # The feedback injection happens in generate_post, not _build_user_prompt
    # So we test the full function integration separately
