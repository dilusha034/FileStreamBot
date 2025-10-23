from aiohttp import web
from .stream_routes import routes

async def web_server():
    web_app = web.Application()
    web_app.add_routes(routes)
    return web_app
