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
            balance DOUBLE PRECISION DEFAULT 1000.0,
            collector_level INT DEFAULT 1,
            last_collect BIGINT DEFAULT 0,
            is_banned BOOLEAN DEFAULT FALSE
        );
    """)
    # Игрок с user_id = 0 — это Банк Казино
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
            VALUES (%s, %s, %s, 1000.0, 1, %s)
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
    return row["balance"] if row else 1000000.0

def update_casino_bank(delta: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE players SET balance = balance + %s WHERE user_id = 0", (delta,))
    conn.commit()
    cur.close()
    conn.close()

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
    # Поиск либо по AIMA-ID, либо по Telegram ID
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

def adjust_player_balance(user_id: int, delta: float) -> float:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE players 
        SET balance = FLOOR((balance + %s) * 100) / 100 
        WHERE user_id = %s 
        RETURNING balance
    """, (delta, user_id))
    res = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return res["balance"] if res else 0.0

def collect_passive_income(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE user_id = %s", (user_id,))
    p = cur.fetchone()
    if not p:
        cur.close()
        conn.close()
        return None
        
    now = int(time.time())
    elapsed = max(0, now - p["last_collect"])
    # Ограничение накопления: максимум за 12 часов (43200 сек), 2 ASG/сек за уровень
    elapsed = min(elapsed, 43200)
    raw_collected = elapsed * (p["collector_level"] * 2.0)
    
    if raw_collected < 10:
        cur.close()
        conn.close()
        return {"error": "Слишком мало накоплено (минимум 10 ASG)"}
        
    # Налог коллектора 10-30% в пользу казино (округление вверх)
    tax_rate = random.uniform(0.10, 0.30)
    tax = math.ceil(raw_collected * tax_rate)
    net = math.floor(raw_collected - tax)
    
    cur.execute("""
        UPDATE players 
        SET balance = balance + %s, last_collect = %s 
        WHERE user_id = %s RETURNING balance
    """, (net, now, user_id))
    new_bal = cur.fetchone()["balance"]
    
    cur.execute("UPDATE players SET balance = balance + %s WHERE user_id = 0", (tax,))
    conn.commit()
    cur.close()
    conn.close()
    
    return {
        "net": net,
        "tax": tax,
        "tax_percent": int(round(tax_rate * 100)),
        "balance": new_bal
    }

def upgrade_collector(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT balance, collector_level FROM players WHERE user_id = %s", (user_id,))
    p = cur.fetchone()
    cost = p["collector_level"] * 5000
    
    if p["balance"] < cost:
        cur.close()
        conn.close()
        return {"error": f"Недостаточно средств. Нужно {cost} ASG"}
        
    cur.execute("""
        UPDATE players 
        SET balance = balance - %s, collector_level = collector_level + 1 
        WHERE user_id = %s 
        RETURNING balance, collector_level
    """, (cost, user_id))
    updated = cur.fetchone()
    cur.execute("UPDATE players SET balance = balance + %s WHERE user_id = 0", (cost,))
    conn.commit()
    cur.close()
    conn.close()
    return {"balance": updated["balance"], "level": updated["collector_level"], "cost": cost}
