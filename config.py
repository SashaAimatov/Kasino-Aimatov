import os

# Без этих переменных приложение не запустится (так лучше, чем молча работать с пустым токеном)
BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://sashaaimatov.github.io/Cazino-/")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5399819309"))  # твой Telegram ID
# Авторизация идёт по подписанному заголовку X-Init-Data (куки не используются),
# поэтому "*" безопасен. Можно сузить: ALLOWED_ORIGINS=https://sashaaimatov.github.io
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
