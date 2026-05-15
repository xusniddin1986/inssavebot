import os


class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8760063277:AAHvL0in9A8BrXe17IlxZ1FmUM2rmuygNH8")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "8553997595"))
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "https://inssavebot.onrender.com")  # https://your-app.onrender.com
    PORT: int = int(os.getenv("PORT", "8080"))
    DATABASE_URL: str = os.getenv("DATABASE_URL", "bot_database.db")