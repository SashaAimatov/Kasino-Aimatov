import asyncio
import math
import random
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

import config
import database as db

app = FastAPI()

# Разрешаем запросы с твоего GitHub Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(bot)

# ================= ТЕЛЕГРАМ БОТ =================

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    player = db.get_or_create_player(message.from_user.id, message.from_user.first_name)
    if player["is_banned"]:
        await message.answer("🚫 Ваш аккаунт заблокирован службой безопасности Aimatov Silver Group.")
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
    await message.answer(text, reply_markup=markup, parse_mode="HTML")

@dp.message_handler(commands=['admin'])
async def cmd_admin(message: types.Message):
    if message.from_user.id != config.ADMIN_ID:
        return
    bank = db.get_casino_bank()
    text = (
        f"👑 <b>АДМИН-ПАНЕЛЬ AIMATOV SILVER</b>\n"
        f"🏦 Банк казино: <b>{bank:,.2f} ASG</b>\n\n"
        f"• <code>/give ID СУММА</code> — начислить / списать\n"
        f"• <code>/setbal ID СУММА</code> — установить баланс\n"
        f"• <code>/casino СУММА</code> — установить банк казино\n"
        f"• <code>/ban ID</code> / <code>/unban ID</code> — бан (по AIMA-ID или TG ID)"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message_handler(commands=['casino'])
async def cmd_casino(message: types.Message):
    if message.from_user.id != config.ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("⚠️ Формат: <code>/casino СУММА</code>", parse_mode="HTML")
        return
    try:
        amount = float(args[1])
        db.set_casino_bank(amount)
        await message.answer(f"🏛 Баланс Банка Казино успешно установлен на: <b>{amount:,.2f} ASG</b>", parse_mode="HTML")
    except ValueError:
        await message.answer("⚠️ Ошибка: введите число.")

@dp.message_handler(commands=['give', 'setbal', 'set'])
async def cmd_balance_ops(message: types.Message):
    if message.from_user.id != config.ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("⚠️ Формат: <code>/give AIMA-ID СУММА</code> или <code>/setbal AIMA-ID СУММА</code>", parse_mode="HTML")
        return
        
    cmd = args[0].lower()
    target = args[1].strip()
    try:
        amount = float(args[2])
    except ValueError:
        await message.answer("⚠️ Сумма должна быть числом.")
        return

    mode = "give" if cmd == "/give" else "set"
    ok = db.update_balance_by_target(target, amount, mode=mode)
    if ok:
        action_str = "изменен на" if mode == "give" else "установлен на"
        await message.answer(f"✅ Баланс игрока <code>{target}</code> {action_str} <b>{amount:,.2f} ASG</b>", parse_mode="HTML")
    else:
        await message.answer(f"❌ Игрок с ID <code>{target}</code> не найден в базе.", parse_mode="HTML")

@dp.message_handler(commands=['ban', 'unban'])
async def cmd_ban_ops(message: types.Message):
    if message.from_user.id != config.ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("⚠️ Формат: <code>/ban ID</code>", parse_mode="HTML")
        return
    is_ban = (args[0].lower() == '/ban')
    target = args[1].strip()
    if db.set_ban_status(target, is_ban):
        status = "заблокирован 🚫" if is_ban else "разблокирован ✅"
        await message.answer(f"Игрок <code>{target}</code> {status}", parse_mode="HTML")
    else:
        await message.answer("❌ Игрок не найден.")

# ================= FASTAPI СЕРВЕР ИГР =================

class UserReq(BaseModel):
    user_id: int
    username: str = "Player"

class BetReq(BaseModel):
    user_id: int
    bet: float
    game: str  # 'slots', 'crash', 'dice'
    choice: str = ""

class ClickMineReq(BaseModel):
    user_id: int
    clicks: int

@app.on_event("startup")
async def on_startup():
    db.init_db()
    asyncio.create_task(dp.start_polling())

@app.get("/")
async def root():
    return {"status": "Aimatov Silver Casino Server Running"}

@app.post("/api/user")
async def api_user(req: UserReq):
    p = db.get_or_create_player(req.user_id, req.username)
    if p["is_banned"]:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")
    now = int(time.time())
    elapsed = min(max(0, now - p["last_collect"]), 43200)
    pending_collector = math.floor(elapsed * (p["collector_level"] * 2.0))
    return {
        "aima_id": p["aima_id"],
        "balance": p["balance"],
        "collector_level": p["collector_level"],
        "pending_collector": pending_collector,
        "casino_bank": db.get_casino_bank()
    }

@app.post("/api/play")
async def api_play(req: BetReq):
    p = db.get_or_create_player(req.user_id)
    if p["is_banned"]:
        raise HTTPException(status_code=403, detail="Бан")
    
    bet = math.ceil(req.bet) # Округление ставки вверх в пользу казино
    if bet <= 0 or bet > p["balance"]:
        raise HTTPException(status_code=400, detail="Некорректная ставка")

    casino_bank = db.get_casino_bank()
    # Лимит выплаты: нельзя выиграть больше 3% от банка казино за раз (невозможно обанкротить)
    max_allowed_payout = math.floor(casino_bank * 0.03)

    roll = random.random()
    multiplier = 0.0
    details = {}

    if req.game == "slots":
        symbols = ["🍒", "🍋", "🔔", "💎", "7️⃣"]
        # House Edge: 68% проигрыш, 22% мелкий возврат (Near-miss эффект), 8% выигрыш, 2% джекпот
        if roll < 0.68:
            # Генерируем "почти выиграл" (2 одинаковых символа из 3) для вызова азарта
            s1 = random.choice(symbols)
            s2 = s1 if random.random() < 0.65 else random.choice(symbols)
            s3 = random.choice([x for x in symbols if x != s1])
            details["reels"] = [s1, s2, s3]
            multiplier = 0.0
        elif roll < 0.90:
            s = random.choice(["🍒", "🍋"])
            details["reels"] = [s, s, "🔔"]
            multiplier = 1.25
        elif roll < 0.98:
            s = random.choice(["🔔", "💎"])
            details["reels"] = [s, s, s]
            multiplier = 2.4
        else:
            details["reels"] = ["7️⃣", "7️⃣", "7️⃣"]
            multiplier = 5.0

    elif req.game == "dice":
        # Игра Больше/Меньше (шанс победы 34%, множитель 2.1x)
        is_win = roll < 0.34
        dice_num = random.randint(4, 6) if (is_win and req.choice == "high") or (not is_win and req.choice == "low") else random.randint(1, 3)
        details["dice"] = dice_num
        multiplier = 2.1 if is_win else 0.0

    elif req.game == "crash":
        # Ракета/Краш: 32% мгновенный слив на 1.00x, иначе осторожный икс
        target = float(req.choice) if req.choice else 2.0
        target = max(1.1, min(target, 10.0))
        # Реальный шанс пробить икс занижен на 15% в пользу казино
        win_prob = (0.85 / target)
        if roll < win_prob:
            crash_point = round(target + random.uniform(0.05, 1.2), 2)
            multiplier = target
        else:
            crash_point = round(random.uniform(1.00, max(1.01, target - 0.05)), 2)
            multiplier = 0.0
        details["crash_point"] = crash_point

    # Округление выигрыша строго ВНИЗ в пользу казино
    raw_win = math.floor(bet * multiplier)
    win_amount = min(raw_win, max_allowed_payout) if raw_win > 0 else 0

    net_change = win_amount - bet
    new_balance = db.adjust_player_balance(req.user_id, net_change)
    db.update_casino_bank(-net_change) # Проигрыш идет в банк казино, выигрыш списывается

    return {
        "win": win_amount,
        "multiplier": round(multiplier, 2),
        "balance": new_balance,
        "details": details
    }

@app.post("/api/mine_click")
async def api_mine_click(req: ClickMineReq):
    clicks = max(1, min(req.clicks, 50))
    raw_mined = clicks * 5.0  # 5 ASG за клик
    
    # Налог 10-30% в пользу казино с округлением налога ВВЕРХ
    tax_rate = random.uniform(0.10, 0.30)
    tax = math.ceil(raw_mined * tax_rate)
    net_profit = math.floor(raw_mined - tax)
    
    new_bal = db.adjust_player_balance(req.user_id, net_profit)
    db.update_casino_bank(tax)
    
    return {
        "net": net_profit,
        "tax": tax,
        "tax_percent": int(round(tax_rate * 100)),
        "balance": new_bal
    }

@app.post("/api/collector_claim")
async def api_collector_claim(req: UserReq):
    res = db.collect_passive_income(req.user_id)
    if not res or "error" in res:
        raise HTTPException(status_code=400, detail=res.get("error", "Ошибка сбора"))
    return res

@app.post("/api/collector_upgrade")
async def api_collector_upgrade(req: UserReq):
    res = db.upgrade_collector(req.user_id)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res
