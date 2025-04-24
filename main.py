import os
import threading
from datetime import datetime, timedelta
import asyncio
import stripe
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

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
SUBSCRIPTION_PRICE_ID = os.getenv("STRIPE_SUBSCRIPTION_PRICE_ID")
ONE_TIME_PRICE_ID = os.getenv("STRIPE_ONE_TIME_PRICE_ID")
if not all([STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, SUBSCRIPTION_PRICE_ID, ONE_TIME_PRICE_ID]):
    raise RuntimeError("Stripe keys and price IDs must be set in .env")

# Инициализация Stripe
stripe.api_key = STRIPE_SECRET_KEY

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

# Создание страницы оплаты через Stripe
@app.post("/create-checkout-session")
async def create_checkout_session(session: CheckoutSession):
    if session.plan_type not in ("subscription", "one_time"):
        raise HTTPException(status_code=400, detail="Invalid plan_type")

    price_id = SUBSCRIPTION_PRICE_ID if session.plan_type == "subscription" else ONE_TIME_PRICE_ID
    mode = "subscription" if session.plan_type == "subscription" else "payment"

    stripe_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode=mode,
        success_url=f"{FRONTEND_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{FRONTEND_URL}/cancel",
        metadata={"user_id": session.user_id, "plan_type": session.plan_type}
    )

    # Сохраняем сессию в БД
    await db.checkout_sessions.insert_one({
        "_id": stripe_session.id,
        "user_id": session.user_id,
        "plan_type": session.plan_type,
        "created": datetime.now(VIENNA_TZ)
    })

    return {"url": stripe_session.url}

# Webhook Stripe
@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event['type'] == 'checkout.session.completed':
        sess = event['data']['object']
        session_id = sess['id']
        rec = await db.checkout_sessions.find_one({"_id": session_id})
        if rec:
            user_id = rec['user_id']
            plan = rec['plan_type']
            if plan == 'subscription':
                end = datetime.now(VIENNA_TZ) + timedelta(days=30)
                await db.subscriptions.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_active": True, "end_date": end.isoformat()}},
                    upsert=True
                )
            else:
                # Одиночная покупка, можно хранить отдельно
                await db.payments.insert_one({
                    "user_id": user_id,
                    "session_id": session_id,
                    "amount": sess['amount_total'],
                    "currency": sess['currency'],
                    "paid_at": datetime.now(VIENNA_TZ)
                })
    return {"status": "ok"}

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
