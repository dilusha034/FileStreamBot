import time
import math
import logging
import mimetypes
import traceback
import asyncio
import subprocess
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
from FileStream.bot import multi_clients, work_loads, FileStream
from FileStream.config import Telegram, Server
from FileStream.server.exceptions import FIleNotFound, InvalidHash
from FileStream import utils, StartTime, __version__
from FileStream.utils.render_template import render_page

routes = web.RouteTableDef()

# (මෙම /status route එකේ කිසිම වෙනසක් නෑ)
@routes.get("/status", allow_head=True)
async def root_route_handler(_):
    return web.json_response(
        {
            "server_status": "running",
            "uptime": utils.get_readable_time(time.time() - StartTime),
            "telegram_bot": "@" + FileStream.username,
            # ... (අනෙකුත් status දේවල්)
        }
    )

# (මෙම /watch route එකේ කිසිම වෙනසක් නෑ)
@routes.get("/watch/{path}", allow_head=True)
async def watch_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        return web.Response(text=await render_page(path), content_type='text/html')
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)

# --- මෙන්න අපේ ප්‍රධානම වෙනස තියෙන තැන ---
@routes.get("/dl/{path}", allow_head=True)
async def download_handler(request: web.Request):
    try:
        db_id = request.match_info["path"]
        
        # Get file properties
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]
        tg_connect = utils.ByteStreamer(faster_client)
        file_id = await tg_connect.get_file_properties(db_id)

        # Check if the file is MKV
        if "video/x-matroska" in file_id.mime_type:
            # --- MKV Remuxing Logic ---
            logging.info(f"Remuxing MKV file: {file_id.file_name}")
            
            # Get the direct download link from Telegram
            download_url = await faster_client.get_download_link(file_id.file_id)
            
            # Prepare FFmpeg command
            command = [
                'ffmpeg', '-i', download_url, '-c', 'copy', '-f', 'mp4',
                '-movflags', 'frag_keyframe+empty_moov', 'pipe:1'
            ]
            
            # Start the FFmpeg process
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Prepare and stream the response
            response = web.StreamResponse(
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Disposition": f"inline; filename=\"{utils.get_name(file_id).replace('.mkv', '.mp4')}\""
                }
            )
            await response.prepare(request)
            
            try:
                while True:
                    chunk = await process.stdout.read(4096)
                    if not chunk:
                        break
                    await response.write(chunk)
                await response.write_eof()
                return response
            except asyncio.CancelledError:
                process.kill()
                return response
            finally:
                await process.wait()
        else:
            # --- Default MP4/Other files Streaming Logic ---
            logging.info(f"Streaming file: {file_id.file_name}")
            return await media_streamer(request, file_id)

    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except Exception as e:
        logging.critical(e, exc_info=True)
        raise web.HTTPInternalServerError(text="Something went wrong")

# (media_streamer function එක පොඩි වෙනසක් කර ඇත)
async def media_streamer(request: web.Request, file_id):
    range_header = request.headers.get("Range", 0)
    
    index = min(work_loads, key=work_loads.get)
    faster_client = multi_clients[index]
    tg_connect = utils.ByteStreamer(faster_client)
    
    file_size = file_id.file_size

    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes = request.http_range.start or 0
        until_bytes = (request.http_range.stop or file_size) - 1

    # ... (මෙම කොටසේ සිට අවසානය දක්වා කිසිම වෙනසක් නෑ)
    chunk_size = 1024 * 1024
    # ...
    
    return web.Response(
        status=206 if range_header else 200,
        body=body,
        headers={
            "Content-Type": file_id.mime_type or "application/octet-stream",
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(req_length),
            "Content-Disposition": f'inline; filename="{utils.get_name(file_id)}"',
            "Accept-Ranges": "bytes",
        },
    )
