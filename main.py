import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

import config
import database as db

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    bot_thread = threading.Thread(
        target=bot.infinity_polling,
        kwargs={"skip_pending": True},
        daemon=True
    )
    bot_thread.start()
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode="HTML")

@bot.message_handler(commands=['start'])
def cmd_start(message):
    player = db.get_or_create_player(message.from_user.id, message.from_user.first_name)
    if player.get("is_banned"):
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

@bot.message_handler(commands=['setbal', 'set'])
def cmd_balance(message):
    if message.from_user.id != config.ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 3:
        bot.send_message(message.chat.id, "⚠️ Формат: <code>/setbal AIMA-ID_ИЛИ_TG_ID СУММА</code>")
        return
    if db.update_balance_by_target(args[1].strip(), float(args[2]), mode="set"):
        bot.send_message(message.chat.id, f"✅ Баланс <code>{args[1]}</code> установлен на <b>{int(float(args[2])):,} ASG</b>")
    else:
        bot.send_message(message.chat.id, "❌ Игрок не найден.")

@bot.message_handler(commands=['give'])
def cmd_give(message):
    if message.from_user.id != config.ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 3:
        return
    db.update_balance_by_target(args[1].strip(), float(args[2]), mode="give")
    bot.send_message(message.chat.id, f"✅ Баланс пополнен.")

@bot.message_handler(commands=['casino'])
def cmd_casino(message):
    if message.from_user.id != config.ADMIN_ID:
        return
    args = message.text.split()
    if len(args) == 2:
        amount = int(float(args[1]))
        db.set_casino_bank(amount)
        bot.send_message(message.chat.id, f"🏛 Банк Казино установлен на: <b>{amount:,} ASG</b>")

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
    return {
        "aima_id": p["aima_id"],
        "balance": int(p["balance"]),
        "casino_bank": int(db.get_casino_bank())
    }

@app.post("/api/sync")
def api_sync(req: SyncReq):
    res = db.sync_player_delta(req.user_id, req.balance_delta, req.bank_delta)
    return {
        "balance": int(res["balance"]) if res else 0,
        "casino_bank": int(db.get_casino_bank())
    }

@app.get("/api/forbes")
def api_forbes():
    rows = db.get_forbes_list(50)
    data = {
        "casino_bank": int(db.get_casino_bank()),
        "leaders": [
            {
                "username": str(r["username"] or "Игрок"),
                "aima_id": str(r["aima_id"]),
                "balance": int(r["balance"])
            }
            for r in rows
        ]
    }
    return JSONResponse(
        content=data,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }
    )

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
