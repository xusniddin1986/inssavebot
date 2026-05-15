"""
Application factory - creates and configures the bot application.
Handles webhook server, bot lifecycle, database, and cache.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import (
    SimpleRequestHandler,
    setup_application,
)

from config.settings import get_settings
from database.db import Database
from handlers import register_all_handlers
from middlewares.antiflood import AntiFloodMiddleware
from middlewares.logging import LoggingMiddleware
from middlewares.user import UserMiddleware
from utils.logger import setup_logging
from utils.scheduler import setup_scheduler

logger = logging.getLogger(__name__)
settings = get_settings()


class BotApplication:
    """Main bot application class."""

    def __init__(self):
        self.bot: Optional[Bot] = None
        self.dp: Optional[Dispatcher] = None
        self.runner: Optional[web.AppRunner] = None
        self.db: Optional[Database] = None
        self.scheduler = None

    async def setup_bot(self):
        """Initialize bot and dispatcher."""
        self.bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
                link_preview_is_disabled=False,
            ),
        )

        # Setup storage
        if settings.REDIS_URL:
            try:
                storage = RedisStorage.from_url(settings.REDIS_URL)
                logger.info("Using Redis storage for FSM")
            except Exception as e:
                logger.warning(f"Redis unavailable, falling back to memory: {e}")
                storage = MemoryStorage()
        else:
            storage = MemoryStorage()
            logger.info("Using memory storage for FSM")

        self.dp = Dispatcher(storage=storage)

        # Register middlewares
        self.dp.message.middleware(LoggingMiddleware())
        self.dp.message.middleware(UserMiddleware(self.db))
        self.dp.message.middleware(AntiFloodMiddleware(rate_limit=settings.RATE_LIMIT))
        self.dp.callback_query.middleware(LoggingMiddleware())
        self.dp.callback_query.middleware(UserMiddleware(self.db))

        # Register all handlers
        register_all_handlers(self.dp, self.db)

        logger.info("Bot and dispatcher configured successfully")

    async def setup_database(self):
        """Initialize database connection."""
        self.db = Database(settings.DATABASE_URL)
        await self.db.connect()
        await self.db.create_tables()
        logger.info("Database connected and tables created")

    async def setup_scheduler(self):
        """Initialize task scheduler."""
        self.scheduler = await setup_scheduler(self.bot, self.db)
        logger.info("Scheduler started")

    async def setup_webhook(self) -> web.Application:
        """Setup aiohttp webhook server."""
        app = web.Application()

        # Health check endpoints
        async def health_check(request):
            return web.Response(text="Bot is running", status=200)

        async def health_detail(request):
            bot_info = await self.bot.get_me()
            return web.json_response({
                "status": "ok",
                "bot": bot_info.username,
                "version": settings.VERSION,
                "environment": settings.ENVIRONMENT,
            })

        app.router.add_get("/", health_check)
        app.router.add_get("/health", health_detail)

        # Setup webhook handler
        webhook_handler = SimpleRequestHandler(
            dispatcher=self.dp,
            bot=self.bot,
            secret_token=settings.WEBHOOK_SECRET,
        )
        webhook_handler.register(app, path=settings.WEBHOOK_PATH)
        setup_application(app, self.dp, bot=self.bot)

        return app

    async def set_webhook(self):
        """Set webhook URL with Telegram."""
        webhook_url = f"{settings.WEBHOOK_URL}{settings.WEBHOOK_PATH}"
        await self.bot.set_webhook(
            url=webhook_url,
            secret_token=settings.WEBHOOK_SECRET,
            allowed_updates=self.dp.resolve_used_update_types(),
            drop_pending_updates=True,
        )
        logger.info(f"Webhook set to: {webhook_url}")

    async def delete_webhook(self):
        """Remove webhook from Telegram."""
        await self.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted")

    async def run(self):
        """Start the application."""
        if settings.USE_WEBHOOK:
            await self.run_webhook()
        else:
            await self.run_polling()

    async def run_webhook(self):
        """Run in webhook mode (for Render.com)."""
        app = await self.setup_webhook()
        await self.set_webhook()

        self.runner = web.AppRunner(app)
        await self.runner.setup()

        site = web.TCPSite(
            self.runner,
            host=settings.HOST,
            port=settings.PORT,
        )
        await site.start()
        logger.info(f"Webhook server started on {settings.HOST}:{settings.PORT}")

        # Keep running
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    async def run_polling(self):
        """Run in polling mode (for local development)."""
        await self.delete_webhook()
        logger.info("Starting polling mode...")
        await self.dp.start_polling(
            self.bot,
            allowed_updates=self.dp.resolve_used_update_types(),
            drop_pending_updates=True,
        )

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down...")

        if self.scheduler:
            self.scheduler.shutdown(wait=False)

        if settings.USE_WEBHOOK and self.bot:
            try:
                await self.delete_webhook()
            except Exception as e:
                logger.error(f"Error deleting webhook: {e}")

        if self.runner:
            await self.runner.cleanup()

        if self.db:
            await self.db.disconnect()

        if self.bot:
            await self.bot.session.close()

        logger.info("Shutdown complete")


async def create_app() -> BotApplication:
    """Factory function to create the bot application."""
    app = BotApplication()

    # Initialize components in order
    await app.setup_database()
    await app.setup_bot()
    await app.setup_scheduler()

    return app