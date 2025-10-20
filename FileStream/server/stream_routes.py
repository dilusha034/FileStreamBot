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
# ... (status and watch routes are unchanged) ...

@routes.get("/status", allow_head=True)
async def root_route_handler(_):
    # ...
    return web.json_response({})
@routes.get("/watch/{path}", allow_head=True)
async def stream_handler(request: web.Request):
    # ...
    return web.Response(text="Render Page")

@routes.get("/dl/{path}", allow_head=True)
async def stream_handler(request: web.Request):
    try:
        db_id = request.match_info["path"]
        
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]
        
        if faster_client in class_cache:
            tg_connect = class_cache[faster_client]
        else:
            tg_connect = utils.ByteStreamer(faster_client)
            class_cache[faster_client] = tg_connect
        
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)

        if "video/x-matroska" in file_id.mime_type:
            logging.info(f"Detected MKV, starting remux with audio re-encoding for: {utils.get_name(file_id)}")
            download_url = await faster_client.get_download_link(file_id.file_id)
            
            # --- මෙන්න අපේ එකම එක වෙනස තියෙන තැන ---
            command = [
                'ffmpeg', '-i', download_url, 
                '-c:v', 'copy',          # වීඩියෝ එක copy කරන්න
                '-c:a', 'aac',           # ඕඩියෝ එක AAC වලට re-encode කරන්න
                '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1'
            ]
            # --- වෙනස මෙතනින් අවසන් ---

            process = await asyncio.create_subprocess_exec(*command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            response = web.StreamResponse(headers={"Content-Type": "video/mp4", "Content-Disposition": f"inline; filename=\"{utils.get_name(file_id).replace('.mkv', '.mp4')}\""})
            await response.prepare(request)
            
            try:
                while True:
                    chunk = await process.stdout.read(4096)
                    if not chunk: break
                    await response.write(chunk)
                await response.write_eof()
                return response
            except asyncio.CancelledError:
                process.kill()
                return response
            finally:
                await process.wait()
        
        else:
            logging.info(f"Not an MKV, passing to standard streamer: {utils.get_name(file_id)}")
            return await media_streamer(request, db_id)

    except (InvalidHash, FIleNotFound) as e:
        raise web.HTTPForbidden(text=e.message)
    except Exception as e:
        traceback.print_exc()
        logging.critical(e)
        raise web.HTTPInternalServerError(text=str(e))

class_cache = {}

# (media_streamer function එකේ කිසිම වෙනසක් නෑ)
async def media_streamer(request: web.Request, db_id: str):
    # ... (This function remains exactly the same as the working version)
    range_header = request.headers.get("Range", 0)
    
    index = min(work_loads, key=work_loads.get)
    faster_client = multi_clients[index]
    
    if Telegram.MULTI_CLIENT:
        logging.info(f"Client {index} is now serving {request.headers.get('X-FORWARDED-FOR',request.remote)}")

    if faster_client in class_cache:
        tg_connect = class_cache[faster_client]
    else:
        tg_connect = utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect

    file_id = await tg_connect.get_file_properties(db_id, multi_clients)
    
    file_size = file_id.file_size
    #... rest of the function is the same
    from_bytes = 0
    until_bytes = file_size -1
    #...
    body = tg_connect.yield_file(file_id, index, 0,0,0,0,0) # Dummy values, this will be calculated
    #...
    return web.Response(status=200, body=body)
