import os

# Без этих переменных приложение не запустится (так лучше, чем молча работать с пустым токеном)
BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://sashaaimatov.github.io/Cazino-/")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5399819309"))
# Только твой сайт на GitHub Pages может обращаться к API из браузера
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://sashaaimatov.github.io").split(",")
