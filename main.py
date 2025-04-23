from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

app = FastAPI()

# Разрешаем фронту (GitHub Pages) слать запросы к нашему API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # На проде лучше ограничить своим доменом!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Модель для приёма данных формы
class CheckoutSession(BaseModel):
    user_id: str
    username: Optional[str] = None
    first_name: Optional[str] = None
    plan_type: str

# Главная — просто проверка что backend жив
@app.get("/")
async def root():
    return {"msg": "Dreamcatcher backend online!"}

# Эндпоинт для создания платёжной сессии
@app.post("/create-checkout-session")
async def create_checkout_session(session: CheckoutSession):
    print(f"Запрос на оплату: user_id={session.user_id}, username={session.username}, план={session.plan_type}")

    # Тут будет твоя логика создания платёжной сессии (Portmone/WayForPay/Stripe)
    # Пока возвращаем тестовую ссылку (можно сразу редиректить!)
    fake_payment_url = f"https://your-pay-gateway.com/pay?user_id={session.user_id}&plan={session.plan_type}"
    return {"url": fake_payment_url}

# Эндпоинт для webhook-а от платёжки (сюда будет приходить уведомление об успешной оплате)
@app.post("/webhook")
async def payment_webhook(request: Request):
    data = await request.json()
    print("Webhook от платёжки:", data)
    # Здесь обработка платежа: отметить user_id как оплаченный в базе
    # ...
    return {"status": "ok"}

# Эндпоинт для проверки статуса подписки (будет обращаться бот или сайт)
@app.get("/check-access")
async def check_access(user_id: str):
    # Здесь будет логика проверки подписки пользователя (например, поиск в базе)
    # Пока возвращаем всегда True для теста
    print(f"Проверка подписки для user_id={user_id}")
    return {"active": True}
