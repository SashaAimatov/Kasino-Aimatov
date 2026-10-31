import os

# Без этих переменных приложение не запустится (так лучше, чем молча работать с пустым токеном)
BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://sashaaimatov.github.io/Cazino-/")
# Админ определяется по нику в Telegram (без @, регистр не важен)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "pampampa1").lstrip("@")
# Авторизация идёт по подписанному заголовку X-Init-Data (куки не используются),
# поэтому "*" безопасен. Можно сузить: ALLOWED_ORIGINS=https://sashaaimatov.github.io
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
