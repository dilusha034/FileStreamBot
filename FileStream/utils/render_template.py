import os
from aiohttp.web import Request
from FileStream.config import Telegram
from FileStream.utils.file_properties import get_file_ids
from FileStream.utils.human_readable import humanbytes

async def render_page(db_id: str, request: Request) -> str:
    """
    HTML ප්ලේයර් පිටුව සඳහා අවශ්‍ය දත්ත සකසා,
    URL එක HTTPS වලින් ජනනය කර HTML එක ආපසු ලබා දීම
    """
    file_id = await get_file_ids(db_id, Telegram.MULTI_CLIENT)
    
    file_name = file_id.file_name
    file_size = humanbytes(file_id.file_size)

    # --- මෙන්න ප්‍රධානම නිවැරදි කිරීම ---
    # request එකෙන් scheme (http/https) සහ host (domain name) එක ලබාගෙන
    # නිවැරදි සහ සම්පූර්ණ URL එක ජනනය කිරීම.
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.host
    file_url = f"{scheme}://{host}/dl/{db_id}"

    # play.html ගොනුව විවෘත කර දත්ත ආදේශ කිරීම
    # __file__ මගින් මෙම ගොනුව ඇති ස්ථානය නිවැරදිවම සොයාගනී
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "template", "play.html")
    
    with open(template_path, "r", encoding="utf-8") as template_file:
        template_content = template_file.read()

    # {{...}} placeholders වලට අදාළ අගයන් ආදේශ කිරීම
    rendered_html = template_content.replace("{{file_name}}", file_name)
    rendered_html = rendered_html.replace("{{file_size}}", file_size)
    rendered_html = rendered_html.replace("{{file_url}}", file_url)
    
    return rendered_html
