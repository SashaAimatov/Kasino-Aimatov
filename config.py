import os

# Секреты подтягиваются из вкладки Environment на Render
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://sashaaimatov.github.io/Cazino-/")

# Твой Telegram ID администратора
ADMIN_ID = 5399819309
