import os
import asyncio
import random
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from aiogram import Bot, Dispatcher
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types.web_app_info import WebAppInfo
from aiogram.filters import Command

from config import BOT_TOKEN, WEBAPP_URL
from database import (
    init_db, get_player, update_balance, 
    transfer_money, get_all_leaderboard, 
    set_balance, set_ban
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class PlayRequest(BaseModel):
    user_id: int
    username: str = None
    bet: float

class FarmRequest(BaseModel):
    user_id: int

class TransferRequest(BaseModel):
    sender_id: int
    target: str
    amount: float

@app.get("/api/user/{user_id}")
def api_get_user(user_id: int, username: str = None):
    return get_player(user_id, username)

@app.get("/api/leaderboard")
def api_leaderboard():
    return get_all_leaderboard()

@app.post("/api/transfer")
def api_transfer(req: TransferRequest):
    return transfer_money(req.sender_id, req.target, req.amount)

@app.post("/api/farm")
def api_farm(req: FarmRequest):
    p = get_player(req.user_id)
    if p["banned"] == 1:
        return {"error": "Аккаунт заблокирован"}
    new_bal = update_balance(req.user_id, 0.35, affect_casino=True)
    return {"status": "ok", "new_balance": new_bal, "earned": 0.35}

@app.post("/api/play/{game}")
def api_play_game(game: str, req: PlayRequest):
    p = get_player(req.user_id, req.username)
    if p["banned"] == 1:
        return {"error": "Ваш аккаунт заблокирован администратором", "balance": p["balance"]}
        
    bet = req.bet
    if bet <= 0 or p["balance"] < bet:
        return {"error": "Недостаточно средств", "balance": p["balance"]}

    win_amount = 0.0
    details = ""

    if game == "slots":
        syms = ["7", "BAR", "CHERRY", "LEMON", "DIAMOND"]
        r1, r2, r3 = random.choice(syms), random.choice(syms), random.choice(syms)
        if r1 == "7" and r2 == "7" and r3 == "7": win_amount = bet * 25
        elif r1 == r2 == r3: win_amount = bet * 10
        elif r1 == r2 or r2 == r3 or r1 == r3: win_amount = bet * 2
        details = f"{r1} | {r2} | {r3}"

    elif game == "coinflip":
        win = random.choice([True, False])
        if win: win_amount = bet * 1.95
        details = "Орел" if win else "Решка"

    elif game == "mines":
        win = random.random() < 0.45
        if win: win_amount = bet * 2.8
        details = "Успех" if win else "Подрыв"

    elif game == "crash":
        mult = round(1.0 + random.expovariate(0.8), 2)
        win = mult > 1.35
        if win: win_amount = bet * mult
        details = f"x{mult}"

    elif game == "plinko":
        mult = random.choice([0.2, 0.5, 1.0, 1.5, 3.0, 10.0])
        win_amount = bet * mult
        details = f"x{mult}"

    elif game == "tower":
        win = random.random() < 0.4
        if win: win_amount = bet * 3.1
        details = "Пройдено" if win else "Обвал"

    elif game == "bj":
        win = random.choice([True, False, False])
        if win: win_amount = bet * 2.0
        details = "Игрок" if win else "Дилер"

    elif game == "wheel":
        mult = random.choice([0, 0.5, 1.0, 2.0, 5.0])
        win_amount = bet * mult
        details = f"x{mult}"

    elif game == "hilo":
        win = random.choice([True, False])
        if win: win_amount = bet * 2.35
        details = "Угадал" if win else "Мимо"
    else:
        return {"error": "Неизвестная игра"}

    profit = win_amount - bet
    new_bal = update_balance(req.user_id, profit, affect_casino=True)
    
    return {
        "win": win_amount > 0,
        "payout": win_amount,
        "new_balance": new_bal,
        "details": details
    }

# --- TELEGRAM BOT И НАСТРОЙКА АДМИНКИ ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Твой персональный Telegram ID (доступ только у тебя)
ADMIN_ID = 5399819309

@dp.message(Command("start"))
async def cmd_start(message: Message):
    uname = message.from_user.username or message.from_user.first_name or "Player"
    p = get_player(message.from_user.id, uname)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕹 Открыть Aimatov Casino", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    await message.answer(
        f"🏛 <b>Aimatov Silver Group</b>\n\n"
        f"👤 Игрок: <b>{uname}</b>\n"
        f"💳 Ваш AIMA-ID: <code>{p['aima_id']}</code>\n"
        f"💰 Баланс: <b>{p['balance']:,.2f} ASG</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("❌ У вас нет доступа к этой команде.")
        
    leaders = get_all_leaderboard()
    text = (
        "👑 <b>АДМИН-ПАНЕЛЬ AIMATOV SILVER</b>\n\n"
        "<b>Команды управления:</b>\n"
        "• <code>/give ID СУММА</code> — начислить/списать\n"
        "• <code>/setbal ID СУММА</code> — установить баланс\n"
        "• <code>/casino СУММА</code> — установить баланс Банка Казино\n"
        "• <code>/ban ID</code> / <code>/unban ID</code> — бан/разбан\n\n"
        "📊 <b>Все участники в базе:</b>\n"
    )
    for i, u in enumerate(leaders, 1):
        status = "🚫" if u["banned"] else ("🏛" if u["is_casino"] else "👤")
        text += f"{i}. {status} <b>{u['username']}</b> (ID: <code>{u['user_id']}</code>) — {u['balance']:,.2f} ASG\n"
        
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer("Использование: <code>/give ID СУММА</code>", parse_mode="HTML")
    target, amount = parts[1], float(parts[2])
    if target.isdigit():
        new_b = update_balance(int(target), amount, affect_casino=False)
        await message.answer(f"✅ Баланс ID <code>{target}</code> изменен на {amount:,.2f}.\nТекущий: <b>{new_b:,.2f} ASG</b>", parse_mode="HTML")

@dp.message(Command("setbal"))
async def cmd_setbal(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer("Использование: <code>/setbal ID СУММА</code>", parse_mode="HTML")
    res = set_balance(parts[1], float(parts[2]))
    if res:
        await message.answer(f"✅ Для <b>{res[0]}</b> установлен баланс: <b>{res[1]:,.2f} ASG</b>", parse_mode="HTML")

@dp.message(Command("casino"))
async def cmd_casino_bal(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("Использование: <code>/casino СУММА</code>", parse_mode="HTML")
    res = set_balance(0, float(parts[1]))
    await message.answer(f"🏛 Баланс <b>Банка Казино</b> установлен на: <b>{res[1]:,.2f} ASG</b>", parse_mode="HTML")

@dp.message(Command("ban"))
async def cmd_ban_user(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("Использование: <code>/ban ID</code>", parse_mode="HTML")
    res = set_ban(parts[1], 1)
    if res:
        await message.answer(f"🚫 Игрок <b>{res[0]}</b> заблокирован!", parse_mode="HTML")

@dp.message(Command("unban"))
async def cmd_unban_user(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("Использование: <code>/unban ID</code>", parse_mode="HTML")
    res = set_ban(parts[1], 0)
    if res:
        await message.answer(f"✅ Игрок <b>{res[0]}</b> разблокирован!", parse_mode="HTML")

@app.on_event("startup")
async def on_startup():
    init_db()
    asyncio.create_task(dp.start_polling(bot))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
