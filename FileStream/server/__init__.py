from aiohttp import web
from .stream_routes import routes

# This is the web_server function that your __main__.py is looking for.
async def web_server():
    web_app = web.Application()
    web_app.add_routes(routes)
    return web_app
