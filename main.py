import os
import threading
from datetime import datetime, timedelta
import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, filters
from pytz import timezone
from dotenv import load_dotenv

VIENNA_TZ = timezone("Europe/Vienna")
# Загрузка настроек из .env
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI is not set in .env")

# MongoDB
mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["dreamcatcher"]

# Настройки
FRONTEND_URL = os.getenv("FRONTEND_URL") or "http://localhost:3000"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")

# FastAPI
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Модель запроса на оплату
class CheckoutSession(BaseModel):
    user_id: str
    plan_type: str  # "subscription" или "one_time"

# Корень
@app.get("/")
async def root():
    return {"msg": "Dreamcatcher backend online!"}

@app.post("/send-message")
async def send_message(user_id: str, message: str):
    try:
        await bot.send_message(chat_id=user_id, text=message)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Проверка доступа по подписке
@app.get("/check-access")
async def check_access(user_id: str):
    sub = await db.subscriptions.find_one({"user_id": user_id})
    if sub and sub.get("is_active") and sub.get("end_date") >= datetime.now(VIENNA_TZ).isoformat():
        return {"active": True}
    return {"active": False}

# Telegram-auth endpoint
@app.get("/telegram-auth")
async def telegram_auth(user_id: str, username: Optional[str] = None, first_name: Optional[str] = None):
    # Сохраняем или обновляем пользователя
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"username": username, "first_name": first_name}},
        upsert=True
    )
    return {"user_id": user_id, "username": username, "first_name": first_name}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
