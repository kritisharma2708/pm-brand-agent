"""Tests for storage module."""

import storage


def test_init_db_creates_tables(temp_db):
    conn = storage.get_connection()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {t["name"] for t in tables}
    assert "posts" in table_names
    assert "trends" in table_names
    assert "learning_insights" in table_names
    assert "project_features" in table_names
    conn.close()


def test_save_post_returns_id(temp_db):
    post_id = storage.save_post(
        content="Test post", platform="linkedin",
        content_mode="build_diary", project_name="test-project",
    )
    assert post_id == 1


def test_save_post_default_status_is_draft(temp_db):
    post_id = storage.save_post(
        content="Test", platform="linkedin", content_mode="build_diary",
    )
    post = storage.get_post_by_id(post_id)
    assert post["status"] == "draft"


def test_save_post_with_reviewer_data(temp_db):
    post_id = storage.save_post(
        content="Test", platform="twitter", content_mode="hot_take",
        reviewer_score=4, reviewer_notes="Good voice match",
    )
    post = storage.get_post_by_id(post_id)
    assert post["reviewer_score"] == 4
    assert post["reviewer_notes"] == "Good voice match"


def test_score_post_updates_engagement(temp_db):
    post_id = storage.save_post(
        content="Test", platform="linkedin", content_mode="build_diary",
    )
    storage.score_post(post_id, likes=42, comments=7, shares=3)

    post = storage.get_post_by_id(post_id)
    assert post["status"] == "published"
    assert post["engagement_likes"] == 42
    assert post["engagement_comments"] == 7
    assert post["engagement_shares"] == 3
    assert post["published_at"] is not None


def test_get_post_by_id_returns_none_for_missing(temp_db):
    assert storage.get_post_by_id(999) is None


def test_get_recent_posts_empty(temp_db):
    assert storage.get_recent_posts() == []


def test_get_recent_posts_returns_posts(temp_db):
    storage.save_post(content="Post 1", platform="linkedin", content_mode="build_diary")
    storage.save_post(content="Post 2", platform="twitter", content_mode="hot_take")

    posts = storage.get_recent_posts(days=7)
    assert len(posts) == 2


def test_save_learning_insight(temp_db):
    insight_id = storage.save_learning_insight(
        posts_analyzed=10,
        top_format="numbered list",
        top_topic="AI tools",
        top_tone="witty",
        best_time_linkedin="Tuesday 8am",
        best_time_twitter="Thursday 6pm",
        raw_insight='{"key": "value"}',
    )
    assert insight_id == 1


def test_get_latest_insight(temp_db):
    storage.save_learning_insight(
        posts_analyzed=5, top_format="thread", top_topic="building",
        top_tone="casual", best_time_linkedin="Mon", best_time_twitter="Wed",
        raw_insight='{"test": true}',
    )
    insight = storage.get_latest_insight()
    assert insight is not None
    assert insight["top_format"] == "thread"
    assert insight["posts_analyzed"] == 5


def test_get_latest_insight_returns_none_when_empty(temp_db):
    assert storage.get_latest_insight() is None


def test_multiple_posts_different_platforms(temp_db):
    storage.save_post(content="LinkedIn post", platform="linkedin", content_mode="build_diary")
    storage.save_post(content="Twitter post", platform="twitter", content_mode="build_diary")

    posts = storage.get_recent_posts()
    platforms = {p["platform"] for p in posts}
    assert platforms == {"linkedin", "twitter"}


# --- Rotation tracking tests ---


def test_record_project_feature(temp_db):
    post_id = storage.save_post(content="Test", platform="linkedin", content_mode="build_diary")
    storage.record_project_feature("insight-clips", "build_diary", post_id)

    conn = storage.get_connection()
    rows = conn.execute("SELECT * FROM project_features").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["project_name"] == "insight-clips"
    assert rows[0]["content_mode"] == "build_diary"
    assert rows[0]["post_id"] == post_id


def test_get_project_rotation_weights_no_history(temp_db):
    weights = storage.get_project_rotation_weights(["project-a", "project-b"])
    assert weights == {"project-a": 1.0, "project-b": 1.0}


def test_get_project_rotation_weights_penalizes_recent(temp_db):
    post_id = storage.save_post(content="Test", platform="linkedin", content_mode="build_diary")
    storage.record_project_feature("project-a", "build_diary", post_id)

    weights = storage.get_project_rotation_weights(["project-a", "project-b"])
    assert weights["project-b"] == 1.0
    assert weights["project-a"] < 1.0  # Recently featured = penalized


def test_get_project_rotation_weights_empty_list(temp_db):
    assert storage.get_project_rotation_weights([]) == {}


def test_get_project_rotation_weights_multiple_features(temp_db):
    """Multiple recent features for same project = larger penalty."""
    for _ in range(3):
        post_id = storage.save_post(content="Test", platform="linkedin", content_mode="build_diary")
        storage.record_project_feature("project-a", "build_diary", post_id)

    weights = storage.get_project_rotation_weights(["project-a", "project-b"])
    assert weights["project-a"] < 0.5  # Heavily penalized
    assert weights["project-b"] == 1.0
