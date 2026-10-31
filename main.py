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


def reply(m, text):
    bot.send_message(m.chat.id, text)


def esc(x):
    return html.escape(str(x if x is not None else ""))


def num(s):
    return int(float(s))


def admin_cmd(*names):
    """Команда доступна только админу; ошибки ввода объясняются, а не роняют бота."""
    def deco(fn):
        @bot.message_handler(commands=list(names), func=is_admin)
        def wrapper(m):
            try:
                fn(m, m.text.split()[1:])
            except (ValueError, IndexError):
                reply(m, "⚠️ Неверный формат. Все команды и примеры: /admin")
            except Exception as e:
                logging.exception("admin command failed")
                reply(m, f"❌ Ошибка: {esc(type(e).__name__)}")
        return wrapper
    return deco


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
        f"👤 Игрок: <b>{esc(p['username'])}</b>\n"
        f"💳 Ваш AIMA-ID:\n<code>{p['aima_id']}</code>\n"
        f"💰 Счет игрока: <b>{int(p['balance']):,} ASG</b>",
        reply_markup=markup)


@bot.message_handler(commands=["whoami"])
def cmd_whoami(message):
    u = message.from_user
    bot.send_message(
        message.chat.id,
        f"ID: <code>{u.id}</code>\n"
        f"Ник: {'@' + esc(u.username) if u.username else 'не задан'}\n"
        f"Админ: {'да' if is_admin(message) else 'нет'}")


HELP = (
    "🛠 <b>Команды админа</b>\n\n"
    "💰 <b>Баланс игроков</b>\n"
    "/give ID СУММА — выдать деньги\n"
    "/take ID СУММА — списать деньги\n"
    "/setbal ID СУММА — установить точный баланс (то же: /set)\n"
    "/reset ID — сбросить баланс до 500 000\n\n"
    "🚫 <b>Блокировки</b>\n"
    "/ban ID — забанить (игра и API закрываются)\n"
    "/unban ID — разбанить\n\n"
    "🏛 <b>Казино</b>\n"
    "/casino — показать банк\n"
    "/casino СУММА — установить банк\n"
    "/casinoadd СУММА — добавить в банк (с минусом — убавить)\n\n"
    "📊 <b>Информация</b>\n"
    "/player ID — карточка игрока\n"
    "/top N — богатейшие игроки (по умолчанию 10)\n"
    "/stats — игроков, деньги на руках, банк, баны\n\n"
    "📣 <b>Рассылка</b>\n"
    "/broadcast ТЕКСТ — сообщение всем незабаненным игрокам\n\n"
    "ID — числовой Telegram ID, AIMA-ID или имя игрока.\n"
    "Пример: /give 5399819309 5000\n"
    "Потолок баланса игрока: 50 000 000 ASG."
)


@admin_cmd("admin")
def c_admin(m, a):
    reply(m, HELP)


def _balance(m, a, mode):
    amount = num(a[1])
    r = db.admin_balance(a[0], amount, mode)
    if not r:
        return reply(m, "❌ Игрок не найден.")
    p, new = r
    what = {"set": "Баланс установлен", "give": f"Выдано {amount:,} ASG", "take": f"Списано {amount:,} ASG"}[mode]
    reply(m, f"✅ {esc(p['username'])} (<code>{p['user_id']}</code>)\n{what}\n💰 Баланс: <b>{new:,} ASG</b>")


@admin_cmd("setbal", "set")
def c_set(m, a):
    _balance(m, a, "set")


@admin_cmd("give")
def c_give(m, a):
    _balance(m, a, "give")


@admin_cmd("take")
def c_take(m, a):
    _balance(m, a, "take")


@admin_cmd("reset")
def c_reset(m, a):
    _balance(m, [a[0], str(db.START_BAL)], "set")


def _ban(m, a, flag):
    p = db.player_info(a[0])
    if p and p["user_id"] == config.ADMIN_ID:
        return reply(m, "❌ Себя банить нельзя.")
    p = db.set_ban(a[0], flag)
    if not p:
        return reply(m, "❌ Игрок не найден.")
    reply(m, f"{'🚫 Забанен' if flag else '✅ Разбанен'}: {esc(p['username'])} (<code>{p['user_id']}</code>)")
    try:
        bot.send_message(p["user_id"], "🚫 Ваш аккаунт заблокирован." if flag else "✅ Ваш аккаунт разблокирован.")
    except Exception:
        pass  # игрок мог не запускать бота


@admin_cmd("ban")
def c_ban(m, a):
    _ban(m, a, True)


@admin_cmd("unban")
def c_unban(m, a):
    _ban(m, a, False)


@admin_cmd("casino")
def c_casino(m, a):
    new = db.set_bank(num(a[0])) if a else db.stats()["bank"]
    reply(m, f"🏛 Банк Казино: <b>{new:,} ASG</b>")


@admin_cmd("casinoadd")
def c_casinoadd(m, a):
    reply(m, f"🏛 Банк Казино: <b>{db.add_bank(num(a[0])):,} ASG</b>")


@admin_cmd("player")
def c_player(m, a):
    p = db.player_info(a[0])
    if not p:
        return reply(m, "❌ Игрок не найден.")
    reply(m, f"👤 <b>{esc(p['username'])}</b>\n"
             f"ID: <code>{p['user_id']}</code>\n"
             f"AIMA-ID: <code>{p['aima_id']}</code>\n"
             f"💰 Баланс: <b>{int(p['balance']):,} ASG</b>\n"
             f"Статус: {'🚫 забанен' if p['is_banned'] else '✅ активен'}")


@admin_cmd("top")
def c_top(m, a):
    n = max(1, min(num(a[0]) if a else 10, 30))
    rows = db.top(n)
    lines = [f"{i}. {esc(r['username'])} — {r['balance']:,} ASG" for i, r in enumerate(rows, 1)]
    reply(m, "🏆 <b>Топ игроков</b>\n" + ("\n".join(lines) or "Пока никого."))


@admin_cmd("stats")
def c_stats(m, a):
    s = db.stats()
    reply(m, f"📊 <b>Статистика</b>\n"
             f"Игроков: <b>{s['players']}</b> (забанено: {s['banned']})\n"
             f"Деньги на руках: <b>{s['total']:,} ASG</b>\n"
             f"Банк казино: <b>{s['bank']:,} ASG</b>")


@admin_cmd("broadcast")
def c_broadcast(m, a):
    text = m.text.split(maxsplit=1)[1]
    ids = db.all_ids()
    reply(m, f"📣 Рассылка запущена: {len(ids)} получателей…")

    def send():
        ok = 0
        for uid in ids:
            try:
                bot.send_message(uid, text, parse_mode=None)
                ok += 1
            except Exception:
                pass  # игрок не запускал бота или заблокировал его
            time.sleep(0.05)  # лимиты Telegram
        reply(m, f"✅ Доставлено: {ok} из {len(ids)}")

    threading.Thread(target=send, daemon=True).start()
