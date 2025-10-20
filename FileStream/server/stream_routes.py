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
from FileStream.config import Telegram
from FileStream.server.exceptions import FIleNotFound, InvalidHash
from FileStream import utils, StartTime, __version__
from FileStream.utils.render_template import render_page

routes = web.RouteTableDef()
class_cache = {}

@routes.get("/status", allow_head=True)
async def status_handler(_):
    # ... (මෙම කොටස වෙනස් කර නැත) ...
    return web.json_response({
        "server_status": "running",
        "uptime": utils.get_readable_time(time.time() - StartTime),
        "telegram_bot": "@" + FileStream.username,
    })

@routes.get("/watch/{path}", allow_head=True)
async def watch_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        return web.Response(text=await render_page(path), content_type='text/html')
    except (FIleNotFound, InvalidHash) as e:
        raise web.HTTPNotFound(text=str(e))

@routes.get("/dl/{path}", allow_head=True)
async def download_handler(request: web.Request):
    # ... (මෙම කොටස බොහෝ දුරට සමානයි, නමුත් media_streamer වෙත යොමු කිරීම පමණි) ...
    try:
        db_id = request.match_info["path"]
        return await media_streamer(request, db_id)
    except (InvalidHash, FIleNotFound) as e:
        raise web.HTTPForbidden(text=str(e))
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logging.critical(f"Download handler error: {e}", exc_info=True)
        raise web.HTTPInternalServerError(text=str(e))

async def media_streamer(request: web.Request, db_id: str):
    range_header = request.headers.get("Range", 0)
    
    index = min(work_loads, key=work_loads.get)
    faster_client = multi_clients[index]
    
    if faster_client in class_cache:
        tg_connect = class_cache[faster_client]
    else:
        tg_connect = utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
        
    file_id = await tg_connect.get_file_properties(db_id, multi_clients)
    file_size = file_id.file_size

    if range_header:
        from_bytes, until_bytes = utils.get_range(range_header, file_size)
    else:
        from_bytes = 0
        until_bytes = file_size - 1

    if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(status=416)

    # MKV වැනි format සඳහා FFmpeg භාවිතා කිරීම
    if file_id.mime_type in ["video/x-matroska", "video/x-msvideo"]:
        # FFmpeg සඳහා stdin වෙත pipe කිරීමට stream එක ලබාගැනීම
        stream = tg_connect.yield_file(file_id, index, 0, 0, file_size, math.ceil(file_size / (1024*1024)), 1024*1024)
        
        command = [
            'ffmpeg', '-i', '-', '-c', 'copy', '-movflags', 
            'frag_keyframe+empty_moov', '-f', 'mp4', 'pipe:1'
        ]
        
        process = await asyncio.create_subprocess_exec(
            *command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        response = web.StreamResponse(headers={"Content-Type": "video/mp4"})
        await response.prepare(request)

        # දත්ත එකවර ffmpeg වෙත යැවීම සහ client වෙත ලබා දීම
        try:
            # ffmpeg වෙත දත්ත යැවීමේ task එක
            async def pipe_to_ffmpeg():
                try:
                    async for chunk in stream:
                        if process.stdin.is_closing(): break
                        process.stdin.write(chunk)
                        await process.stdin.drain()
                finally:
                    if not process.stdin.is_closing():
                        process.stdin.close()

            # client වෙත දත්ත යැවීමේ task එක
            async def pipe_to_client():
                while not process.stdout.at_eof():
                    chunk = await process.stdout.read(4096)
                    if not chunk: break
                    await response.write(chunk)
            
            await asyncio.gather(pipe_to_ffmpeg(), pipe_to_client())
            return response
        except (asyncio.CancelledError, ConnectionResetError):
            process.kill()
            return response
        finally:
            if process.returncode is None:
                process.kill()

    # අනෙකුත් file types සඳහා සාමාන්‍ය streaming ක්‍රමය
    else:
        req_length = until_bytes - from_bytes + 1
        body = tg_connect.yield_file(file_id, index, from_bytes, 0, req_length, math.ceil(req_length / (1024*1024)), 1024*1024)
        
        return web.Response(
            status=206 if range_header else 200,
            body=body,
            headers={
                "Content-Type": file_id.mime_type,
                "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
                "Content-Length": str(req_length),
                "Accept-Ranges": "bytes",
            }
        )

# --- උපසිරැසි සඳහා වන නව Route එක ---
@routes.get("/subtitle/{path}")
async def get_subtitle_as_vtt(request: web.Request):
    try:
        db_id = request.match_info['path']
        
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]

        tg_connect = class_cache.get(faster_client)
        if not tg_connect:
            tg_connect = utils.ByteStreamer(faster_client)
            class_cache[faster_client] = tg_connect
            
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)

        # FFmpeg command එක: පළමු subtitle stream එක webvtt බවට හරවන්න
        command = ['ffmpeg', '-i', '-', '-map', '0:s:0', '-f', 'webvtt', 'pipe:1']
        
        process = await asyncio.create_subprocess_exec(
            *command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        stream = tg_connect.yield_file(file_id, index, 0, 0, file_id.file_size, math.ceil(file_id.file_size / (1024*1024)), 1024*1024)

        # උපසිරැසි තිබේදැයි බැලීමට FFmpeg වෙතින් කුඩා දත්ත ප්‍රමාණයක් ලබාගැනීම
        # stdout වෙතින් පළමු දත්ත කොටස ලැබෙනතුරු බලා සිටීම
        try:
            first_chunk = await asyncio.wait_for(process.stdout.read(1024), timeout=5.0)
            if not first_chunk or b"Subtitle stream not found" in await process.stderr.read():
                 process.kill()
                 return web.Response(status=404, text="Subtitle Not Found")
        except asyncio.TimeoutError:
             process.kill()
             return web.Response(status=404, text="Subtitle Not Found (Timeout)")

        # උපසිරැසි තිබේ නම්, streaming ආරම්භ කිරීම
        response = web.StreamResponse(headers={'Content-Type': 'text/vtt', 'Charset': 'utf-8'})
        await response.prepare(request)
        await response.write(first_chunk) # පළමු chunk එක යැවීම

        # ඉතිරි ක්‍රියාවලිය සමාන්තරව ක්‍රියාත්මක කිරීම
        async def pipe_to_ffmpeg():
            try:
                async for chunk in stream:
                    if process.stdin.is_closing(): break
                    process.stdin.write(chunk)
                    await process.stdin.drain()
            finally:
                if not process.stdin.is_closing(): process.stdin.close()

        async def pipe_to_client():
            while not process.stdout.at_eof():
                chunk = await process.stdout.read(4096)
                if not chunk: break
                await response.write(chunk)
        
        try:
            await asyncio.gather(pipe_to_ffmpeg(), pipe_to_client())
            return response
        except (asyncio.CancelledError, ConnectionResetError):
            process.kill()
            return response

    except Exception as e:
        logging.error(f"Subtitle error: {e}", exc_info=True)
        return web.Response(status=500)
