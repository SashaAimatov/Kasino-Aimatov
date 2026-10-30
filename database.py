import psycopg2
from config import DATABASE_URL

def get_conn():
    # psycopg2 отлично понимает ссылку, которую выдает Render
    return psycopg2.connect(DATABASE_URL)

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
    conn.commit()
    cursor.close()
    conn.close()

def make_aima_id(id_val):
    s = str(id_val).zfill(8) if len(str(id_val)) <= 8 else str(id_val)
    s_clean = s[-8:].zfill(8)
    return f"AIMA-{s_clean[:4]}-{s_clean[4:]}-8492-1049"

def get_player(user_id, username="Player"):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT balance, aima_id, banned FROM players WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        aima_id = make_aima_id(user_id)
        cursor.execute(
            "INSERT INTO players (user_id, username, balance, aima_id) VALUES (%s, %s, 500000.0, %s)", 
            (user_id, username, aima_id)
        )
        conn.commit()
        balance, banned = 500000.0, 0
    else:
        balance, aima_id, banned = row[0], row[1], row[2]
        cursor.execute("UPDATE players SET username = %s WHERE user_id = %s", (username, user_id))
        conn.commit()
        
    cursor.close()
    conn.close()
    return {"id": user_id, "username": username, "balance": balance, "aima_id": aima_id, "banned": banned}

def update_balance(user_id, amount):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE players SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
    conn.commit()
    
    cursor.execute("SELECT balance FROM players WHERE user_id = %s", (user_id,))
    new_bal = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return new_bal
