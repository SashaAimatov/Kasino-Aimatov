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
from database import init_db, get_player, update_balance

# --- НАСТРОЙКА FASTAPI ДЛЯ MINI APP ---
app = FastAPI()

# Открываем CORS, чтобы твой сайт на GitHub Pages мог делать запросы к Render
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class PlayRequest(BaseModel):
    user_id: int
    bet: float

class FarmRequest(BaseModel):
    user_id: int

# Получение данных пользователя для отображения в Mini App
@app.get("/api/user/{user_id}")
def api_get_user(user_id: int):
    p = get_player(user_id)
    return p

# Эндпоинт для фарма ASG
@app.post("/api/farm")
def api_farm(req: FarmRequest):
    new_bal = update_balance(req.user_id, 0.35)
    return {"status": "ok", "new_balance": new_bal, "earned": 0.35}

# Единый эндпоинт для всех 9 игр
@app.post("/api/play/{game}")
def api_play_game(game: str, req: PlayRequest):
    p = get_player(req.user_id)
    bet = req.bet
    
    if p["balance"] < bet:
        return {"error": "Недостаточно средств", "balance": p["balance"]}

    win_amount = 0
    details = ""

    if game == "slots":
        syms = ["7", "BAR", "CHERRY", "LEON", "DIAMOND"]
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
        if win: win_amount = bet * 2.8 # Возвращаем ставку + 1.8 выигрыш
        details = "Успех" if win else "Подрыв"

    elif game == "crash":
        mult = round(1.0 + random.expovariate(0.8), 2)
        win = mult > 1.3
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

    # Списываем ставку и начисляем выигрыш (win_amount уже включает тело ставки)
    profit = win_amount - bet
    new_bal = update_balance(req.user_id, profit)
    
    return {
        "win": win_amount > 0,
        "payout": win_amount,
        "new_balance": new_bal,
        "details": details
    }

# --- НАСТРОЙКА AIOGRAM (TELEGRAM BOT) ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    # При старте бот выдает кнопку, открывающую Mini App
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕹 Открыть казино (Mini App)", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    
    # Регистрируем пользователя в БД
    get_player(message.from_user.id, message.from_user.username or "Player")
    
    await message.answer(
        "Aimatov Silver Group\n\nЭкосистема активна. Запускай приложение:",
        reply_markup=kb
    )

# --- ЗАПУСК ВСЕГО ВМЕСТЕ ---
@app.on_event("startup")
async def on_startup():
    print("Инициализация базы данных...")
    init_db()
    print("Запуск Telegram-бота...")
    # Запускаем aiogram в фоновом режиме внутри FastAPI
    asyncio.create_task(dp.start_polling(bot))

if __name__ == "__main__":
    # Render привязывает приложение к порту из переменной $PORT, либо 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
