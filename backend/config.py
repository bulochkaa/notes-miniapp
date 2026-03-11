import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str   = os.getenv("BOT_TOKEN", "")
GROUP_ID: int    = int(os.getenv("GROUP_ID", "0"))
MINIAPP_URL: str = os.getenv("MINIAPP_URL", "")   # e.g. https://yoursite.com/app
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")   # e.g. https://yoursite.com/webhook
ALLOWED_USERS: list[int] = [
    int(x.strip())
    for x in os.getenv("ALLOWED_USERS", "").split(",")
    if x.strip().isdigit()
]

TOPICS: dict[str, int] = {
    "🎬 Фильмы":          2,
    "🍳 Рецепты":         3,
    "🎵 Музыка":          5,
    "🎁 Подарки":         6,
    "👕 Одежда":          9,
    "📍 Интересные места": 10,
}
