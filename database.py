import random
from contextlib import contextmanager

from psycopg2.extras import Json, RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

import config

MAX_BAL = 50_000_000      # потолок баланса игрока
START_BAL = 500_000       # стартовый баланс
MAX_BET = 1_000_000       # максимальная ставка
_pool = None


class GameError(Exception):
    """Ошибка для игрока: показывается в приложении как есть."""


@contextmanager
def tx():
    """Одна транзакция на запрос: либо всё применилось, либо ничего."""
    conn = _pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def init_db():
    global _pool
    _pool = ThreadedConnectionPool(1, 10, config.DATABASE_URL)
    with tx() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS players (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                aima_id TEXT UNIQUE,
                balance BIGINT DEFAULT 500000,
                collector_level INT DEFAULT 1,
                last_collect BIGINT DEFAULT 0,
                is_banned BOOLEAN DEFAULT FALSE
            )""")
        # миграция старой таблицы: деньги теперь целые числа
        cur.execute("ALTER TABLE players ALTER COLUMN balance DROP DEFAULT")
        cur.execute("ALTER TABLE players ALTER COLUMN balance TYPE BIGINT USING ROUND(balance)::BIGINT")
        cur.execute("ALTER TABLE players ALTER COLUMN balance SET DEFAULT 500000")
        cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS last_mint BIGINT DEFAULT 0")
        cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS last_raid BIGINT DEFAULT 0")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                user_id BIGINT PRIMARY KEY,
                game TEXT,
                data JSONB
            )""")
        cur.execute("""
            INSERT INTO players (user_id, username, aima_id, balance)
            VALUES (0, 'CASINO_BANK', 'AIMA-0000-0000-0000-0000', 1000000000)
            ON CONFLICT (user_id) DO NOTHING""")
        cur.execute("UPDATE players SET balance=%s WHERE balance>%s AND user_id<>0", (START_BAL, MAX_BAL))


def get_player(cur, uid, name="", banned_ok=False):
    """Находит игрока (или создаёт) и блокирует его строку до конца транзакции."""
    cur.execute("SELECT * FROM players WHERE user_id=%s FOR UPDATE", (uid,))
    p = cur.fetchone()
    for _ in range(10):
        if p:
            break
        aid = "AIMA-" + "-".join(str(random.randint(1000, 9999)) for _ in range(4))
        cur.execute("""
            INSERT INTO players (user_id, username, aima_id, balance)
            VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING *""",
                    (uid, (name or "Player")[:64], aid, START_BAL))
        p = cur.fetchone()
        if not p:  # коллизия AIMA-ID или параллельное создание
            cur.execute("SELECT * FROM players WHERE user_id=%s FOR UPDATE", (uid,))
            p = cur.fetchone()
    if not p:
        raise GameError("Не удалось создать игрока")
    if p["is_banned"] and not banned_ok:
        raise GameError("Ваш аккаунт заблокирован")
    if name and p["username"] != name[:64]:
        cur.execute("UPDATE players SET username=%s WHERE user_id=%s", (name[:64], uid))
        p["username"] = name[:64]
    return p


def bank(cur, lock=False):
    cur.execute("SELECT balance FROM players WHERE user_id=0" + (" FOR UPDATE" if lock else ""))
    return cur.fetchone()["balance"]


def to_bank(cur, uid, amt):
    """Игрок -> банк казино (ставка). Баланс не может уйти в минус."""
    cur.execute("UPDATE players SET balance=balance-%s WHERE user_id=%s AND balance>=%s RETURNING balance",
                (amt, uid, amt))
    r = cur.fetchone()
    if not r:
        raise GameError("Недостаточно ASG на счете")
    cur.execute("UPDATE players SET balance=balance+%s WHERE user_id=0", (amt,))
    return r["balance"]


def from_bank(cur, uid, amt):
    """Банк казино -> игрок (выигрыш). Выплата не больше 10% банка и потолка баланса."""
    amt = max(0, min(int(amt), bank(cur, lock=True) // 10))
    cur.execute("SELECT balance FROM players WHERE user_id=%s", (uid,))
    amt = max(0, min(amt, MAX_BAL - cur.fetchone()["balance"]))
    cur.execute("UPDATE players SET balance=balance+%s WHERE user_id=%s RETURNING balance", (amt, uid))
    bal = cur.fetchone()["balance"]
    cur.execute("UPDATE players SET balance=balance-%s WHERE user_id=0", (amt,))
    return bal, amt


def sess_load(cur, uid, game):
    cur.execute("SELECT data FROM sessions WHERE user_id=%s AND game=%s FOR UPDATE", (uid, game))
    r = cur.fetchone()
    if not r:
        raise GameError("Игра не начата")
    return r["data"]


def sess_save(cur, uid, game, data):
    cur.execute("""
        INSERT INTO sessions (user_id, game, data) VALUES (%s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET game=EXCLUDED.game, data=EXCLUDED.data""",
                (uid, game, Json(data)))


def sess_end(cur, uid):
    cur.execute("DELETE FROM sessions WHERE user_id=%s", (uid,))


def get_forbes(cur, limit=50):
    cur.execute("""
        SELECT username, aima_id, balance FROM players
        WHERE user_id<>0 AND is_banned=FALSE
        ORDER BY balance DESC LIMIT %s""", (limit,))
    return [{"username": r["username"] or "Игрок", "aima_id": r["aima_id"], "balance": int(r["balance"])}
            for r in cur.fetchall()]


# ---------- команды админа (бот) ----------
def admin_balance(target, amount, mode):
    by_aima = target.startswith("AIMA-")
    val = target if by_aima else int(target)
    expr = "balance+%s" if mode == "give" else "%s"
    with tx() as cur:
        cur.execute(f"UPDATE players SET balance=LEAST(%s, GREATEST(0, {expr})) "
                    f"WHERE {'aima_id' if by_aima else 'user_id'}=%s AND user_id<>0 RETURNING user_id",
                    (MAX_BAL, amount, val))
        return bool(cur.fetchone())


def set_bank(amount):
    with tx() as cur:
        cur.execute("UPDATE players SET balance=%s WHERE user_id=0", (max(0, int(amount)),))
