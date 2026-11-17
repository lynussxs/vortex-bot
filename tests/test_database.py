from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.database import Database, SCHEMA_VERSION


class DatabaseTests(unittest.TestCase):
    def test_schema_initializes_and_persists_parameterized_values(self) -> None:
        async def scenario(path: Path) -> None:
            db = Database(path)
            await db.initialize()
            await db.execute(
                "INSERT INTO server_knowledge(guild_id, question, answer) VALUES (?, ?, ?)",
                (12, "question'; DROP TABLE users; --", "safe answer"),
            )
            row = await db.fetchone("SELECT question, answer FROM server_knowledge WHERE guild_id = ?", (12,))
            self.assertEqual(row["question"], "question'; DROP TABLE users; --")
            self.assertEqual(row["answer"], "safe answer")
            version = await db.fetchone("PRAGMA user_version")
            self.assertEqual(int(version[0]), SCHEMA_VERSION)

            with self.assertRaises(RuntimeError):
                async with db.transaction() as connection:
                    await connection.execute(
                        "INSERT INTO server_knowledge(guild_id, question, answer) VALUES (?, ?, ?)",
                        (12, "rolled back", "not saved"),
                    )
                    raise RuntimeError("rollback")
            missing = await db.fetchone(
                "SELECT id FROM server_knowledge WHERE guild_id = ? AND question = ?",
                (12, "rolled back"),
            )
            self.assertIsNone(missing)
            await db.close()

            reopened = Database(path)
            await reopened.initialize()
            persisted = await reopened.fetchone("SELECT answer FROM server_knowledge WHERE guild_id = ?", (12,))
            self.assertEqual(persisted["answer"], "safe answer")
            await reopened.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory) / "bot.db"))

    def test_v1_database_migrates_additive_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE reaction_roles (
                    id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    style INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE custom_embeds (
                    id INTEGER PRIMARY KEY,
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
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, owner_id, name)
                );
                CREATE TABLE giveaways (
                    id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    prize TEXT NOT NULL,
                    winner_count INTEGER NOT NULL,
                    ends_at TEXT NOT NULL,
                    ended INTEGER NOT NULL DEFAULT 0,
                    created_by INTEGER NOT NULL
                );
                PRAGMA user_version = 1;
                """
            )
            connection.close()

            async def migrate() -> None:
                db = Database(path)
                await db.initialize()
                rr_columns = await db.fetchall("PRAGMA table_info(reaction_roles)")
                embed_columns = await db.fetchall("PRAGMA table_info(custom_embeds)")
                rr_names = {row["name"] for row in rr_columns}
                embed_names = {row["name"] for row in embed_columns}
                self.assertIn("panel_type", rr_names)
                self.assertIn("timestamp", embed_names)
                table = await db.fetchone(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'giveaway_winners'"
                )
                self.assertIsNotNone(table)
                await db.close()

            asyncio.run(migrate())
