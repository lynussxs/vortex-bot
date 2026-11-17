"""A single asynchronous SQLite connection with safe schema migrations."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Sequence

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    moderation_log_channel_id INTEGER,
    message_log_channel_id INTEGER,
    suggestion_channel_id INTEGER,
    message_activity_enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS moderation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    duration_seconds INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_moderation_guild_target
    ON moderation_logs(guild_id, target_id, created_at DESC);
CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id, active);
CREATE TABLE IF NOT EXISTS automod_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    spam_limit INTEGER NOT NULL DEFAULT 6,
    spam_window INTEGER NOT NULL DEFAULT 8,
    mention_limit INTEGER NOT NULL DEFAULT 6,
    punish_after INTEGER NOT NULL DEFAULT 3,
    timeout_seconds INTEGER NOT NULL DEFAULT 300,
    raid_limit INTEGER NOT NULL DEFAULT 8,
    raid_window INTEGER NOT NULL DEFAULT 15,
    blocked_words TEXT NOT NULL DEFAULT '[]',
    whitelist_roles TEXT NOT NULL DEFAULT '[]',
    whitelist_channels TEXT NOT NULL DEFAULT '[]',
    blacklist_channels TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS user_levels (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    xp INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 0,
    last_xp_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_levels_leaderboard ON user_levels(guild_id, xp DESC);
CREATE TABLE IF NOT EXISTS level_settings (
    guild_id INTEGER PRIMARY KEY,
    multiplier REAL NOT NULL DEFAULT 1.0,
    cooldown_seconds INTEGER NOT NULL DEFAULT 60,
    ignored_channels TEXT NOT NULL DEFAULT '[]',
    announce_channel_id INTEGER
);
CREATE TABLE IF NOT EXISTS level_rewards (
    guild_id INTEGER NOT NULL,
    level INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, level),
    UNIQUE (guild_id, role_id)
);
CREATE TABLE IF NOT EXISTS autoroles (
    guild_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);
CREATE TABLE IF NOT EXISTS reaction_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    style INTEGER NOT NULL DEFAULT 1,
    panel_type TEXT NOT NULL DEFAULT 'button',
    UNIQUE (message_id, role_id)
);
CREATE INDEX IF NOT EXISTS idx_reaction_roles_message ON reaction_roles(message_id);
CREATE TABLE IF NOT EXISTS logging_settings (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    events TEXT NOT NULL DEFAULT '["member","message","role","channel","voice","moderation"]'
);
CREATE TABLE IF NOT EXISTS welcome_settings (
    guild_id INTEGER PRIMARY KEY,
    welcome_channel_id INTEGER,
    goodbye_channel_id INTEGER,
    welcome_template TEXT NOT NULL DEFAULT 'Welcome {user} to {server}! You are member #{membercount}.',
    goodbye_template TEXT NOT NULL DEFAULT '{username} has left {server}.',
    welcome_enabled INTEGER NOT NULL DEFAULT 0,
    goodbye_enabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ticket_settings (
    guild_id INTEGER PRIMARY KEY,
    panel_channel_id INTEGER,
    panel_message_id INTEGER,
    category_id INTEGER,
    staff_role_id INTEGER
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL UNIQUE,
    opener_id INTEGER NOT NULL,
    claimed_by INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_active_opener
    ON tickets(guild_id, opener_id) WHERE status = 'open';
CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL UNIQUE,
    prize TEXT NOT NULL,
    winner_count INTEGER NOT NULL,
    ends_at TEXT NOT NULL,
    ended INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS giveaway_entries (
    giveaway_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    entered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (giveaway_id, user_id),
    FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS giveaway_winners (
    giveaway_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    draw_number INTEGER NOT NULL DEFAULT 1,
    drawn_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (giveaway_id, user_id, draw_number),
    FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL UNIQUE,
    author_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS suggestion_votes (
    suggestion_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    vote INTEGER NOT NULL CHECK (vote IN (-1, 1)),
    PRIMARY KEY (suggestion_id, user_id),
    FOREIGN KEY (suggestion_id) REFERENCES suggestions(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS custom_ai_prompts (
    guild_id INTEGER PRIMARY KEY,
    prompt TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ai_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ai_history
    ON ai_conversations(guild_id, user_id, channel_id, id DESC);
CREATE TABLE IF NOT EXISTS server_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    category TEXT NOT NULL DEFAULT 'faq',
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'admin',
    channel_id INTEGER,
    approved INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_knowledge_guild ON server_knowledge(guild_id, approved, category);
CREATE TABLE IF NOT EXISTS ai_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS custom_embeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    color INTEGER NOT NULL DEFAULT 5793266,
    author TEXT,
    footer TEXT,
    thumbnail_url TEXT,
    image_url TEXT,
    fields TEXT NOT NULL DEFAULT '[]',
    timestamp INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, owner_id, name)
);
CREATE TABLE IF NOT EXISTS analytics_daily (
    guild_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    messages INTEGER NOT NULL DEFAULT 0,
    joins INTEGER NOT NULL DEFAULT 0,
    leaves INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, day)
);
"""


class Database:
    """Owns one SQLite connection and serializes access to it."""

    def __init__(
        self,
        path: Path | str,
        fallback_path: Path | str | None = None,
        runtime_environment: str = "local",
    ) -> None:
        self.path = Path(path)
        self.fallback_path = Path(fallback_path) if fallback_path else None
        self.runtime_environment = runtime_environment
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._connection is not None

    async def initialize(self) -> None:
        if self._connection is not None:
            return
        connection = await self._open_connection()
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute("PRAGMA journal_mode = WAL")
        await connection.execute("PRAGMA busy_timeout = 10000")
        await connection.executescript(SCHEMA)
        current_version_cursor = await connection.execute("PRAGMA user_version")
        current_version_row = await current_version_cursor.fetchone()
        current_version = int(current_version_row[0]) if current_version_row else 0
        await current_version_cursor.close()
        if current_version < 2:
            await self._ensure_column(connection, "reaction_roles", "panel_type", "TEXT NOT NULL DEFAULT 'button'")
            await self._ensure_column(connection, "custom_embeds", "timestamp", "INTEGER NOT NULL DEFAULT 1")
            await connection.execute(
                """CREATE TABLE IF NOT EXISTS giveaway_winners (
                    giveaway_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    draw_number INTEGER NOT NULL DEFAULT 1,
                    drawn_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (giveaway_id, user_id, draw_number),
                    FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
                )"""
            )
        await connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        await connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        await connection.commit()
        self._connection = connection

    async def _open_connection(self) -> aiosqlite.Connection:
        """Open the primary database, falling back to ``fallback_path`` if it fails."""
        candidates = [self.path]
        if self.fallback_path and self.fallback_path != self.path:
            candidates.append(self.fallback_path)
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                connection = await aiosqlite.connect(candidate, timeout=10)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("Could not open database at %s: %s", candidate, exc)
                continue
            if candidate != self.path:
                logger.warning("Using fallback database at %s", candidate)
                self.path = candidate
            return connection
        assert last_error is not None
        raise last_error

    @staticmethod
    async def _ensure_column(
        connection: aiosqlite.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        cursor = await connection.execute(f"PRAGMA table_info({table})")
        columns = {str(row[1]) for row in await cursor.fetchall()}
        await cursor.close()
        if column not in columns:
            await connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    def _require_connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Database has not been initialized.")
        return self._connection

    async def execute(self, sql: str, parameters: Sequence[Any] = ()) -> int:
        connection = self._require_connection()
        async with self._lock:
            cursor = await connection.execute(sql, parameters)
            await connection.commit()
            lastrowid = cursor.lastrowid
            await cursor.close()
            return int(lastrowid or 0)

    async def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        connection = self._require_connection()
        async with self._lock:
            await connection.executemany(sql, rows)
            await connection.commit()

    async def fetchone(self, sql: str, parameters: Sequence[Any] = ()) -> aiosqlite.Row | None:
        connection = self._require_connection()
        async with self._lock:
            cursor = await connection.execute(sql, parameters)
            row = await cursor.fetchone()
            await cursor.close()
            return row

    async def fetchall(self, sql: str, parameters: Sequence[Any] = ()) -> list[aiosqlite.Row]:
        connection = self._require_connection()
        async with self._lock:
            cursor = await connection.execute(sql, parameters)
            rows = await cursor.fetchall()
            await cursor.close()
            return rows

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = self._require_connection()
        async with self._lock:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                await connection.rollback()
                raise
            else:
                await connection.commit()
