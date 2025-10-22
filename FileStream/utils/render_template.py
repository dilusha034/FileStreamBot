# FileStream/server/stream_routes.py

@routes.get("/watch/{path}", allow_head=True)
async def watch_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        # මෙතන request එක render_page function එකට pass කරනවා
        return web.Response(text=await render_page(path, request), content_type='text/html')
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)```

### 2 වන කොටස: `render_template.py` ගොනුව නිවැරදි කිරීම

දැන් තමයි අපි ගැටළුවේ මුලටම ගිහින් `http://` URL එක ජනනය වීම නවත්වන්නේ. ඔබට `FileStream/utils/render_template.py` නමින් ගොනුවක් තිබිය යුතුයි. එහි ඇති `render_page` function එක සම්පූර්ණයෙන්ම පහත කේතයෙන් ප්‍රතිස්ථාපනය කරන්න.

**ක්‍රියාමාර්ගය:**
ඔබගේ `FileStream/utils/render_template.py` ගොනුවේ ඇති සම්පූර්ණ කේතය ඉවත් කර, ඒ වෙනුවට පහත කේතය ඇතුළත් කරන්න.

```python
# FileStream/utils/render_template.py ගොනුවට මෙම සම්පූර්ණ කේතය යොදන්න

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
