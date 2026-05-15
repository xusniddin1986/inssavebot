"""
Telegram Media Downloader Bot - Main Entry Point
Production-ready, async, webhook-based bot for Render.com
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app import create_app
from config.settings import get_settings
from utils.logger import setup_logging

logger = logging.getLogger(__name__)


async def main():
    """Main entry point for the bot."""
    # Setup logging first
    setup_logging()
    
    settings = get_settings()
    logger.info(f"Starting {settings.BOT_NAME} v{settings.VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Webhook mode: {settings.USE_WEBHOOK}")
    
    # Create and run the application
    app = await create_app()
    
    try:
        await app.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        raise
    finally:
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())