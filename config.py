import os

# Берем токен из переменных окружения (нужно будет добавить в Render)
BOT_TOKEN = os.getenv("BOT_TOKEN", "ТВОЙ_ТОКЕН")

# Ссылка на твой HTML сайт на GitHub Pages
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://ТВОЙ-ЛОГИН.github.io/ТВОЙ-РЕПОЗИТОРИЙ/")

# Render автоматически выдаст эту переменную при создании БД
DATABASE_URL = os.getenv("DATABASE_URL", "")
