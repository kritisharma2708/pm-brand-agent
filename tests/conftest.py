"""Shared test fixtures."""

import os
import tempfile

import pytest

import config
import storage


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Use a temporary database for each test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    storage.init_db()
    yield db_path


@pytest.fixture
def temp_output(tmp_path, monkeypatch):
    """Use temporary output directories."""
    drafts = str(tmp_path / "drafts")
    insights = str(tmp_path / "insights")
    os.makedirs(drafts)
    os.makedirs(insights)
    monkeypatch.setattr(config, "DRAFTS_DIR", drafts)
    monkeypatch.setattr(config, "INSIGHTS_DIR", insights)
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path))
    return {"drafts": drafts, "insights": insights}


@pytest.fixture
def sample_voice_profile(tmp_path, monkeypatch):
    """Create a temporary voice profile."""
    profile_path = str(tmp_path / "voice_profile.yaml")
    with open(profile_path, "w") as f:
        f.write("""
linkedin:
  tone: "Conversational"
  structure:
    - "Hook opener"
    - "Numbered takeaways"
  signature_moves:
    - "Name real people"
  anti_patterns:
    - "NEVER: I'm excited to announce"
twitter:
  tone: "Punchy and witty"
  structure:
    - "One-liner hook"
  anti_patterns:
    - "NEVER: Thread that could be one tweet"
voice_dna:
  identity: "PM who builds with AI"
  perspective: "Practitioner"
  humor: "Self-deprecating"
""")
    monkeypatch.setattr(config, "VOICE_PROFILE_PATH", profile_path)
    return profile_path


@pytest.fixture
def sample_voice_samples(tmp_path, monkeypatch):
    """Create temporary voice sample files."""
    samples_dir = str(tmp_path / "voice_samples")
    os.makedirs(samples_dir)
    with open(os.path.join(samples_dir, "linkedin_01.md"), "w") as f:
        f.write("# Platform: LinkedIn\nI built a thing and learned stuff.")
    monkeypatch.setattr(config, "VOICE_SAMPLES_DIR", samples_dir)
    return samples_dir


@pytest.fixture
def sample_project_context():
    return """## Recent Project Activity

### insight-clips [Postability: 0.73]
**What happened:** The team added a YouTube transcript fallback chain that tries multiple extraction methods before giving up. They also fixed a timeout issue with long video clip generation that was causing failures for videos over 30 minutes.
**Key commits (2 feature, 1 fix):**
  - feature: Add YouTube transcript fallback chain (2 days ago)
  - fix: Fix clip generation timeout for long videos (3 days ago)

**About:** AI-powered YouTube insight extraction tool
"""
