import aiohttp
import jinja2
from aiohttp.web import Request  # <-- අලුතින් import කළ යුතුයි
from FileStream.config import Telegram
from FileStream.utils.database import Database
from FileStream.utils.human_readable import humanbytes

db = Database(Telegram.DATABASE_URL, Telegram.SESSION_NAME)

# function එක දැන් request එකත් බලාපොරොත්තු වෙනවා
async def render_page(db_id: str, request: Request):
    file_data = await db.get_file(db_id)
    
    # --- මෙතන තමයි ප්‍රධානම වෙනස ---
    # Server.URL භාවිතා කරනවා වෙනුවට, request එකෙන් URL එක නිවැරදිව සකසා ගැනීම
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.host
    src = f"{scheme}://{host}/dl/{file_data['_id']}"
    # ------------------------------------

    file_size = humanbytes(file_data['file_size'])
    file_name = file_data['file_name'].replace("_", " ")

    if str((file_data['mime_type']).split('/')[0].strip()) == 'video':
        template_file = "FileStream/template/play.html"
    else:
        template_file = "FileStream/template/dl.html"
        # ඔබගේ මුල් කේතයේ තිබූ aiohttp කොටස වෙනස්කම් නොමැතිවම ක්‍රියා කරයි
        async with aiohttp.ClientSession() as s:
            async with s.get(src) as u:
                file_size = humanbytes(int(u.headers.get('Content-Length')))

    with open(template_file, "r", encoding="utf-8") as f: # utf-8 encoding එකතු කිරීම වඩාත් සුදුසුයි
        template = jinja2.Template(f.read())

    return template.render(
        file_name=file_name,
        file_url=src,
        file_size=file_size
    )
