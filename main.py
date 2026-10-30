import threading
import math
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

import config
import database as db

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
        text="🕹 Открыть Kasino Aimatov",
        web_app=WebAppInfo(url=config.WEBAPP_URL)
    ))

    text = (
        f"🏛 <b>Aimatov Silver Group</b>\n\n"
        f"👤 Игрок: <b>{player['username']}</b>\n"
        f"💳 Ваш AIMA-ID:\n<code>{player['aima_id']}</code>\n"
        f"💰 Счет игрока: <b>{int(player['balance']):,} ASG</b>"
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    if message.from_user.id != config.ADMIN_ID:
        return
    bank = db.get_casino_bank()
    text = (
        f"👑 <b>АДМИН-ПАНЕЛЬ AIMATOV SILVER</b>\n"
        f"🏦 Банк казино: <b>{bank:,} ASG</b>\n\n"
        f"• <code>/give ID СУММА</code> — выдать/списать ASG\n"
        f"• <code>/setbal ID СУММА</code> — установить точный баланс\n"
        f"• <code>/casino СУММА</code> — установить банк казино\n"
        f"• <code>/ban ID</code> / <code>/unban ID</code> — бан игрока"
    )
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['casino'])
def cmd_casino(message):
    if message.from_user.id != config.ADMIN_ID:
        return
    args = message.text.split()
    if len(args) == 2:
        amount = int(float(args[1]))
        db.set_casino_bank(amount)
        bot.send_message(message.chat.id, f"🏛 Банк Казино установлен на: <b>{amount:,} ASG</b>")

@bot.message_handler(commands=['give', 'setbal', 'set'])
def cmd_balance(message):
    if message.from_user.id != config.ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 3:
        bot.send_message(message.chat.id, "⚠️ Формат: <code>/give AIMA-ID СУММА</code>")
        return
    mode = "give" if args[0] == "/give" else "set"
    if db.update_balance_by_target(args[1].strip(), float(args[2]), mode=mode):
        bot.send_message(message.chat.id, f"✅ Баланс <code>{args[1]}</code> обновлен.")
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
        bot.send_message(message.chat.id, f"✅ Статус блокировки <code>{args[1]}</code> изменен.")

class UserReq(BaseModel):
    user_id: int
    username: str = "Player"

class SyncReq(BaseModel):
    user_id: int
    balance_delta: int
    bank_delta: int

class TransferReq(BaseModel):
    user_id: int
    target_aima: str
    amount: int

class RaidReq(BaseModel):
    user_id: int
    target_aima: str = ""

@app.get("/")
def root():
    return {"status": "Aimatov Silver Group Server OK"}

@app.post("/api/user")
def api_user(req: UserReq):
    p = db.get_or_create_player(req.user_id, req.username)
    if p["is_banned"]:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")
    return {
        "aima_id": p["aima_id"],
        "balance": int(p["balance"]),
        "debt": int(p.get("debt", 0)),
        "collector_level": p["collector_level"],
        "casino_bank": db.get_casino_bank()
    }

@app.post("/api/sync")
def api_sync(req: SyncReq):
    res = db.sync_player_delta(req.user_id, req.balance_delta, req.bank_delta)
    return {
        "balance": int(res["balance"]) if res else 0,
        "casino_bank": db.get_casino_bank()
    }

@app.get("/api/forbes")
def api_forbes():
    rows = db.get_forbes_list(25)
    return {
        "casino_bank": db.get_casino_bank(),
        "leaders": [
            {
                "username": r["username"] or "Аноним",
                "aima_id": r["aima_id"],
                "balance": int(r["balance"]),
                "collector_level": r["collector_level"]
            }
            for r in rows
        ]
    }

@app.post("/api/transfer")
def api_transfer(req: TransferReq):
    res = db.transfer_asg(req.user_id, req.target_aima, req.amount)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.post("/api/collector_raid")
def api_collector_raid(req: RaidReq):
    res = db.collector_raid_action(req.user_id, req.target_aima)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res
