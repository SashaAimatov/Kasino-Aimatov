import psycopg2
from psycopg2.extras import RealDictCursor
import random
import time
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
            balance DOUBLE PRECISION DEFAULT 10000.0,
            collector_level INT DEFAULT 1,
            last_collect BIGINT DEFAULT 0,
            is_banned BOOLEAN DEFAULT FALSE
        );
    """)
    # Создаем банк казино с фиксированным ID = 0
    cur.execute("""
        INSERT INTO players (user_id, username, aima_id, balance)
        VALUES (0, 'CASINO_BANK', 'AIMA-0000-0000-0000-0000', 1000000000.0)
        ON CONFLICT (user_id) DO NOTHING;
    """)
    # Жестко исправляем аномальные миллиарды у обычных игроков, если они случайно записались
    cur.execute("UPDATE players SET balance = 500000.0 WHERE balance > 50000000 AND user_id != 0;")
    conn.commit()
    cur.close()
    conn.close()

def generate_aima_id(user_id: int) -> str:
    parts = [f"{random.randint(1000, 9999)}" for _ in range(4)]
    return "AIMA-" + "-".join(parts)

def get_or_create_player(user_id: int, username: str = "Player"):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE user_id = %s", (user_id,))
    player = cur.fetchone()
    
    if not player:
        aima_id = generate_aima_id(user_id)
        now = int(time.time())
        cur.execute("""
            INSERT INTO players (user_id, username, aima_id, balance, collector_level, last_collect)
            VALUES (%s, %s, %s, 500000.0, 1, %s)
            RETURNING *;
        """, (user_id, username, aima_id, now))
        player = cur.fetchone()
        conn.commit()
    
    # Защитное ограничение: если баланс игрока стал больше 50 млн, срезаем до нормы
    if player["balance"] > 50000000 and user_id != 0:
        cur.execute("UPDATE players SET balance = 500000.0 WHERE user_id = %s RETURNING *;", (user_id,))
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
    return float(row["balance"]) if row else 1000000000.0

def set_casino_bank(amount: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE players SET balance = %s WHERE user_id = 0", (float(amount),))
    conn.commit()
    cur.close()
    conn.close()

def sync_player_delta(user_id: int, balance_delta: float, bank_delta: float):
    conn = get_conn()
    cur = conn.cursor()
    # Обновляем баланс игрока с защитой от ухода в минус и от превышения 50 млн
    cur.execute("""
        UPDATE players 
        SET balance = LEAST(50000000.0, GREATEST(0.0, balance + %s))
        WHERE user_id = %s RETURNING balance;
    """, (float(balance_delta), user_id))
    res = cur.fetchone()
    
    cur.execute("UPDATE players SET balance = GREATEST(100000.0, balance + %s) WHERE user_id = 0", (float(bank_delta),))
    conn.commit()
    cur.close()
    conn.close()
    return res

def get_forbes_list(limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT username, aima_id, balance 
        FROM players 
        WHERE user_id != 0 AND is_banned = FALSE
        ORDER BY balance DESC 
        LIMIT %s;
    """, (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def update_balance_by_target(target: str, amount: float, mode: str = "give") -> bool:
    conn = get_conn()
    cur = conn.cursor()
    amt = float(amount)
    if target.startswith("AIMA-"):
        op = "LEAST(50000000.0, GREATEST(0.0, balance + %s))" if mode == "give" else "LEAST(50000000.0, %s)"
        cur.execute(f"UPDATE players SET balance = {op} WHERE aima_id = %s RETURNING user_id", (amt, target))
    else:
        op = "LEAST(50000000.0, GREATEST(0.0, balance + %s))" if mode == "give" else "LEAST(50000000.0, %s)"
        cur.execute(f"UPDATE players SET balance = {op} WHERE user_id = %s RETURNING user_id", (amt, int(target)))
    updated = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return bool(updated)
