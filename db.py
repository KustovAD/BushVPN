import os
import sqlite3
import threading
import time
import math

from servers import SERVERS

_web_id_lock = threading.Lock()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "users.db")

USER_COLUMNS = {
    "created_at": "INTEGER",
    "trial_used": "INTEGER DEFAULT 0",
    "paid_until": "INTEGER",
    "bonus_used": "INTEGER DEFAULT 0",
    "notified": "INTEGER DEFAULT 0",
    "referrer_id": "INTEGER",
    "ref_bonus_used": "INTEGER DEFAULT 0",
    "ref_days": "INTEGER DEFAULT 0",
    "server": "TEXT",
    "source": "TEXT",
        "username": "TEXT",
        "password_hash": "TEXT",
        "web_username": "TEXT",
        "last_server_change": "INTEGER",
        "active": "INTEGER DEFAULT 1",
    }


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _table_columns(cur, table):
    cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            uuid TEXT NOT NULL,
            expires_at REAL,
            active INTEGER DEFAULT 1
        )
        """
    )

    existing = _table_columns(cur, "users")
    for name, ddl in USER_COLUMNS.items():
        if name not in existing:
            cur.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS dirty_servers (
            server TEXT PRIMARY KEY,
            generation INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER
        )
        """
    )

    cur.execute("PRAGMA table_info(dirty_servers)")
    dirty_info = cur.fetchall()
    dirty_has_pk = any(col[5] for col in dirty_info)
    if not dirty_has_pk:
        cur.execute(
            """
            CREATE TABLE dirty_servers_new (
                server TEXT PRIMARY KEY,
                generation INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER
            )
            """
        )
        cur.execute(
            """
            INSERT OR IGNORE INTO dirty_servers_new(server, updated_at)
            SELECT server, updated_at FROM dirty_servers
            """
        )
        cur.execute("DROP TABLE dirty_servers")
        cur.execute("ALTER TABLE dirty_servers_new RENAME TO dirty_servers")

    dirty_cols = _table_columns(cur, "dirty_servers")
    if "generation" not in dirty_cols:
        cur.execute(
            "ALTER TABLE dirty_servers ADD COLUMN generation INTEGER NOT NULL DEFAULT 0"
        )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_state (
            server TEXT PRIMARY KEY,
            users_hash TEXT,
            synced_at INTEGER
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_invoices (
            invoice_id TEXT PRIMARY KEY,
            processed_at INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_sbp (
            transaction_id TEXT PRIMARY KEY,
            telegram_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            created_at INTEGER
        )
        """
    )

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_server_expires ON users(server, expires_at)"
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS link_codes (
            code TEXT PRIMARY KEY,
            telegram_id INTEGER NOT NULL,
            created_at INTEGER,
            expires_at INTEGER
        )
        """
    )
    cur.execute(
        """
        UPDATE users
        SET web_username = username
        WHERE password_hash IS NOT NULL
          AND password_hash != ''
          AND (web_username IS NULL OR web_username = '')
          AND username IS NOT NULL
          AND username != ''
        """
    )
    try:
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_web_username
            ON users(web_username)
            WHERE web_username IS NOT NULL AND web_username != ''
            """
        )
    except sqlite3.Error:
        pass

    conn.commit()
    conn.close()


def update_user_username(tg_id, username):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET username = ? WHERE telegram_id = ?",
        (username, tg_id),
    )
    conn.commit()
    conn.close()


def get_user_time_by_tg_id(tg_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT expires_at FROM users WHERE telegram_id = ?",
        (tg_id,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    expires = row[0] or 0
    seconds_left = expires - int(time.time())
    if seconds_left <= 0:
        return 0
    return math.ceil(seconds_left / 86400)


def add_or_update_user(
    telegram_id: int,
    uuid: str,
    expires_at: int,
    created_at: int | None = None,
    trial_used: int = 0,
    paid_until: int | None = None,
    referrer_id: int | None = None,
    server=None,
    source: str | None = None,
):
    now = int(time.time())
    created_at = created_at or now

    conn = get_conn()
    conn.execute(
        """
        INSERT INTO users (
            telegram_id,
            uuid,
            created_at,
            expires_at,
            trial_used,
            paid_until,
            bonus_used,
            notified,
            referrer_id,
            ref_bonus_used,
            server,
            source
        ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, 0, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            expires_at = CASE
                WHEN excluded.expires_at > users.expires_at
                THEN excluded.expires_at
                ELSE users.expires_at
            END,
            paid_until = COALESCE(excluded.paid_until, users.paid_until),
            referrer_id = COALESCE(users.referrer_id, excluded.referrer_id),
            source = COALESCE(users.source, excluded.source),
            server = COALESCE(users.server, excluded.server)
        """,
        (
            telegram_id,
            uuid,
            created_at,
            expires_at,
            trial_used,
            paid_until,
            referrer_id,
            server,
            source,
        ),
    )
    conn.commit()
    conn.close()


def get_user(telegram_id: int):
    conn = get_conn()
    user = conn.execute(
        "SELECT uuid, expires_at, bonus_used, server FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()
    conn.close()
    return user


def get_user_by_uuid(user_uuid: str):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT telegram_id, uuid, expires_at, server
        FROM users
        WHERE uuid = ?
        """,
        (user_uuid,),
    ).fetchone()
    conn.close()
    return row


def get_user_server_row(telegram_id: int):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT uuid, server, last_server_change
        FROM users
        WHERE telegram_id = ?
        """,
        (telegram_id,),
    ).fetchone()
    conn.close()
    return row


def change_user_server(telegram_id: int, new_uuid: str, new_server: str):
    conn = get_conn()
    conn.execute(
        """
        UPDATE users
        SET uuid = ?, server = ?, last_server_change = ?
        WHERE telegram_id = ?
        """,
        (new_uuid, new_server, int(time.time()), telegram_id),
    )
    conn.commit()
    conn.close()


def get_active_users():
    conn = get_conn()
    now = int(time.time())
    users = [
        row[0]
        for row in conn.execute(
            """
            SELECT uuid FROM users
            WHERE expires_at > ? OR paid_until > ?
            """,
            (now, now),
        ).fetchall()
    ]
    conn.close()
    return users


def get_active_uuids(server_name: str) -> list[str]:
    conn = get_conn()
    now = int(time.time())
    rows = conn.execute(
        """
        SELECT uuid
        FROM users
        WHERE server = ?
          AND expires_at > ?
        ORDER BY uuid
        """,
        (server_name, now),
    ).fetchall()
    conn.close()
    return [row[0] for row in rows]


def add_time(tg_id, days):
    conn = get_conn()
    now = int(time.time())
    seconds = days * 86400

    row = conn.execute(
        "SELECT expires_at FROM users WHERE telegram_id=?",
        (tg_id,),
    ).fetchone()

    if row is None:
        conn.close()
        return False

    old_expires = row[0] or 0
    new_expires = old_expires + seconds if old_expires > now else now + seconds

    conn.execute(
        "UPDATE users SET expires_at=?, notified=0 WHERE telegram_id=?",
        (new_expires, tg_id),
    )
    conn.commit()
    conn.close()
    return True


def set_bonus_used(tg_id):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET bonus_used = 1 WHERE telegram_id = ?",
        (tg_id,),
    )
    conn.commit()
    conn.close()


def add_days_to_user(tg_id, days):
    return add_time(tg_id, days)


def get_users_for_warning():
    now = int(time.time())
    tomorrow = now + 86400

    conn = get_conn()
    rows = conn.execute(
        """
        SELECT telegram_id, expires_at
        FROM users
        WHERE expires_at BETWEEN ? AND ?
          AND notified = 0
        """,
        (now, tomorrow),
    ).fetchall()
    conn.close()
    return rows


def mark_notified(tg_id):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET notified = 1 WHERE telegram_id = ?",
        (tg_id,),
    )
    conn.commit()
    conn.close()


def apply_referral_bonus(new_user_tg_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT referrer_id FROM users WHERE telegram_id = ?",
        (new_user_tg_id,),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        conn.close()
        return False

    referrer_id = int(row[0])

    cur.execute(
        "SELECT ref_bonus_used FROM users WHERE telegram_id = ?",
        (new_user_tg_id,),
    )
    used = cur.fetchone()
    if used and used[0] == 1:
        conn.close()
        return False

    bonus_days = 5
    max_ref_days = 30

    cur.execute(
        "SELECT ref_days FROM users WHERE telegram_id = ?",
        (referrer_id,),
    )
    row = cur.fetchone()
    ref_days = row[0] if row and row[0] else 0
    if ref_days >= max_ref_days:
        conn.close()
        return False

    add_days = min(bonus_days, max_ref_days - ref_days)
    add_seconds = add_days * 86400
    now = int(time.time())

    cur.execute(
        "SELECT expires_at FROM users WHERE telegram_id = ?",
        (referrer_id,),
    )
    row = cur.fetchone()
    current_expires = int(row[0]) if row and row[0] else 0
    new_expires = current_expires + add_seconds if current_expires > now else now + add_seconds

    cur.execute(
        "UPDATE users SET expires_at = ? WHERE telegram_id = ?",
        (new_expires, referrer_id),
    )
    cur.execute(
        "UPDATE users SET ref_days = COALESCE(ref_days, 0) + ? WHERE telegram_id = ?",
        (add_days, referrer_id),
    )
    cur.execute(
        "UPDATE users SET ref_bonus_used = 1 WHERE telegram_id = ?",
        (new_user_tg_id,),
    )

    conn.commit()
    conn.close()
    return add_days


def get_available_server():
    conn = get_conn()
    now = int(time.time())
    for server in SERVERS:
        count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE server = ? AND expires_at > ?",
            (server["name"], now),
        ).fetchone()[0]
        if count < server["limit"]:
            conn.close()
            return server
    conn.close()
    return None


def get_server_users(server_name):
    conn = get_conn()
    now = int(time.time())
    count = conn.execute(
        "SELECT COUNT(*) FROM users WHERE server=? AND expires_at > ?",
        (server_name, now),
    ).fetchone()[0]
    conn.close()
    return count


def mark_server_dirty(server_name):
    if not server_name:
        return
    now = int(time.time())
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO dirty_servers(server, generation, updated_at)
        VALUES (?, 1, ?)
        ON CONFLICT(server) DO UPDATE SET
            generation = dirty_servers.generation + 1,
            updated_at = excluded.updated_at
        """,
        (server_name, now),
    )
    conn.commit()
    conn.close()


def get_dirty_servers():
    conn = get_conn()
    rows = conn.execute(
        "SELECT server, generation FROM dirty_servers"
    ).fetchall()
    conn.close()
    return rows


def clear_dirty(server_name, generation=None):
    conn = get_conn()
    if generation is None:
        conn.execute("DELETE FROM dirty_servers WHERE server=?", (server_name,))
    else:
        conn.execute(
            "DELETE FROM dirty_servers WHERE server=? AND generation=?",
            (server_name, generation),
        )
    conn.commit()
    conn.close()


def get_sync_hash(server_name):
    conn = get_conn()
    row = conn.execute(
        "SELECT users_hash FROM sync_state WHERE server=?",
        (server_name,),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def set_sync_hash(server_name, users_hash):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO sync_state(server, users_hash, synced_at)
        VALUES (?, ?, ?)
        ON CONFLICT(server) DO UPDATE SET
            users_hash = excluded.users_hash,
            synced_at = excluded.synced_at
        """,
        (server_name, users_hash, int(time.time())),
    )
    conn.commit()
    conn.close()


def invoice_already_processed(invoice_id) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM processed_invoices WHERE invoice_id=?",
        (str(invoice_id),),
    ).fetchone()
    conn.close()
    return row is not None


def mark_invoice_processed(invoice_id):
    conn = get_conn()
    conn.execute(
        """
        INSERT OR IGNORE INTO processed_invoices(invoice_id, processed_at)
        VALUES (?, ?)
        """,
        (str(invoice_id), int(time.time())),
    )
    conn.commit()
    conn.close()


def save_pending_sbp(transaction_id, telegram_id, plan):
    conn = get_conn()
    conn.execute(
        """
        INSERT OR REPLACE INTO pending_sbp(transaction_id, telegram_id, plan, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (str(transaction_id), int(telegram_id), str(plan), int(time.time())),
    )
    conn.commit()
    conn.close()


def get_pending_sbp(transaction_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT transaction_id, telegram_id, plan FROM pending_sbp WHERE transaction_id=?",
        (str(transaction_id),),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"transaction_id": row[0], "telegram_id": row[1], "plan": row[2]}


def list_pending_sbp(max_age_seconds=86400):
    conn = get_conn()
    since = int(time.time()) - max_age_seconds
    rows = conn.execute(
        """
        SELECT transaction_id, telegram_id, plan
        FROM pending_sbp
        WHERE created_at >= ?
        ORDER BY created_at DESC
        """,
        (since,),
    ).fetchall()
    conn.close()
    return [
        {"transaction_id": row[0], "telegram_id": row[1], "plan": row[2]}
        for row in rows
    ]


def delete_pending_sbp(transaction_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM pending_sbp WHERE transaction_id=?",
        (str(transaction_id),),
    )
    conn.commit()
    conn.close()


def _user_row_to_profile(row):
    if not row:
        return None
    return {
        "telegram_id": row[0],
        "uuid": row[1],
        "expires_at": row[2] or 0,
        "bonus_used": row[3] or 0,
        "server": row[4],
        "username": row[5],
        "web_username": row[6],
        "last_server_change": row[7],
        "referrer_id": row[8],
        "ref_days": row[9] or 0,
        "source": row[10],
        "has_password": bool(row[11]),
        "linked_telegram": bool(row[0] and row[0] > 0),
    }


_PROFILE_SELECT = """
    SELECT telegram_id, uuid, expires_at, bonus_used, server, username,
           web_username, last_server_change, referrer_id, ref_days, source,
           password_hash
    FROM users
"""


def get_user_profile(telegram_id: int):
    conn = get_conn()
    row = conn.execute(
        _PROFILE_SELECT + " WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()
    conn.close()
    return _user_row_to_profile(row)


def get_user_by_web_username(username: str):
    if not username:
        return None
    conn = get_conn()
    row = conn.execute(
        _PROFILE_SELECT + " WHERE lower(web_username) = lower(?)",
        (username.strip(),),
    ).fetchone()
    conn.close()
    return _user_row_to_profile(row)


def get_password_hash(telegram_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def web_username_taken(username: str, exclude_tg_id=None):
    conn = get_conn()
    if exclude_tg_id is None:
        row = conn.execute(
            "SELECT telegram_id FROM users WHERE lower(web_username) = lower(?)",
            (username,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT telegram_id FROM users
            WHERE lower(web_username) = lower(?) AND telegram_id != ?
            """,
            (username, exclude_tg_id),
        ).fetchone()
    conn.close()
    return row is not None


def allocate_web_id(conn):
    row = conn.execute("SELECT MIN(telegram_id) FROM users").fetchone()
    current_min = row[0] if row and row[0] is not None else 0
    return current_min - 1 if current_min < 0 else -1


def create_web_user(
    web_username: str,
    password_hash: str,
    user_uuid: str,
    expires_at: int,
    server_name: str,
    referrer_id: int | None = None,
):
    now = int(time.time())
    conn = get_conn()
    try:
        with _web_id_lock:
            telegram_id = allocate_web_id(conn)
            conn.execute(
            """
            INSERT INTO users (
                telegram_id, uuid, created_at, expires_at, trial_used,
                bonus_used, notified, referrer_id, ref_bonus_used, server,
                source, web_username, password_hash, active
            ) VALUES (?, ?, ?, ?, 1, 0, 0, ?, 0, ?, 'web', ?, ?, 1)
            """,
            (
                telegram_id,
                user_uuid,
                now,
                expires_at,
                referrer_id,
                server_name,
                web_username,
                password_hash,
            ),
        )
        conn.commit()
        return telegram_id
    finally:
        conn.close()


def set_web_credentials(telegram_id: int, web_username: str, password_hash: str):
    conn = get_conn()
    conn.execute(
        """
        UPDATE users
        SET web_username = ?, password_hash = ?
        WHERE telegram_id = ?
        """,
        (web_username, password_hash, telegram_id),
    )
    conn.commit()
    conn.close()


def bind_web_credentials_by_uuid(user_uuid: str, web_username: str, password_hash: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT telegram_id, web_username, password_hash FROM users WHERE uuid = ?",
        (user_uuid,),
    ).fetchone()
    if not row:
        conn.close()
        return None, "Ключ не найден"
    telegram_id, existing_name, existing_hash = row
    if existing_hash and existing_name:
        conn.close()
        return None, "К этому ключу уже привязан логин. Войдите в аккаунт."
    taken = conn.execute(
        """
        SELECT telegram_id FROM users
        WHERE lower(web_username) = lower(?) AND telegram_id != ?
        """,
        (web_username, telegram_id),
    ).fetchone()
    if taken:
        conn.close()
        return None, "Такой логин уже занят"
    conn.execute(
        """
        UPDATE users
        SET web_username = ?, password_hash = ?
        WHERE telegram_id = ?
        """,
        (web_username, password_hash, telegram_id),
    )
    conn.commit()
    conn.close()
    return telegram_id, None


def create_link_code(telegram_id: int, ttl=900):
    import secrets

    now = int(time.time())
    conn = get_conn()
    conn.execute(
        "DELETE FROM link_codes WHERE telegram_id = ? OR expires_at < ?",
        (telegram_id, now),
    )
    code = f"{secrets.randbelow(900000) + 100000}"
    conn.execute(
        """
        INSERT INTO link_codes(code, telegram_id, created_at, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (code, telegram_id, now, now + ttl),
    )
    conn.commit()
    conn.close()
    return code, now + ttl


def consume_link_code(code: str, tg_id: int, tg_username: str | None = None):
    now = int(time.time())
    code = (code or "").strip()
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT telegram_id, expires_at FROM link_codes WHERE code = ?",
        (code,),
    ).fetchone()
    if not row:
        conn.close()
        return None, "Код не найден или уже использован"
    web_id, expires_at = row
    if expires_at < now:
        cur.execute("DELETE FROM link_codes WHERE code = ?", (code,))
        conn.commit()
        conn.close()
        return None, "Код истёк — получите новый на сайте"

    if web_id == tg_id:
        cur.execute("DELETE FROM link_codes WHERE code = ?", (code,))
        if tg_username:
            cur.execute(
                "UPDATE users SET username = ? WHERE telegram_id = ?",
                (tg_username, tg_id),
            )
        conn.commit()
        conn.close()
        return tg_id, None

    web = cur.execute(
        """
        SELECT uuid, expires_at, bonus_used, server, web_username, password_hash
        FROM users WHERE telegram_id = ?
        """,
        (web_id,),
    ).fetchone()
    if not web:
        cur.execute("DELETE FROM link_codes WHERE code = ?", (code,))
        conn.commit()
        conn.close()
        return None, "Аккаунт сайта не найден"

    tg = cur.execute(
        """
        SELECT uuid, expires_at, bonus_used, server, web_username, password_hash
        FROM users WHERE telegram_id = ?
        """,
        (tg_id,),
    ).fetchone()

    dirty = []
    try:
        if tg is None:
            cur.execute(
                """
                UPDATE users
                SET telegram_id = ?, username = COALESCE(?, username)
                WHERE telegram_id = ?
                """,
                (tg_id, tg_username, web_id),
            )
            dirty.append(web[3])
        else:
            tg_web_name, tg_password = tg[4], tg[5]
            if tg_web_name and tg_password and tg_web_name != web[4]:
                conn.close()
                return None, "Этот Telegram уже привязан к другому логину"
            new_expires = max(int(web[1] or 0), int(tg[1] or 0))
            bonus_used = 1 if (web[2] or tg[2]) else 0
            cur.execute(
                """
                UPDATE users SET
                    web_username = COALESCE(?, web_username),
                    password_hash = COALESCE(?, password_hash),
                    expires_at = ?,
                    bonus_used = ?,
                    username = COALESCE(?, username)
                WHERE telegram_id = ?
                """,
                (web[4], web[5], new_expires, bonus_used, tg_username, tg_id),
            )
            cur.execute("DELETE FROM users WHERE telegram_id = ?", (web_id,))
            dirty.extend([web[3], tg[3]])
        cur.execute("DELETE FROM link_codes WHERE code = ?", (code,))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    for name in dirty:
        mark_server_dirty(name)
    return tg_id, None

