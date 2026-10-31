import hashlib
import hmac
import html
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import parse_qsl

import telebot
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

import config
import database as db
import games

bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode="HTML")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    threading.Thread(target=bot.infinity_polling, kwargs={"skip_pending": True}, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Init-Data"],
)


# ================= ПРОВЕРКА ЛИЧНОСТИ (подпись Telegram) =================
def current_user(x_init_data: str = Header(default="")):
    """user_id берётся только из подписанных Telegram данных, подделать его нельзя."""
    try:
        data = dict(parse_qsl(x_init_data, keep_blank_values=True))
        got = data.pop("hash")
        check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        key = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got) or time.time() - int(data["auth_date"]) > 7 * 86400:
            raise ValueError
        u = json.loads(data["user"])
        return int(u["id"]), (u.get("first_name") or "Player")
    except Exception:
        raise HTTPException(401, "Откройте игру через Telegram-бота")


def run(fn, user, *args, own=True):
    """Выполняет действие в одной транзакции. own=False — функция сама блокирует строки игроков."""
    uid, name = user
    try:
        with db.tx() as cur:
            if own:
                db.get_player(cur, uid, name)
            return fn(cur, uid, *args)
    except db.GameError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        # HTTPException проходит через CORS-middleware, а "голая" ошибка 500 нет:
        # браузер тогда пишет "нет связи". Так мы увидим настоящую причину.
        logging.exception("api error")
        raise HTTPException(500, f"Ошибка сервера: {type(e).__name__}: {e}"[:300])


# ================= API =================
class PlayReq(BaseModel):
    game: str
    bet: int
    choice: str = ""


class StartReq(BaseModel):
    game: str
    bet: int
    bombs: int = 3


class ActReq(BaseModel):
    game: str
    action: str = ""
    idx: Optional[int] = None
    direction: Optional[str] = None


class MintReq(BaseModel):
    n: int


class RaidReq(BaseModel):
    target_aima: str = ""


class TransferReq(BaseModel):
    target_aima: str
    amount: int


@app.get("/")
def root():
    return {"status": "ok"}


def _user(cur, uid):
    p = db.get_player(cur, uid)
    return {"aima_id": p["aima_id"], "balance": p["balance"],
            "casino_bank": db.bank(cur), "forbes": db.get_forbes(cur)}


@app.post("/api/user")
def api_user(u=Depends(current_user)):
    return run(_user, u)


@app.get("/health")
def health():
    """Открой в браузере: покажет, живо ли подключение к базе."""
    def check(cur, uid):
        cur.execute("SELECT COUNT(*) AS n FROM players")
        return {"db": "ok", "players": cur.fetchone()["n"]}
    return run(check, (0, ""), own=False)


@app.get("/api/forbes")
def api_forbes():
    def top(cur, uid):
        return {"casino_bank": db.bank(cur), "leaders": db.get_forbes(cur)}
    return run(top, (0, ""), own=False)


@app.post("/api/play")
def api_play(r: PlayReq, u=Depends(current_user)):
    return run(games.play, u, r.game, r.bet, r.choice)


@app.post("/api/start")
def api_start(r: StartReq, u=Depends(current_user)):
    return run(games.start, u, r.game, r.bet, r.bombs)


@app.post("/api/act")
def api_act(r: ActReq, u=Depends(current_user)):
    return run(games.act, u, r.game, r.action, r.idx, r.direction)


@app.post("/api/mint")
def api_mint(r: MintReq, u=Depends(current_user)):
    return run(games.mint, u, r.n)


@app.post("/api/collector_raid")
def api_collector_raid(r: RaidReq, u=Depends(current_user)):
    return run(games.raid, u, r.target_aima.strip(), own=False)


@app.post("/api/transfer")
def api_transfer(r: TransferReq, u=Depends(current_user)):
    return run(games.transfer, u, r.target_aima.strip(), r.amount, own=False)


# ================= БОТ =================
def is_admin(m):
    return m.from_user.id == config.ADMIN_ID


@bot.message_handler(commands=["start"])
def cmd_start(message):
    with db.tx() as cur:
        p = db.get_player(cur, message.from_user.id, message.from_user.first_name, banned_ok=True)
    if p["is_banned"]:
        bot.send_message(message.chat.id, "🚫 Ваш аккаунт заблокирован.")
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🕹 Открыть Kasino Aimatov", web_app=WebAppInfo(url=config.WEBAPP_URL)))
    bot.send_message(
        message.chat.id,
        f"🏛 <b>Aimatov Silver Group</b>\n\n"
        f"👤 Игрок: <b>{html.escape(p['username'] or '')}</b>\n"
        f"💳 Ваш AIMA-ID:\n<code>{p['aima_id']}</code>\n"
        f"💰 Счет игрока: <b>{int(p['balance']):,} ASG</b>",
        reply_markup=markup)


@bot.message_handler(commands=["setbal", "set", "give"], func=is_admin)
def cmd_balance(message):
    a = message.text.split()
    mode = "give" if a[0].startswith("/give") else "set"
    if len(a) != 3:
        bot.send_message(message.chat.id, f"⚠️ Формат: <code>/{'give' if mode == 'give' else 'setbal'} ID СУММА</code>")
        return
    try:
        amount = int(float(a[2]))
        ok = db.admin_balance(a[1].strip(), amount, mode)
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ ID и сумма должны быть числами (или AIMA-ID).")
        return
    text = f"✅ <code>{html.escape(a[1])}</code>: {'начислено' if mode == 'give' else 'баланс'} {amount:,} ASG" \
        if ok else "❌ Игрок не найден."
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=["casino"], func=is_admin)
def cmd_casino(message):
    a = message.text.split()
    try:
        amount = int(float(a[1]))
    except (IndexError, ValueError):
        bot.send_message(message.chat.id, "⚠️ Формат: <code>/casino СУММА</code>")
        return
    db.set_bank(amount)
    bot.send_message(message.chat.id, f"🏛 Банк Казино установлен на: <b>{max(0, amount):,} ASG</b>")
