import threading
import math
import random
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

import config
import database as db

# Современный запуск бота в фоновом потоке при старте сервера
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    bot_thread = threading.Thread(target=bot.infinity_polling, kwargs={"skip_pending": True}, daemon=True)
    bot_thread.start()
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode="HTML")

@bot.message_handler(commands=['start'])
def cmd_start(message):
    player = db.get_or_create_player(message.from_user.id, message.from_user.first_name)
    if player["is_banned"]:
        bot.send_message(message.chat.id, "🚫 Ваш аккаунт заблокирован.")
        return

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(
        text="🕹 Открыть Aimatov Casino",
        web_app=WebAppInfo(url=config.WEBAPP_URL)
    ))

    text = (
        f"🏛 <b>Aimatov Silver Group</b>\n\n"
        f"👤 Игрок: <b>{player['username']}</b>\n"
        f"💳 Ваш AIMA-ID:\n<code>{player['aima_id']}</code>\n"
        f"💰 Баланс: <b>{player['balance']:,.2f} ASG</b>"
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    if message.from_user.id != config.ADMIN_ID:
        return
    bank = db.get_casino_bank()
    text = (
        f"👑 <b>АДМИН-ПАНЕЛЬ AIMATOV SILVER</b>\n"
        f"🏦 Банк казино: <b>{bank:,.2f} ASG</b>\n\n"
        f"• <code>/give ID СУММА</code> — начислить / списать\n"
        f"• <code>/setbal ID СУММА</code> — установить баланс\n"
        f"• <code>/casino СУММА</code> — установить банк казино\n"
        f"• <code>/ban ID</code> / <code>/unban ID</code> — блокировка"
    )
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['casino'])
def cmd_casino(message):
    if message.from_user.id != config.ADMIN_ID:
        return
    args = message.text.split()
    if len(args) == 2:
        amount = float(args[1])
        db.set_casino_bank(amount)
        bot.send_message(message.chat.id, f"🏛 Банк Казино установлен на: <b>{amount:,.2f} ASG</b>")

@bot.message_handler(commands=['give', 'setbal', 'set'])
def cmd_balance(message):
    if message.from_user.id != config.ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 3:
        bot.send_message(message.chat.id, "⚠️ Формат: <code>/give ID СУММА</code>")
        return
    mode = "give" if args[0] == "/give" else "set"
    if db.update_balance_by_target(args[1].strip(), float(args[2]), mode=mode):
        bot.send_message(message.chat.id, f"✅ Баланс <code>{args[1]}</code> обновлен на <b>{float(args[2]):,.2f} ASG</b>")
    else:
        bot.send_message(message.chat.id, "❌ Игрок не найден.")

@bot.message_handler(commands=['ban', 'unban'])
def cmd_ban(message):
    if message.from_user.id != config.ADMIN_ID:
        return
    args = message.text.split()
    if len(args) == 2:
        is_ban = (args[0] == '/ban')
        db.set_ban_status(args[1].strip(), is_ban)
        bot.send_message(message.chat.id, f"✅ Статус бана для <code>{args[1]}</code> обновлен.")

class UserReq(BaseModel):
    user_id: int
    username: str = "Player"

@app.get("/")
def root():
    return {"status": "ok"}

@app.post("/api/user")
def api_user(req: UserReq):
    p = db.get_or_create_player(req.user_id, req.username)
    now = int(time.time())
    elapsed = min(max(0, now - p["last_collect"]), 43200)
    return {
        "aima_id": p["aima_id"],
        "balance": p["balance"],
        "collector_level": p["collector_level"],
        "pending_collector": math.floor(elapsed * (p["collector_level"] * 2.0)),
        "casino_bank": db.get_casino_bank()
    }
