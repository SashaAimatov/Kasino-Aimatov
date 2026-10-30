import os

# Теперь токен и база данных берутся из секретных настроек сервера, а не из файла
BOT_TOKEN = os.getenv("BOT_TOKEN", "тут_мог_быть_дефолтный_токен_но_лучше_пусто")
DATABASE_URL = os.getenv("DATABASE_URL", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://kasino-aimatov.onrender.com")
