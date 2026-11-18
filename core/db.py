"""Co so du lieu SQLite (aiosqlite): cau hinh, case xu phat, XP/level, kho kien thuc AI."""
import os
import time

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT,
    PRIMARY KEY (guild_id, key)
);
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    mod_id INTEGER NOT NULL, action TEXT NOT NULL, reason TEXT, created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cases_user ON cases (guild_id, user_id);
CREATE TABLE IF NOT EXISTS levels (
    guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, xp INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS level_roles (
    guild_id INTEGER NOT NULL, level INTEGER NOT NULL, role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, level)
);
CREATE TABLE IF NOT EXISTS kb (
    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL
);
"""


def default_db_path() -> str:
    if os.getenv("DB_PATH"):
        return os.environ["DB_PATH"]
    return "/data/bot.db" if os.path.isdir("/data") else "bot.db"


def xp_for_level(n: int) -> int:
    """XP can de len tu cap n len cap n+1."""
    return 5 * n * n + 50 * n + 100


def level_from_xp(total: int):
    """-> (level, xp_trong_cap_hien_tai, xp_can_de_len_cap_tiep)"""
    level, rest = 0, max(int(total), 0)
    while rest >= xp_for_level(level):
        rest -= xp_for_level(level)
        level += 1
    return level, rest, xp_for_level(level)


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self._cache: dict = {}

    async def connect(self):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()
            self.conn = None

    # ------------------------------------------------------------ settings
    async def get_setting(self, guild_id: int, key: str, default=None):
        k = (guild_id, key)
        if k not in self._cache:
            cur = await self.conn.execute("SELECT value FROM settings WHERE guild_id=? AND key=?", (guild_id, key))
            row = await cur.fetchone()
            self._cache[k] = row["value"] if row else None
        v = self._cache[k]
        return default if v is None else v

    async def get_int(self, guild_id: int, key: str, default=None):
        v = await self.get_setting(guild_id, key)
        try:
            return int(v) if v is not None else default
        except ValueError:
            return default

    async def get_bool(self, guild_id: int, key: str, default: bool = False) -> bool:
        v = await self.get_setting(guild_id, key)
        return default if v is None else v == "1"

    async def set_setting(self, guild_id: int, key: str, value):
        if value is None:
            await self.conn.execute("DELETE FROM settings WHERE guild_id=? AND key=?", (guild_id, key))
            self._cache[(guild_id, key)] = None
        else:
            if isinstance(value, bool):
                value = "1" if value else "0"
            await self.conn.execute(
                "INSERT INTO settings (guild_id, key, value) VALUES (?,?,?) "
                "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
                (guild_id, key, str(value)),
            )
            self._cache[(guild_id, key)] = str(value)
        await self.conn.commit()

    async def all_settings(self, guild_id: int) -> dict:
        cur = await self.conn.execute("SELECT key, value FROM settings WHERE guild_id=?", (guild_id,))
        return {r["key"]: r["value"] for r in await cur.fetchall()}

    # --------------------------------------------------------------- cases
    async def add_case(self, guild_id, user_id, mod_id, action, reason) -> int:
        cur = await self.conn.execute(
            "INSERT INTO cases (guild_id, user_id, mod_id, action, reason, created_at) VALUES (?,?,?,?,?,?)",
            (guild_id, user_id, mod_id, action, reason, int(time.time())),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def user_cases(self, guild_id, user_id, action=None, limit=10):
        sql, args = "SELECT * FROM cases WHERE guild_id=? AND user_id=?", [guild_id, user_id]
        if action:
            sql += " AND action=?"
            args.append(action)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        cur = await self.conn.execute(sql, args)
        return await cur.fetchall()

    async def count_cases(self, guild_id, user_id, action) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS n FROM cases WHERE guild_id=? AND user_id=? AND action=?", (guild_id, user_id, action)
        )
        return (await cur.fetchone())["n"]

    async def clear_cases(self, guild_id, user_id, action) -> int:
        cur = await self.conn.execute(
            "DELETE FROM cases WHERE guild_id=? AND user_id=? AND action=?", (guild_id, user_id, action)
        )
        await self.conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------ xp / level
    async def get_xp(self, guild_id, user_id) -> int:
        cur = await self.conn.execute("SELECT xp FROM levels WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        row = await cur.fetchone()
        return row["xp"] if row else 0

    async def add_xp(self, guild_id, user_id, amount) -> tuple[int, int, int]:
        """Cong XP. Tra ve (level_cu, level_moi, tong_xp)."""
        old = await self.get_xp(guild_id, user_id)
        new = max(old + int(amount), 0)
        await self.conn.execute(
            "INSERT INTO levels (guild_id, user_id, xp) VALUES (?,?,?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET xp=excluded.xp",
            (guild_id, user_id, new),
        )
        await self.conn.commit()
        return level_from_xp(old)[0], level_from_xp(new)[0], new

    async def set_xp(self, guild_id, user_id, xp):
        return await self.add_xp(guild_id, user_id, int(xp) - await self.get_xp(guild_id, user_id))

    async def rank_position(self, guild_id, user_id) -> int:
        xp = await self.get_xp(guild_id, user_id)
        cur = await self.conn.execute("SELECT COUNT(*) AS n FROM levels WHERE guild_id=? AND xp>?", (guild_id, xp))
        return (await cur.fetchone())["n"] + 1

    async def leaderboard(self, guild_id, limit=10, offset=0):
        cur = await self.conn.execute(
            "SELECT user_id, xp FROM levels WHERE guild_id=? ORDER BY xp DESC LIMIT ? OFFSET ?",
            (guild_id, limit, offset),
        )
        return await cur.fetchall()

    async def set_level_role(self, guild_id, level, role_id):
        await self.conn.execute(
            "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?,?,?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id=excluded.role_id",
            (guild_id, level, role_id),
        )
        await self.conn.commit()

    async def remove_level_role(self, guild_id, level) -> bool:
        cur = await self.conn.execute("DELETE FROM level_roles WHERE guild_id=? AND level=?", (guild_id, level))
        await self.conn.commit()
        return cur.rowcount > 0

    async def level_roles(self, guild_id):
        cur = await self.conn.execute(
            "SELECT level, role_id FROM level_roles WHERE guild_id=? ORDER BY level", (guild_id,)
        )
        return [(r["level"], r["role_id"]) for r in await cur.fetchall()]

    # ------------------------------------------------------------- kien thuc AI
    async def kb_add(self, guild_id, title, content) -> int:
        cur = await self.conn.execute(
            "INSERT INTO kb (guild_id, title, content) VALUES (?,?,?)", (guild_id, title, content)
        )
        await self.conn.commit()
        return cur.lastrowid

    async def kb_list(self, guild_id):
        cur = await self.conn.execute("SELECT id, title, content FROM kb WHERE guild_id=? ORDER BY id", (guild_id,))
        return await cur.fetchall()

    async def kb_get(self, guild_id, kb_id):
        cur = await self.conn.execute(
            "SELECT id, title, content FROM kb WHERE guild_id=? AND id=?", (guild_id, kb_id)
        )
        return await cur.fetchone()

    async def kb_remove(self, guild_id, kb_id) -> bool:
        cur = await self.conn.execute("DELETE FROM kb WHERE guild_id=? AND id=?", (guild_id, kb_id))
        await self.conn.commit()
        return cur.rowcount > 0
