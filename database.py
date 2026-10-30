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
            balance BIGINT DEFAULT 10000,
            debt BIGINT DEFAULT 0,
            collector_level INT DEFAULT 1,
            last_collect BIGINT DEFAULT 0,
            is_banned BOOLEAN DEFAULT FALSE
        );
    """)
    # На случай если таблица уже была создана со старыми типами
    cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS debt BIGINT DEFAULT 0;")
    cur.execute("""
        INSERT INTO players (user_id, username, aima_id, balance, debt)
        VALUES (0, 'CASINO_BANK', 'AIMA-0000-0000-0000-0000', 1000000000, 0)
        ON CONFLICT (user_id) DO NOTHING;
    """)
    # Исправляем баг с гигантским минусом (-54 млрд), переводя старый минус в контролируемый долг
    cur.execute("UPDATE players SET debt = 50000, balance = 0 WHERE balance < -1000000;")
    conn.commit()
    cur.close()
    conn.close()

def generate_aima_id(user_id: int) -> str:
    random.seed(user_id + int(time.time()))
    parts = [f"{random.randint(1000, 9999)}" for _ in range(4)]
    return "AIMA-" + "-".join(parts)

def get_or_create_player(user_id: int, username: str = "Player"):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE user_id = %s", (user_id,))
    player = cur.fetchone()
    
    now = int(time.time())
    if not player:
        aima_id = generate_aima_id(user_id)
        cur.execute("""
            INSERT INTO players (user_id, username, aima_id, balance, debt, collector_level, last_collect)
            VALUES (%s, %s, %s, 10000, 0, 1, %s)
            RETURNING *;
        """, (user_id, username, aima_id, now))
        player = cur.fetchone()
        conn.commit()
    else:
        # Работа коллекторов: если у игрока есть долг или отрицательный баланс, коллекторы выбивают 15%
        if player["debt"] > 0 and player["balance"] > 0:
            seized = min(player["balance"], max(10, int(player["debt"] * 0.25)))
            cur.execute("""
                UPDATE players 
                SET balance = balance - %s, debt = GREATEST(0, debt - %s)
                WHERE user_id = %s RETURNING *;
            """, (seized, seized, user_id))
            player = cur.fetchone()
            cur.execute("UPDATE players SET balance = balance + %s WHERE user_id = 0", (seized,))
            conn.commit()

    cur.close()
    conn.close()
    return player

def get_casino_bank() -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM players WHERE user_id = 0")
    row = cur.fetchone()
    cur.close()
    conn.close()
    return max(1000000, int(row["balance"])) if row else 1000000000

def set_casino_bank(amount: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE players SET balance = %s WHERE user_id = 0", (int(amount),))
    conn.commit()
    cur.close()
    conn.close()

def sync_player_delta(user_id: int, balance_delta: int, bank_delta: int):
    conn = get_conn()
    cur = conn.cursor()
    # Если игрок выигрывает слишком много, режем выплату до 5% от банка казино (защита от банкротства)
    bank = get_casino_bank()
    max_win = int(bank * 0.05)
    if balance_delta > max_win:
        balance_delta = max_win
        bank_delta = -max_win

    cur.execute("""
        UPDATE players 
        SET balance = GREATEST(0, balance + %s)
        WHERE user_id = %s RETURNING balance, debt;
    """, (int(balance_delta), user_id))
    res = cur.fetchone()
    cur.execute("UPDATE players SET balance = GREATEST(100000, balance + %s) WHERE user_id = 0", (int(bank_delta),))
    conn.commit()
    cur.close()
    conn.close()
    return res

def get_forbes_list(limit: int = 20):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT username, aima_id, balance, collector_level 
        FROM players 
        WHERE user_id != 0 AND is_banned = FALSE
        ORDER BY balance DESC 
        LIMIT %s;
    """, (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def transfer_asg(sender_id: int, target_aima: str, amount: int):
    if amount <= 0:
        return {"error": "Сумма должна быть больше 0"}
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE user_id = %s", (sender_id,))
    sender = cur.fetchone()
    if not sender or sender["balance"] < amount:
        cur.close()
        conn.close()
        return {"error": "Недостаточно ASG на счете"}

    cur.execute("SELECT * FROM players WHERE aima_id = %s", (target_aima.strip(),))
    receiver = cur.fetchone()
    if not receiver:
        cur.close()
        conn.close()
        return {"error": "Получатель с таким AIMA-ID не найден"}

    # Комиссия за перевод ровно 50% в пользу казино
    fee = math.ceil(amount * 0.50)
    net_amount = math.floor(amount - fee)

    cur.execute("UPDATE players SET balance = balance - %s WHERE user_id = %s RETURNING balance", (amount, sender_id))
    new_bal = cur.fetchone()["balance"]
    cur.execute("UPDATE players SET balance = balance + %s WHERE user_id = %s", (net_amount, receiver["user_id"]))
    cur.execute("UPDATE players SET balance = balance + %s WHERE user_id = 0", (fee,))
    conn.commit()
    cur.close()
    conn.close()
    return {"balance": new_bal, "sent": net_amount, "fee": fee}

def collector_raid_action(attacker_id: int, target_aima: str = ""):
    """Механика коллекторов: выбивание долгов из должников или других игроков"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players WHERE user_id = %s", (attacker_id,))
    attacker = cur.fetchone()
    if not attacker:
        cur.close()
        conn.close()
        return {"error": "Игрок не найден"}

    if target_aima:
        cur.execute("SELECT * FROM players WHERE aima_id = %s AND user_id != 0 AND user_id != %s", (target_aima.strip(), attacker_id))
    else:
        cur.execute("SELECT * FROM players WHERE user_id != 0 AND user_id != %s AND balance > 100 ORDER BY RANDOM() LIMIT 1", (attacker_id,))
    victim = cur.fetchone()

    lvl = attacker["collector_level"]
    # Если в базе пока нет других жертв, коллекторы выбивают долг из теневых должников казино
    if not victim:
        raw_loot = random.randint(150, 450) * lvl
        tax = math.ceil(raw_loot * 0.30)
        net = raw_loot - tax
        cur.execute("UPDATE players SET balance = balance + %s WHERE user_id = %s RETURNING balance", (net, attacker_id))
        new_bal = cur.fetchone()["balance"]
        cur.execute("UPDATE players SET balance = balance + %s WHERE user_id = 0", (tax,))
        conn.commit()
        cur.close()
        conn.close()
        return {"balance": new_bal, "loot": net, "tax": tax, "victim": "Теневой должник"}

    # Выбиваем от 5% до 12% баланса цели (ограничено уровнем коллектора)
    max_take = min(int(victim["balance"] * 0.12), lvl * 2500)
    raw_loot = max(50, max_take)
    tax = math.ceil(raw_loot * 0.30)  # 30% доля казино
    net = raw_loot - tax

    cur.execute("UPDATE players SET balance = GREATEST(0, balance - %s) WHERE user_id = %s", (raw_loot, victim["user_id"]))
    cur.execute("UPDATE players SET balance = balance + %s WHERE user_id = %s RETURNING balance", (net, attacker_id))
    new_bal = cur.fetchone()["balance"]
    cur.execute("UPDATE players SET balance = balance + %s WHERE user_id = 0", (tax,))
    conn.commit()
    cur.close()
    conn.close()
    return {"balance": new_bal, "loot": net, "tax": tax, "victim": victim["username"] or victim["aima_id"]}

def update_balance_by_target(target: str, amount: float, mode: str = "give") -> bool:
    conn = get_conn()
    cur = conn.cursor()
    amt = int(amount)
    if target.startswith("AIMA-"):
        op = "GREATEST(0, balance + %s)" if mode == "give" else "%s"
        cur.execute(f"UPDATE players SET balance = {op}, debt = 0 WHERE aima_id = %s RETURNING user_id", (amt, target))
    else:
        op = "GREATEST(0, balance + %s)" if mode == "give" else "%s"
        cur.execute(f"UPDATE players SET balance = {op}, debt = 0 WHERE user_id = %s RETURNING user_id", (amt, int(target)))
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
