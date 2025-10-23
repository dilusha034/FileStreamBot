import asyncio
import logging
from aiohttp import web
from FileStream.bot import FileStream
from FileStream.server.stream_server import web_server
from FileStream.config import Telegram, Server

logging.basicConfig(level=logging.INFO, format='[%(asctime)s - %(levelname)s] - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    # Start the Pyrogram bot client
    await FileStream.start()
    bot_info = await FileStream.get_me()
    FileStream.username = bot_info.username
    logger.info(f"Bot started as @{FileStream.username}")

    # Start the aiohttp web server
    server = web.AppRunner(await web_server())
    await server.setup()
    
    # Use the PORT from environment variables provided by Railway
    port = Server.PORT
    await web.TCPSite(server, "0.0.0.0", port).start()
    logger.info(f"Web server started at http://0.0.0.0:{port}")

    # Keep the application running
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Service shutting down...")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
