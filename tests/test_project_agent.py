"""Tests for project_agent module."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

import project_agent


# --- classify_commit tests ---


def test_classify_commit_feature_prefix():
    assert project_agent.classify_commit("feat: add login flow", []) == "feature"


def test_classify_commit_feature_add():
    assert project_agent.classify_commit("Add onboarding screen", []) == "feature"


def test_classify_commit_fix_prefix():
    assert project_agent.classify_commit("fix: null pointer in auth", []) == "fix"


def test_classify_commit_refactor():
    assert project_agent.classify_commit("refactor: extract helper", []) == "refactor"


def test_classify_commit_docs_prefix():
    assert project_agent.classify_commit("docs: update API reference", []) == "docs"


def test_classify_commit_test_prefix():
    assert project_agent.classify_commit("test: add coverage for auth", []) == "test"


def test_classify_commit_design_prefix():
    assert project_agent.classify_commit("ui: new modal layout", []) == "design"


def test_classify_commit_config_keyword():
    assert project_agent.classify_commit("chore: bump dependencies", []) == "config"


def test_classify_commit_config_files():
    assert project_agent.classify_commit("update deps", ["package.json"]) == "config"


def test_classify_commit_config_tsconfig():
    assert project_agent.classify_commit("update config", ["tsconfig.json"]) == "config"


def test_classify_commit_docs_files():
    assert project_agent.classify_commit("update", ["README.md"]) == "docs"


def test_classify_commit_test_files():
    assert project_agent.classify_commit("add coverage", ["tests/test_auth.py"]) == "test"


def test_classify_commit_design_keywords():
    assert project_agent.classify_commit("redesign the sidebar and navbar", []) == "design"


def test_classify_commit_fallback_to_feature():
    """Unrecognized commits default to feature."""
    assert project_agent.classify_commit("do interesting stuff", ["app.py"]) == "feature"


def test_classify_commit_mixed_files_message_wins():
    """Feature message takes priority even with some config files."""
    assert project_agent.classify_commit("feat: add search endpoint", ["api.py", "package.json"]) == "feature"


def test_classify_commit_all_config_files_override():
    """If ALL files are config, classify as config regardless of message."""
    assert project_agent.classify_commit("add search", ["package.json", "requirements.txt"]) == "config"


# --- score_project tests ---


def test_score_project_all_config():
    repo_data = {
        "commits": [
            {"type": "config", "message": "bump deps"},
            {"type": "config", "message": "update ci"},
            {"type": "config", "message": "fix lint"},
        ]
    }
    assert project_agent.score_project(repo_data) == 0.0


def test_score_project_all_features():
    repo_data = {
        "commits": [
            {"type": "feature", "message": "add login flow with OAuth integration"},
            {"type": "feature", "message": "implement search functionality with filters"},
            {"type": "feature", "message": "create user dashboard with analytics charts"},
        ]
    }
    score = project_agent.score_project(repo_data)
    assert score > 0.8


def test_score_project_mixed():
    repo_data = {
        "commits": [
            {"type": "feature", "message": "add search"},
            {"type": "config", "message": "bump deps"},
            {"type": "config", "message": "update ci"},
            {"type": "config", "message": "fix lint"},
        ]
    }
    score = project_agent.score_project(repo_data)
    # 1 feature out of 4 commits = 0.25, with short message penalty
    assert 0.1 < score < 0.5


def test_score_project_verbose_fix_bonus():
    repo_data = {
        "commits": [
            {"type": "fix", "message": "fix webhook URL parsing that broke when URLs had trailing slashes causing all notifications to fail silently"},
        ]
    }
    score = project_agent.score_project(repo_data)
    # Verbose fix gets 0.7 weight + message quality bonus
    assert score > 0.5


def test_score_project_empty():
    assert project_agent.score_project({"commits": []}) == 0.0


def test_score_project_message_quality_bonus():
    """Long descriptive messages get a multiplier."""
    short = {
        "commits": [{"type": "feature", "message": "add x"}]
    }
    long = {
        "commits": [{"type": "feature", "message": "add comprehensive search with fuzzy matching and filters"}]
    }
    assert project_agent.score_project(long) > project_agent.score_project(short)


# --- scan_repo tests ---


def test_scan_repo_invalid_path():
    assert project_agent.scan_repo("/nonexistent/path") is None


def test_scan_repo_not_a_git_repo(tmp_path):
    assert project_agent.scan_repo(str(tmp_path)) is None


def test_scan_repo_with_git_repo(tmp_path):
    """Create a real git repo with commits and scan it."""
    repo = tmp_path / "test-repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)

    (repo / "main.py").write_text("print('hello')")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "Add main module"], cwd=str(repo), capture_output=True)

    result = project_agent.scan_repo(str(repo))
    assert result is not None
    assert result["repo_name"] == "test-repo"
    assert result["commit_count"] >= 1
    assert any("Add main module" in c["message"] for c in result["commits"])
    # New fields
    assert "postability_score" in result
    assert "interesting_commits" in result
    assert result["commits"][0]["type"] == "feature"  # "Add main module" -> feature
    assert result["commits"][0]["files_changed"]  # Should have file list


def test_scan_repo_classifies_config_commits(tmp_path):
    """Config-only commits should be classified as config."""
    repo = tmp_path / "config-repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)

    (repo / "requirements.txt").write_text("flask==2.0")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "update deps"], cwd=str(repo), capture_output=True)

    result = project_agent.scan_repo(str(repo))
    assert result is not None
    assert result["commits"][0]["type"] == "config"
    assert len(result["interesting_commits"]) == 0
    assert result["postability_score"] == 0.0


def test_scan_repo_no_recent_commits(tmp_path):
    """A repo with only old commits returns None for days=0."""
    repo = tmp_path / "old-repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)

    (repo / "old.txt").write_text("old")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = "2020-01-01T00:00:00"
    env["GIT_COMMITTER_DATE"] = "2020-01-01T00:00:00"
    subprocess.run(["git", "commit", "-m", "Old commit"], cwd=str(repo), capture_output=True, env=env)

    result = project_agent.scan_repo(str(repo), days=1)
    assert result is None


def test_scan_repo_reads_readme(tmp_path):
    repo = tmp_path / "readme-repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)

    (repo / "README.md").write_text("# My Cool Project\nA description here.")
    (repo / "code.py").write_text("x = 1")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo), capture_output=True)

    result = project_agent.scan_repo(str(repo))
    assert result is not None
    assert "My Cool Project" in result["readme_excerpt"]


def test_scan_repos_filters_invalid(tmp_path):
    results = project_agent.scan_repos(["/nonexistent", str(tmp_path)])
    assert results == []


# --- extract_narrative tests ---


@pytest.mark.asyncio
async def test_extract_narrative_filters_config():
    """Narrative extraction only uses interesting commits."""
    repo_data = {
        "repo_name": "test-project",
        "interesting_commits": [],
        "readme_excerpt": "",
    }
    result = await project_agent.extract_narrative(repo_data)
    assert "maintenance" in result.lower()


@pytest.mark.asyncio
async def test_extract_narrative_fallback_on_api_error():
    """Falls back to heuristic summary on API failure."""
    repo_data = {
        "repo_name": "test-project",
        "interesting_commits": [
            {"type": "feature", "message": "add search", "date": "2 days ago"},
            {"type": "fix", "message": "fix timeout", "date": "3 days ago"},
        ],
        "readme_excerpt": "",
    }

    with patch("project_agent.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.side_effect = Exception("API error")
        result = await project_agent.extract_narrative(repo_data)

    assert "test-project" in result
    assert "add search" in result


@pytest.mark.asyncio
async def test_extract_narrative_calls_claude():
    """When interesting commits exist, calls Claude for narrative."""
    repo_data = {
        "repo_name": "cool-app",
        "interesting_commits": [
            {"type": "feature", "message": "add onboarding flow", "date": "1 day ago"},
        ],
        "readme_excerpt": "# Cool App\nA cool application",
    }

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Cool App added an onboarding flow to guide new users.")]

    with patch("project_agent.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = mock_response
        result = await project_agent.extract_narrative(repo_data)

    assert "onboarding" in result


# --- build_project_context tests ---


def test_build_project_context_no_repos():
    """Sync wrapper check — no repos returns fallback message."""
    import asyncio
    context = asyncio.run(project_agent.build_project_context([]))
    assert "No recent" in context


@pytest.mark.asyncio
async def test_build_project_context_with_repo(tmp_path):
    repo = tmp_path / "ctx-repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)

    (repo / "app.py").write_text("# app")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "Build the feature"], cwd=str(repo), capture_output=True)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ctx-repo added a new feature.")]

    with patch("project_agent.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = mock_response
        context = await project_agent.build_project_context([str(repo)])

    assert "ctx-repo" in context
    assert "Postability:" in context
    assert "What happened:" in context


@pytest.mark.asyncio
async def test_build_project_context_sorts_by_score(tmp_path):
    """Higher postability repos should appear first."""
    # Repo with feature commit
    feature_repo = tmp_path / "feature-repo"
    feature_repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(feature_repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(feature_repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(feature_repo), capture_output=True)
    (feature_repo / "app.py").write_text("# app")
    subprocess.run(["git", "add", "."], cwd=str(feature_repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: add amazing search functionality"], cwd=str(feature_repo), capture_output=True)

    # Repo with config commit only
    config_repo = tmp_path / "config-repo"
    config_repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(config_repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(config_repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(config_repo), capture_output=True)
    (config_repo / "requirements.txt").write_text("flask")
    subprocess.run(["git", "add", "."], cwd=str(config_repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "chore: bump deps"], cwd=str(config_repo), capture_output=True)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Repo narrative here.")]

    with patch("project_agent.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = mock_response
        context = await project_agent.build_project_context(
            [str(config_repo), str(feature_repo)]
        )

    # feature-repo should appear before config-repo
    feature_pos = context.index("feature-repo")
    config_pos = context.index("config-repo")
    assert feature_pos < config_pos
