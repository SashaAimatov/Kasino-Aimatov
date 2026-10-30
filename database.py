import psycopg2
from config import DATABASE_URL

def get_conn():
    return psycopg2.connect(DATABASE_URL.strip())

def make_aima_id(id_val):
    if id_val == 0:
        return "AIMA-0000-0000-BANK-RESERVE"
    s = str(id_val).zfill(8) if len(str(id_val)) <= 8 else str(id_val)
    s_clean = s[-8:].zfill(8)
    return f"AIMA-{s_clean[:4]}-{s_clean[4:]}-8492-1049"

def init_db():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            balance DOUBLE PRECISION DEFAULT 500000.0,
            aima_id TEXT,
            banned INTEGER DEFAULT 0
        )
    """)
    
    # Креирање на Банката на Казиното (ID = 0)
    cursor.execute("""
        INSERT INTO players (user_id, username, balance, aima_id, banned)
        VALUES (0, '🏛 Aimatov Casino (Банк)', 100000000.0, 'AIMA-0000-0000-BANK-RESERVE', 0)
        ON CONFLICT (user_id) DO NOTHING
    """)
    conn.commit()
    cursor.close()
    conn.close()

def get_player(user_id, username=None):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT username, balance, aima_id, banned FROM players WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        uname = username if username else f"Player_{str(user_id)[-4:]}"
        aima_id = make_aima_id(user_id)
        cursor.execute(
            "INSERT INTO players (user_id, username, balance, aima_id) VALUES (%s, %s, 500000.0, %s)", 
            (user_id, uname, aima_id)
        )
        conn.commit()
        balance, banned = 500000.0, 0
    else:
        db_uname, balance, aima_id, banned = row[0], row[1], row[2], row[3]
        if username and username != "Player" and username != db_uname:
            cursor.execute("UPDATE players SET username = %s WHERE user_id = %s", (username, user_id))
            conn.commit()
            uname = username
        else:
            uname = db_uname
            
    cursor.close()
    conn.close()
    return {"id": user_id, "username": uname, "balance": float(balance), "aima_id": aima_id, "banned": banned}

def update_balance(user_id, amount, affect_casino=False):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE players SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
    
    if affect_casino and user_id != 0:
        cursor.execute("UPDATE players SET balance = balance - %s WHERE user_id = 0", (amount,))
        
    conn.commit()
    cursor.execute("SELECT balance FROM players WHERE user_id = %s", (user_id,))
    new_bal = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return float(new_bal)

def set_balance(target, amount):
    conn = get_conn()
    cursor = conn.cursor()
    if str(target).isdigit():
        cursor.execute("UPDATE players SET balance = %s WHERE user_id = %s RETURNING username, balance", (amount, int(target)))
    else:
        cursor.execute("UPDATE players SET balance = %s WHERE aima_id = %s OR username = %s RETURNING username, balance", (amount, target, target.lstrip('@')))
    row = cursor.fetchone()
    conn.commit()
    cursor.close()
    conn.close()
    return row

def set_ban(target, ban_status):
    conn = get_conn()
    cursor = conn.cursor()
    if str(target).isdigit():
        cursor.execute("UPDATE players SET banned = %s WHERE user_id = %s RETURNING username", (ban_status, int(target)))
    else:
        cursor.execute("UPDATE players SET banned = %s WHERE aima_id = %s OR username = %s RETURNING username", (ban_status, target, target.lstrip('@')))
    row = cursor.fetchone()
    conn.commit()
    cursor.close()
    conn.close()
    return row

def transfer_money(sender_id, target_str, amount):
    if amount <= 0:
        return {"error": "Сумата мора да биде поголема од 0"}
    conn = get_conn()
    cursor = conn.cursor()
    
    cursor.execute("SELECT balance, banned FROM players WHERE user_id = %s", (sender_id,))
    sender = cursor.fetchone()
    if not sender:
        cursor.close(); conn.close()
        return {"error": "Испраќачот не е пронајден"}
    if sender[1] == 1:
        cursor.close(); conn.close()
        return {"error": "Вашиот профил е блокиран"}
    if sender[0] < amount:
        cursor.close(); conn.close()
        return {"error": "Немате доволно средства"}

    target_clean = str(target_str).strip()
    if target_clean.isdigit():
        cursor.execute("SELECT user_id, username FROM players WHERE user_id = %s", (int(target_clean),))
    else:
        cursor.execute("SELECT user_id, username FROM players WHERE aima_id = %s OR LOWER(username) = LOWER(%s)", (target_clean, target_clean.lstrip('@')))
        
    recipient = cursor.fetchone()
    if not recipient:
        cursor.close(); conn.close()
        return {"error": "Примачот не е пронајден во базата"}
        
    rec_id, rec_name = recipient[0], recipient[1]
    if rec_id == sender_id:
        cursor.close(); conn.close()
        return {"error": "Не можете да си префртите пари на самите себе"}

    cursor.execute("UPDATE players SET balance = balance - %s WHERE user_id = %s", (amount, sender_id))
    cursor.execute("UPDATE players SET balance = balance + %s WHERE user_id = %s", (amount, rec_id))
    conn.commit()
    
    cursor.execute("SELECT balance FROM players WHERE user_id = %s", (sender_id,))
    new_bal = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return {"status": "ok", "new_balance": float(new_bal), "recipient": rec_name}

def get_all_leaderboard():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, balance, aima_id, banned FROM players ORDER BY balance DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    result = []
    for r in rows:
        result.append({
            "user_id": r[0],
            "username": r[1] if r[1] else f"Player_{str(r[0])[-4:]}",
            "balance": float(r[2]),
            "aima_id": r[3],
            "is_casino": (r[0] == 0),
            "banned": r[4]
        })
    return result
