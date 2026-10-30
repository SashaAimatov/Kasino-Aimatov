import psycopg2
from psycopg2.extras import RealDictCursor
import random
import time
import math
import config

def get_conn():
    return psycopg2.connect(config.DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            aima_id TEXT UNIQUE,
            balance DOUBLE PRECISION DEFAULT 25000.0,
            collector_level INT DEFAULT 1,
            last_collect BIGINT DEFAULT 0,
            is_banned BOOLEAN DEFAULT FALSE
        );
    """)
    cur.execute("""
        INSERT INTO players (user_id, username, aima_id, balance)
        VALUES (0, 'CASINO_BANK', 'AIMA-0000-0000-0000-0000', 1000000000.0)
        ON CONFLICT (user_id) DO NOTHING;
    """)
    conn.commit()
    cur.close()
    conn.close()

def generate_aima_id():
    parts = [f"{random.randint(1000, 9999)}" for _ in range(4)]
    return "AIMA-" + "-".join(parts)

def get_or_create_player(user_id: int, username: str = "Player"):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE user_id = %s", (user_id,))
    player = cur.fetchone()
    
    if not player:
        aima_id = generate_aima_id()
        now = int(time.time())
        cur.execute("""
            INSERT INTO players (user_id, username, aima_id, balance, collector_level, last_collect)
            VALUES (%s, %s, %s, 25000.0, 1, %s)
            RETURNING *;
        """, (user_id, username, aima_id, now))
        player = cur.fetchone()
        conn.commit()
        
    cur.close()
    conn.close()
    return player

def get_casino_bank() -> float:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM players WHERE user_id = 0")
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["balance"] if row else 1000000000.0

def set_casino_bank(amount: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE players SET balance = %s WHERE user_id = 0", (amount,))
    conn.commit()
    cur.close()
    conn.close()

def update_balance_by_target(target: str, amount: float, mode: str = "give") -> bool:
    conn = get_conn()
    cur = conn.cursor()
    if target.startswith("AIMA-"):
        op = "balance + %s" if mode == "give" else "%s"
        cur.execute(f"UPDATE players SET balance = {op} WHERE aima_id = %s RETURNING user_id", (amount, target))
    else:
        op = "balance + %s" if mode == "give" else "%s"
        cur.execute(f"UPDATE players SET balance = {op} WHERE user_id = %s RETURNING user_id", (amount, int(target)))
    updated = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return bool(updated)

def set_ban_status(target: str, is_banned: bool) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    if target.startswith("AIMA-"):
        cur.execute("UPDATE players SET is_banned = %s WHERE aima_id = %s RETURNING user_id", (is_banned, target))
    else:
        cur.execute("UPDATE players SET is_banned = %s WHERE user_id = %s RETURNING user_id", (is_banned, int(target)))
    updated = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return bool(updated)
