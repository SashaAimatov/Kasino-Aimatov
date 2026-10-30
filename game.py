"""Вся игровая логика живёт на сервере: клиент только показывает результат."""
import math
import random
import time

import database as db
from database import GameError

R = random.SystemRandom()
SYMS = ["💎", "7", "🔔", "🍒", "🍋"]
REDS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def bet_ok(bet):
    if not isinstance(bet, int) or not 1 <= bet <= db.MAX_BET:
        raise GameError(f"Ставка от 1 до {db.MAX_BET:,} ASG")


# ================= МГНОВЕННЫЕ ИГРЫ =================
def play(cur, uid, game, bet, choice):
    bet_ok(bet)
    mult, out = 0, {}
    if game == "slots":
        x = R.random()
        if x < 0.012:
            res, mult = ["7", "7", "7"], 25
        elif x < 0.062:
            s = R.choice(["💎", "🔔", "🍒"])
            res, mult = [s, s, s], 5
        elif x < 0.232:
            res, mult = ["7", "7", R.choice(["💎", "🔔", "🍒", "🍋"])], 2
        else:
            while True:
                res = [R.choice(SYMS) for _ in range(3)]
                if not (res[0] == res[1] == res[2]) and res[:2] != ["7", "7"]:
                    break
        out["reels"] = res
    elif game == "coin":
        if choice not in ("eagle", "tails"):
            raise GameError("Выберите сторону монеты")
        win = R.random() < 0.5
        out["result"] = choice if win else ("tails" if choice == "eagle" else "eagle")
        mult = 1.9 if win else 0
    elif game == "dice":
        d1, d2 = R.randint(1, 6), R.randint(1, 6)
        s = d1 + d2
        out.update(d1=d1, d2=d2, sum=s)
        if choice == "low" and s < 7 or choice == "high" and s > 7:
            mult = 2.2
        elif choice == "seven" and s == 7:
            mult = 5.5
        elif choice not in ("low", "high", "seven"):
            raise GameError("Неверный выбор")
    elif game == "roulette":
        if choice not in ("red", "black", "green"):
            raise GameError("Неверный выбор")
        n = R.randrange(37)
        color = "green" if n == 0 else ("red" if n in REDS else "black")
        out.update(color=color, n=n)
        if color == choice:
            mult = 35 if color == "green" else 1.9
    elif game == "thimbles":
        if choice not in ("0", "1", "2"):
            raise GameError("Неверный выбор")
        cup = R.randrange(3)
        out["cup"] = cup
        mult = 2.8 if cup == int(choice) else 0
    else:
        raise GameError("Неизвестная игра")

    bal = db.to_bank(cur, uid, bet)
    win = 0
    if mult:
        bal, win = db.from_bank(cur, uid, int(bet * mult))
    out.update(balance=bal, win=win)
    return out


# ================= ИГРЫ С СЕССИЕЙ =================
def mines_mult(b, k):
    m = 0.95
    for i in range(k):
        m *= (25 - i) / (25 - b - i)
    return round(m, 2)


def start(cur, uid, game, bet, bombs=3):
    bet_ok(bet)
    if game == "mines":
        if bombs not in (3, 5, 8, 12):
            raise GameError("Неверное число бомб")
        data = {"bet": bet, "b": bombs, "bombs": R.sample(range(25), bombs), "open": []}
    elif game == "hilo":
        data = {"bet": bet, "card": R.randint(2, 14), "mult": 1.0, "steps": 0}
    elif game == "tower":
        data = {"bet": bet, "traps": [R.randrange(3) for _ in range(5)], "floor": 0, "mult": 1.0}
    elif game == "crash":
        r = R.random()
        data = {"bet": bet, "point": min(1000.0, max(1.0, math.floor(95 / (1 - r)) / 100)), "t0": time.time()}
    else:
        raise GameError("Неизвестная игра")
    bal = db.to_bank(cur, uid, bet)
    db.sess_save(cur, uid, game, data)  # новая игра заменяет брошенную
    out = {"balance": bal}
    if game == "hilo":
        out["card"] = data["card"]
    return out


def cash(cur, uid, d, mult):
    bal, win = db.from_bank(cur, uid, int(d["bet"] * mult))
    db.sess_end(cur, uid)
    return {"balance": bal, "win": win, "mult": mult, "ended": True}


def act(cur, uid, game, action, idx=None, direction=None):
    d = db.sess_load(cur, uid, game)

    if game == "mines":
        if action == "cash":
            if not d["open"]:
                raise GameError("Откройте хотя бы одну клетку")
            return cash(cur, uid, d, mines_mult(d["b"], len(d["open"])))
        if not isinstance(idx, int) or not 0 <= idx < 25 or idx in d["open"]:
            raise GameError("Эту клетку открыть нельзя")
        if idx in d["bombs"]:
            db.sess_end(cur, uid)
            return {"boom": True, "bombs": d["bombs"], "ended": True, "win": 0}
        d["open"].append(idx)
        mult = mines_mult(d["b"], len(d["open"]))
        if len(d["open"]) == 25 - d["b"]:
            return {**cash(cur, uid, d, mult), "safe": True}
        db.sess_save(cur, uid, game, d)
        return {"safe": True, "mult": mult, "preview": int(d["bet"] * mult)}

    if game == "hilo":
        if action == "cash":
            if not d["steps"]:
                raise GameError("Сначала угадайте карту")
            return cash(cur, uid, d, d["mult"])
        if direction not in ("hi", "lo"):
            raise GameError("Неверный выбор")
        c, nxt = d["card"], R.randint(2, 14)
        p = (15 - c) / 13 if direction == "hi" else (c - 1) / 13  # шанс угадать (равно = выигрыш)
        if (direction == "hi" and nxt >= c) or (direction == "lo" and nxt <= c):
            d.update(card=nxt, steps=d["steps"] + 1, mult=round(d["mult"] * max(1.02, 0.95 / p), 2))
            db.sess_save(cur, uid, game, d)
            return {"card": nxt, "mult": d["mult"], "preview": int(d["bet"] * d["mult"])}
        db.sess_end(cur, uid)
        return {"card": nxt, "lost": True, "ended": True, "win": 0}

    if game == "tower":
        if action == "cash":
            if not d["floor"]:
                raise GameError("Поднимитесь хотя бы на один этаж")
            return cash(cur, uid, d, d["mult"])
        if not isinstance(idx, int) or not 0 <= idx < 3:
            raise GameError("Неверная дверь")
        trap = d["traps"][d["floor"]]
        if idx == trap:
            db.sess_end(cur, uid)
            return {"lost": True, "trap": trap, "ended": True, "win": 0}
        d["floor"] += 1
        d["mult"] = round(d["mult"] * 1.42, 2)
        if d["floor"] >= 5:
            return {**cash(cur, uid, d, d["mult"]), "safe": True, "floor": 5}
        db.sess_save(cur, uid, game, d)
        return {"safe": True, "floor": d["floor"], "mult": d["mult"], "preview": int(d["bet"] * d["mult"])}

    if game == "crash":
        m = math.floor(math.exp(0.15 * (time.time() - d["t0"])) * 100) / 100
        if m >= d["point"]:
            db.sess_end(cur, uid)
            return {"crashed": True, "point": d["point"], "ended": True, "win": 0}
        if action == "cash":
            return cash(cur, uid, d, m)
        return {"running": True, "mult": m}

    raise GameError("Неизвестная игра")


# ================= ФАРМ, КОЛЛЕКТОРЫ, ПЕРЕВОДЫ =================
def mint(cur, uid, n):
    """Не больше 10 кликов в секунду: лимит считается по времени на сервере."""
    p = db.get_player(cur, uid)
    now = int(time.time() * 1000)
    last = p["last_mint"] or now - 1000
    allow = max(0, min(int(n), 50, (now - last) // 100))
    gain = min(7 * allow, db.MAX_BAL - p["balance"])
    if allow:
        cur.execute("UPDATE players SET balance=balance+%s, last_mint=%s WHERE user_id=%s RETURNING balance",
                    (gain, now, uid))
        p["balance"] = cur.fetchone()["balance"]
        cur.execute("UPDATE players SET balance=balance+%s WHERE user_id=0", (3 * allow,))
    return {"balance": p["balance"], "clicks": allow}


def _lock_pair(cur, uid, target_aima):
    cur.execute("SELECT user_id FROM players WHERE aima_id=%s AND user_id<>0", (target_aima,))
    r = cur.fetchone()
    if not r or r["user_id"] == uid:
        raise GameError("Игрок с таким AIMA-ID не найден")
    # блокируем обе строки в одном порядке, чтобы два перевода навстречу не зависли
    cur.execute("SELECT 1 FROM players WHERE user_id IN (%s,%s) ORDER BY user_id FOR UPDATE", (uid, r["user_id"]))
    return r["user_id"]


def raid(cur, uid, target):
    tuid = _lock_pair(cur, uid, target) if target else None
    p = db.get_player(cur, uid)
    now = int(time.time())
    left = 30 - (now - p["last_raid"])
    if left > 0:
        raise GameError(f"Коллекторы отдыхают ещё {left} с")
    raw = R.randint(150, 400)
    if tuid:
        cur.execute("SELECT balance FROM players WHERE user_id=%s", (tuid,))
        raw = min(raw, cur.fetchone()["balance"])
        if raw <= 0:
            raise GameError("У должника нечего взять")
    tax = math.ceil(raw * 0.30)
    net = raw - tax
    if tuid:  # деньги берутся у должника, 30% уходит казино
        cur.execute("UPDATE players SET balance=balance-%s WHERE user_id=%s", (raw, tuid))
        cur.execute("UPDATE players SET balance=balance+%s WHERE user_id=0", (tax,))
        cur.execute("UPDATE players SET balance=LEAST(%s, balance+%s) WHERE user_id=%s RETURNING balance",
                    (db.MAX_BAL, net, uid))
        bal = cur.fetchone()["balance"]
    else:  # без цели платит казино
        bal, net = db.from_bank(cur, uid, net)
    cur.execute("UPDATE players SET last_raid=%s WHERE user_id=%s", (now, uid))
    return {"balance": bal, "loot": net}


def transfer(cur, uid, target, amount):
    if not isinstance(amount, int) or amount < 10:
        raise GameError("Минимальный перевод — 10 ASG")
    tuid = _lock_pair(cur, uid, target)
    db.get_player(cur, uid)
    cur.execute("SELECT balance, is_banned FROM players WHERE user_id=%s", (tuid,))
    t = cur.fetchone()
    fee = math.ceil(amount / 2)
    sent = amount - fee
    if t["is_banned"]:
        raise GameError("Получатель заблокирован")
    if t["balance"] + sent > db.MAX_BAL:
        raise GameError("У получателя достигнут лимит баланса")
    bal = db.to_bank(cur, uid, amount)
    cur.execute("UPDATE players SET balance=balance-%s WHERE user_id=0", (sent,))
    cur.execute("UPDATE players SET balance=balance+%s WHERE user_id=%s", (sent, tuid))
    return {"balance": bal, "sent": sent, "fee": fee}
