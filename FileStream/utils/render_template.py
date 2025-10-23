import aiofiles
from aiohttp.web import Request
from FileStream.bot import multi_clients, work_loads
from FileStream.server.exceptions import FIleNotFound, InvalidHash
from FileStream import utils

async def render_page(db_id: str, request: Request) -> str:
    try:
        index = min(work_loads, key=work_loads.get)
        tg_connect = utils.ByteStreamer(multi_clients[index])
        file_id = await tg_connect.get_file_properties(db_id)
        
        file_name = utils.get_name(file_id)
        file_size = utils.get_readable_file_size(file_id.file_size)

        # --- මෙන්න අවසානම සහ ස්ථිරම විසඳුම ---
        # URL variable එකක් වෙනුවට, request එකෙන්ම URL එක ස්වයංක්‍රීයව සකස් කිරීම
        scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
        host = request.host
        dl_url = f"{scheme}://{host}/dl/{db_id}"

        async with aiofiles.open('FileStream/template/play.html', mode='r', encoding='utf-8') as f:
            html = await f.read()
        
        html = html.replace("{{file_name}}", file_name)
        html = html.replace("{{file_size}}", file_size)
        html = html.replace("{{dl_url}}", dl_url)
        
        return html
    except (FIleNotFound, InvalidHash) as e:
        raise e
