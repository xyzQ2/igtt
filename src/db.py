"""Schema and every SQL statement in the project."""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY,
    username        TEXT NOT NULL,
    platform        TEXT NOT NULL DEFAULT 'instagram',
    category        TEXT,
    followers       INTEGER,
    relevance_score REAL,
    active          INTEGER NOT NULL DEFAULT 1,
    last_checked    TEXT,
    added_at        TEXT NOT NULL,
    notes           TEXT,
    UNIQUE (username, platform)
);

CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY,
    platform      TEXT NOT NULL DEFAULT 'instagram',
    shortcode     TEXT NOT NULL UNIQUE,
    account_id    INTEGER REFERENCES accounts(id),
    url           TEXT,
    video_url     TEXT,
    thumbnail_url TEXT,
    caption       TEXT,
    content_type  TEXT,
    posted_at     TEXT,
    duration_sec  REAL,
    is_ours       INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS post_snapshots (
    id          INTEGER PRIMARY KEY,
    post_id     INTEGER NOT NULL REFERENCES posts(id),
    captured_at TEXT NOT NULL,
    views       INTEGER,
    likes       INTEGER,
    comments    INTEGER,
    shares      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snapshots_post ON post_snapshots(post_id, captured_at);

CREATE TABLE IF NOT EXISTS analyses (
    id                INTEGER PRIMARY KEY,
    post_id           INTEGER NOT NULL REFERENCES posts(id),
    tier              TEXT NOT NULL,
    json              TEXT NOT NULL,
    ai_virality_score REAL,
    model             TEXT,
    created_at        TEXT NOT NULL,
    UNIQUE (post_id, tier)
);

CREATE TABLE IF NOT EXISTS patterns (
    id               INTEGER PRIMARY KEY,
    pattern          TEXT NOT NULL UNIQUE,
    description      TEXT,
    first_seen       TEXT,
    last_seen        TEXT,
    occurrences_7d   INTEGER DEFAULT 0,
    occurrences_30d  INTEGER DEFAULT 0,
    occurrences_90d  INTEGER DEFAULT 0,
    avg_performance  REAL,
    trend_direction  TEXT,
    dtw_relevance    REAL
);

CREATE TABLE IF NOT EXISTS ideas (
    id                INTEGER PRIMARY KEY,
    created_at        TEXT NOT NULL,
    brief_json        TEXT NOT NULL,
    source_pattern_id INTEGER REFERENCES patterns(id),
    similarity_risk   TEXT,
    confidence        REAL,
    status            TEXT NOT NULL DEFAULT 'new',
    posted_shortcode  TEXT,
    posted_ref        TEXT,
    posted_at         TEXT
);

CREATE TABLE IF NOT EXISTS repost_candidates (
    id                 INTEGER PRIMARY KEY,
    post_id            INTEGER NOT NULL REFERENCES posts(id),
    permission_granted INTEGER NOT NULL DEFAULT 0,
    credit_handle      TEXT,
    requested_at       TEXT,
    granted_at         TEXT,
    status             TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS runs (
    id      INTEGER PRIMARY KEY,
    ran_at  TEXT NOT NULL,
    ok      INTEGER NOT NULL,
    stats   TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str = "data/intelligence.db") -> sqlite3.Connection:
    """Open the database, creating the parent directory if needed."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_account(conn, username, platform="instagram", category=None,
                   followers=None, relevance_score=None, active=None) -> int:
    """Insert or update an account. Returns its id."""
    insert_active = 1 if active is None else active
    conn.execute(
        """
        INSERT INTO accounts (username, platform, category, followers,
                              relevance_score, active, added_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username, platform) DO UPDATE SET
            category        = COALESCE(excluded.category, accounts.category),
            followers       = COALESCE(excluded.followers, accounts.followers),
            relevance_score = COALESCE(excluded.relevance_score, accounts.relevance_score),
            active          = COALESCE(?, accounts.active)
        """,
        (username, platform, category, followers, relevance_score, insert_active,
         _now(), active),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM accounts WHERE username = ? AND platform = ?",
        (username, platform),
    ).fetchone()
    return row["id"]


def get_active_accounts(conn) -> list:
    return conn.execute(
        "SELECT * FROM accounts WHERE active = 1 ORDER BY id"
    ).fetchall()


def set_account_score(conn, account_id: int, relevance_score: float, active: int) -> None:
    conn.execute(
        "UPDATE accounts SET relevance_score = ?, active = ?, last_checked = ? WHERE id = ?",
        (relevance_score, active, _now(), account_id),
    )
    conn.commit()


def upsert_post(conn, post: dict) -> int:
    """Insert or update a post keyed on shortcode. Returns its id."""
    conn.execute(
        """
        INSERT INTO posts (platform, shortcode, account_id, url, video_url,
                           thumbnail_url, caption, content_type, posted_at,
                           duration_sec, is_ours, first_seen_at)
        VALUES (:platform, :shortcode, :account_id, :url, :video_url,
                :thumbnail_url, :caption, :content_type, :posted_at,
                :duration_sec, :is_ours, :first_seen_at)
        ON CONFLICT(shortcode) DO UPDATE SET
            caption       = excluded.caption,
            video_url     = COALESCE(excluded.video_url, posts.video_url),
            thumbnail_url = COALESCE(excluded.thumbnail_url, posts.thumbnail_url),
            content_type  = excluded.content_type,
            duration_sec  = COALESCE(excluded.duration_sec, posts.duration_sec)
        """,
        {**{"is_ours": 0, "account_id": None, "url": None, "video_url": None,
            "thumbnail_url": None, "caption": None, "content_type": None,
            "posted_at": None, "duration_sec": None, "platform": "instagram"},
         **post, "first_seen_at": _now()},
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM posts WHERE shortcode = ?", (post["shortcode"],)
    ).fetchone()
    return row["id"]


def add_snapshot(conn, post_id, views, likes, comments, shares, captured_at=None) -> None:
    """Append a metrics snapshot. Never overwrites an earlier one."""
    conn.execute(
        """
        INSERT INTO post_snapshots (post_id, captured_at, views, likes, comments, shares)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (post_id, captured_at or _now(), views, likes, comments, shares),
    )
    conn.commit()


def get_snapshots(conn, post_id: int) -> list:
    return conn.execute(
        "SELECT * FROM post_snapshots WHERE post_id = ? ORDER BY captured_at ASC",
        (post_id,),
    ).fetchall()


def save_analysis(conn, post_id: int, tier: str, payload: dict,
                  ai_virality_score, model: str) -> int:
    """Store one AI analysis. One row per (post, tier); re-running replaces it."""
    import json as _json
    conn.execute(
        """
        INSERT INTO analyses (post_id, tier, json, ai_virality_score, model, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(post_id, tier) DO UPDATE SET
            json = excluded.json,
            ai_virality_score = excluded.ai_virality_score,
            model = excluded.model,
            created_at = excluded.created_at
        """,
        (post_id, tier, _json.dumps(payload), ai_virality_score, model, _now()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM analyses WHERE post_id = ? AND tier = ?", (post_id, tier)
    ).fetchone()
    return row["id"]


def get_analyses_since(conn, days: int) -> list:
    """Analyses for posts published within the last N days."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return conn.execute(
        """
        SELECT a.*, p.shortcode, p.posted_at, p.url, p.caption
        FROM analyses a
        JOIN posts p ON p.id = a.post_id
        WHERE p.posted_at >= ?
        ORDER BY p.posted_at DESC
        """,
        (cutoff,),
    ).fetchall()


def save_pattern(conn, pattern: dict) -> int:
    """Upsert a pattern keyed on its name."""
    conn.execute(
        """
        INSERT INTO patterns (pattern, description, first_seen, last_seen,
                              occurrences_7d, occurrences_30d, occurrences_90d,
                              avg_performance, trend_direction, dtw_relevance)
        VALUES (:pattern, :description, :now, :now, :occurrences_7d,
                :occurrences_30d, :occurrences_90d, :avg_performance,
                :trend_direction, :dtw_relevance)
        ON CONFLICT(pattern) DO UPDATE SET
            description     = excluded.description,
            last_seen       = excluded.last_seen,
            occurrences_7d  = excluded.occurrences_7d,
            occurrences_30d = excluded.occurrences_30d,
            occurrences_90d = excluded.occurrences_90d,
            avg_performance = excluded.avg_performance,
            trend_direction = excluded.trend_direction,
            dtw_relevance   = excluded.dtw_relevance
        """,
        {**{"description": None, "occurrences_7d": 0, "occurrences_30d": 0,
            "occurrences_90d": 0, "avg_performance": None,
            "trend_direction": None, "dtw_relevance": None},
         **pattern, "now": _now()},
    )
    conn.commit()
    row = conn.execute("SELECT id FROM patterns WHERE pattern = ?",
                       (pattern["pattern"],)).fetchone()
    return row["id"]


def get_patterns(conn, limit: int = 20) -> list:
    return conn.execute(
        "SELECT * FROM patterns ORDER BY occurrences_7d DESC, dtw_relevance DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_idea(conn, brief: dict, source_pattern_id, similarity_risk: str,
              confidence) -> int:
    import json as _json
    cur = conn.execute(
        """
        INSERT INTO ideas (created_at, brief_json, source_pattern_id,
                           similarity_risk, confidence, status)
        VALUES (?, ?, ?, ?, ?, 'new')
        """,
        (_now(), _json.dumps(brief), source_pattern_id, similarity_risk, confidence),
    )
    conn.commit()
    return cur.lastrowid


def get_recent_ideas(conn, limit: int = 20) -> list:
    return conn.execute(
        "SELECT * FROM ideas ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def get_idea(conn, idea_id: int):
    return conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()


def link_idea(conn, idea_id, shortcode: str) -> None:
    """Record that an idea was posted as our post `shortcode` (idea_id None
    unlinks it). The operator posts from their phone and says which idea it came
    from; nothing guesses."""
    if idea_id is not None and conn.execute(
            "SELECT 1 FROM ideas WHERE id = ?", (idea_id,)).fetchone() is None:
        raise ValueError(f"no idea #{idea_id}")
    conn.execute("UPDATE ideas SET posted_shortcode = NULL, status = 'new', posted_at = NULL "
                 "WHERE posted_shortcode = ?", (shortcode,))
    if idea_id is None:
        conn.commit()
        return
    conn.execute(
        "UPDATE ideas SET status = 'posted', posted_shortcode = ?, posted_at = ? WHERE id = ?",
        (shortcode, _now(), idea_id),
    )
    conn.commit()


def record_run(conn, stats: dict, ok: bool) -> None:
    import json as _json
    conn.execute("INSERT INTO runs (ran_at, ok, stats) VALUES (?, ?, ?)",
                 (_now(), 1 if ok else 0, _json.dumps(stats)))
    conn.commit()


def last_run(conn):
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()


def set_watchlist(conn, usernames: list, own: str) -> None:
    """Make exactly `usernames` (plus our own account) the active set."""
    keep = {u.strip().lstrip("@").lower() for u in usernames if u.strip()} | {own}
    for row in conn.execute("SELECT id, username FROM accounts").fetchall():
        if row["username"] not in keep:
            conn.execute("UPDATE accounts SET active = 0 WHERE id = ?", (row["id"],))
    conn.commit()
    for u in keep:
        upsert_account(conn, u, active=1)


def posts_since(conn, days: int) -> list:
    """Posts published in the last N days, with account username and followers."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return conn.execute(
        """
        SELECT p.*, a.username, a.followers AS owner_followers
        FROM posts p JOIN accounts a ON a.id = p.account_id
        WHERE p.posted_at >= ?
        ORDER BY p.posted_at DESC
        """,
        (cutoff,),
    ).fetchall()


def analyses_by_post(conn) -> dict:
    """{post_id: text analysis dict} for every analysed post."""
    import json as _json
    return {r["post_id"]: _json.loads(r["json"]) for r in conn.execute(
        "SELECT post_id, json FROM analyses WHERE tier = 'text'")}


def latest_metrics(conn, post_id: int) -> dict:
    """Most recent snapshot for a post, or all-None if it has never been measured."""
    row = conn.execute(
        """
        SELECT views, likes, comments, shares FROM post_snapshots
        WHERE post_id = ? ORDER BY captured_at DESC LIMIT 1
        """,
        (post_id,),
    ).fetchone()
    if row is None:
        return {"views": None, "likes": None, "comments": None, "shares": None}
    return dict(row)


def get_our_posts(conn, days: int = 30) -> list:
    """Our own published posts within the window."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return conn.execute(
        "SELECT * FROM posts WHERE is_ours = 1 AND posted_at >= ? ORDER BY posted_at DESC",
        (cutoff,),
    ).fetchall()


def account_baseline(conn, account_id: int, days: int = 30, exclude_post_id=None):
    """Median views for an account's recent posts. None below three measured posts.

    Median rather than mean: one viral post would otherwise raise the bar so far
    that every normal post looks like a failure. exclude_post_id keeps the post
    being evaluated out of its own baseline.
    """
    from datetime import timedelta
    from statistics import median
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        SELECT MAX(s.views) AS views
        FROM posts p
        JOIN post_snapshots s ON s.post_id = p.id
        WHERE p.account_id = ? AND p.posted_at >= ? AND s.views IS NOT NULL
          AND (? IS NULL OR p.id != ?)
        GROUP BY p.id
        """,
        (account_id, cutoff, exclude_post_id, exclude_post_id),
    ).fetchall()
    values = [r["views"] for r in rows if r["views"] is not None]
    if len(values) < 3:
        return None
    return float(median(values))


def get_account(conn, account_id: int):
    return conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
