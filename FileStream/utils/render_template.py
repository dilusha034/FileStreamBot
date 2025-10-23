import aiohttp
from aiohttp.web import Request
from FileStream.config import Telegram
from FileStream.utils.database import Database
from FileStream.utils.human_readable import humanbytes
from FileStream.server.exceptions import FIleNotFound
import aiofiles

db = Database(Telegram.DATABASE_URL, Telegram.SESSION_NAME)

async def render_page(db_id: str, request: Request):
    file_data = await db.get_file(db_id)

    if not file_data:
        raise FIleNotFound

    file_name = file_data.get('file_name', 'Unknown File').replace("_", " ")
    file_size = humanbytes(file_data.get('file_size', 0))

    # Construct the download URL correctly
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.host
    dl_url = f"{scheme}://{host}/dl/{db_id}"

    try:
        async with aiofiles.open("FileStream/template/play.html", mode='r', encoding='utf-8') as f:
            html = await f.read()
    except FileNotFoundError:
        return "Template file not found"

    # Replace placeholders
    html = html.replace("{{file_name}}", file_name)
    html = html.replace("{{file_size}}", file_size)
    html = html.replace("{{dl_url}}", dl_url)

    return html
