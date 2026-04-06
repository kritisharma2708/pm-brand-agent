"""SQLite storage for posts, trends, and learning insights."""

import sqlite3
from datetime import datetime
from typing import Optional

import config


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY,
            content TEXT NOT NULL,
            platform TEXT NOT NULL CHECK (platform IN ('linkedin', 'twitter')),
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'published', 'rejected')),
            content_mode TEXT,
            trend_id INTEGER REFERENCES trends(id),
            project_name TEXT,
            reviewer_score INTEGER,
            reviewer_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            published_at TIMESTAMP,
            engagement_likes INTEGER DEFAULT 0,
            engagement_shares INTEGER DEFAULT 0,
            engagement_comments INTEGER DEFAULT 0,
            scheduled_date TEXT
        );

        CREATE TABLE IF NOT EXISTS trends (
            id INTEGER PRIMARY KEY,
            topic TEXT NOT NULL,
            source TEXT NOT NULL,
            relevance_score INTEGER,
            matched_project TEXT,
            angle TEXT,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            used BOOLEAN DEFAULT FALSE
        );

        CREATE TABLE IF NOT EXISTS learning_insights (
            id INTEGER PRIMARY KEY,
            analysis_date DATE NOT NULL,
            posts_analyzed INTEGER,
            top_format TEXT,
            top_topic TEXT,
            top_tone TEXT,
            best_time_linkedin TEXT,
            best_time_twitter TEXT,
            raw_insight TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS project_features (
            id INTEGER PRIMARY KEY,
            project_name TEXT NOT NULL,
            featured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            content_mode TEXT,
            post_id INTEGER REFERENCES posts(id)
        );
    """)
    # Migration: add scheduled_date to existing DBs
    try:
        conn.execute("ALTER TABLE posts ADD COLUMN scheduled_date TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.commit()
    conn.close()


def save_post(
    content: str,
    platform: str,
    content_mode: str,
    project_name: Optional[str] = None,
    reviewer_score: Optional[int] = None,
    reviewer_notes: Optional[str] = None,
    trend_id: Optional[int] = None,
    scheduled_date: Optional[str] = None,
) -> int:
    """Save a draft post. Returns the post ID."""
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO posts (content, platform, content_mode, project_name,
           reviewer_score, reviewer_notes, trend_id, scheduled_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (content, platform, content_mode, project_name,
         reviewer_score, reviewer_notes, trend_id, scheduled_date),
    )
    post_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return post_id


def score_post(post_id: int, likes: int, comments: int, shares: int):
    """Record engagement metrics for a published post."""
    conn = get_connection()
    conn.execute(
        """UPDATE posts SET status='published', published_at=?,
           engagement_likes=?, engagement_comments=?, engagement_shares=?
           WHERE id=?""",
        (datetime.now().isoformat(), likes, comments, shares, post_id),
    )
    conn.commit()
    conn.close()


def get_recent_posts(days: int = 30) -> list[dict]:
    """Get posts from the last N days with engagement data."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM posts
           WHERE created_at >= datetime('now', ?)
           ORDER BY created_at DESC""",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_post_by_id(post_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_learning_insight(
    posts_analyzed: int,
    top_format: str,
    top_topic: str,
    top_tone: str,
    best_time_linkedin: str,
    best_time_twitter: str,
    raw_insight: str,
) -> int:
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO learning_insights
           (analysis_date, posts_analyzed, top_format, top_topic, top_tone,
            best_time_linkedin, best_time_twitter, raw_insight)
           VALUES (date('now'), ?, ?, ?, ?, ?, ?, ?)""",
        (posts_analyzed, top_format, top_topic, top_tone,
         best_time_linkedin, best_time_twitter, raw_insight),
    )
    insight_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return insight_id


def get_latest_insight() -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM learning_insights ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def record_project_feature(project_name: str, content_mode: str, post_id: int):
    """Record that a project was featured in a post."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO project_features (project_name, content_mode, post_id)
           VALUES (?, ?, ?)""",
        (project_name, content_mode, post_id),
    )
    conn.commit()
    conn.close()


def get_project_rotation_weights(project_names: list[str], days: int = 90) -> dict[str, float]:
    """Return a weight (0.0-1.0) per project for rotation.

    Projects featured recently/frequently get lower weights.
    Projects never featured get 1.0.
    """
    if not project_names:
        return {}

    conn = get_connection()
    rows = conn.execute(
        """SELECT project_name, featured_at FROM project_features
           WHERE featured_at >= datetime('now', ?)
           ORDER BY featured_at DESC""",
        (f"-{days} days",),
    ).fetchall()
    conn.close()

    weights = {name: 1.0 for name in project_names}

    for row in rows:
        name = row["project_name"]
        if name not in weights:
            continue
        # Calculate days since featured
        from datetime import datetime
        featured_at = datetime.fromisoformat(row["featured_at"])
        days_since = (datetime.now() - featured_at).days
        # Penalty decreases with age: 0.3 if today, ~0 if 90 days ago
        penalty = 0.3 * max(0, 1 - days_since / days)
        weights[name] = max(0.0, weights[name] - penalty)

    return weights
