import time
import math
import json
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

# --- 1. Status Route එක ---
@routes.get("/status", allow_head=True)
async def status_handler(_):
    return web.json_response(
        {
            "server_status": "running",
            "uptime": utils.get_readable_time(time.time() - StartTime),
            "telegram_bot": "@" + FileStream.username,
            "connected_bots": len(multi_clients),
            "loads": dict(
                ("bot" + str(c + 1), l)
                for c, (_, l) in enumerate(
                    sorted(work_loads.items(), key=lambda x: x[1], reverse=True)
                )
            ),
            "version": __version__,
        }
    )

# --- 2. Web Player Page එක පෙන්වන Route එක (වෙනස් නමකින්) ---
@routes.get("/watch/{path}", allow_head=True)
async def watch_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        return web.Response(text=await render_page(path), content_type='text/html')
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass

# --- 3. වීඩියෝ දත්ත යවන Route එක (වෙනස් නමකින්) ---
@routes.get("/dl/{path}", allow_head=True)
async def download_handler(request: web.Request):
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

        remux_formats = ["video/x-matroska", "video/x-msvideo"]

        if file_id.mime_type in remux_formats:
            original_name = utils.get_name(file_id)
            new_name = original_name.rsplit('.', 1)[0] + ".mp4" if '.' in original_name else original_name + ".mp4"
            logging.info(f"Remuxing '{original_name}' to MP4 for streaming.")

            command = ['ffmpeg', '-i', '-', '-c', 'copy', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']
            
            process = await asyncio.create_subprocess_exec(*command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            response = web.StreamResponse(headers={"Content-Type": "video/mp4", "Content-Disposition": f"inline; filename=\"{new_name}\""})
            await response.prepare(request)

            try:
                async def pipe_to_ffmpeg():
                    try:
                        async for chunk in tg_connect.yield_file(file_id, index, 0, 0, file_id.file_size, math.ceil(file_id.file_size / (1024*1024)), 1024*1024):
                            if process.stdin.is_closing(): break
                            process.stdin.write(chunk)
                            await process.stdin.drain()
                    except (asyncio.CancelledError, ConnectionResetError): pass
                    finally:
                        if not process.stdin.is_closing(): process.stdin.close()
                
                async def pipe_to_client():
                    try:
                        while not process.stdout.at_eof():
                            chunk = await process.stdout.read(4096)
                            if not chunk: break
                            await response.write(chunk)
                    except (asyncio.CancelledError, ConnectionResetError): pass
                
                async def log_stderr():
                    while not process.stderr.at_eof():
                        line = await process.stderr.readline()
                        if line: logging.error(f"FFmpeg stderr: {line.decode().strip()}")

                await asyncio.gather(pipe_to_ffmpeg(), pipe_to_client(), log_stderr())
                await response.write_eof()
                return response
                
            except asyncio.CancelledError:
                process.kill()
                await process.wait()
                return response
            finally:
                if process.returncode is None: process.kill()
                await process.wait()
                logging.info(f"Remux for '{original_name}' finished with code {process.returncode}")

        else:
            logging.info(f"Passing '{utils.get_name(file_id)}' to standard streamer.")
            return await media_streamer(request, db_id)

    except (InvalidHash, FIleNotFound) as e:
        raise web.HTTPForbidden(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError): pass
    except Exception as e:
        traceback.print_exc()
        logging.critical(e)
        raise web.HTTPInternalServerError(text=str(e))

# --- 4. MP4 වැනි සාමාන්‍ය ගොනු සඳහා වන, වෙනස් නොකළ media_streamer function එක ---
async def media_streamer(request: web.Request, db_id: str):
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

    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes = request.http_range.start or 0
        until_bytes = (request.http_range.stop or file_size) - 1

    if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(status=416, body="416: Range not satisfiable", headers={"Content-Range": f"bytes */{file_size}"})

    chunk_size = 1024 * 1024
    until_bytes = min(until_bytes, file_size - 1)
    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1
    req_length = until_bytes - from_bytes + 1
    part_count = math.ceil(until_bytes / chunk_size) - math.floor(offset / chunk_size)
    body = tg_connect.yield_file(file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size)

    mime_type = file_id.mime_type
    file_name = utils.get_name(file_id)
    disposition = "inline"

    if not mime_type:
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

    return web.Response(
        status=206 if range_header else 200,
        body=body,
        headers={
            "Content-Type": f"{mime_type}",
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(req_length),
            "Content-Disposition": f'{disposition}; filename="{file_name}"',
            "Accept-Ranges": "bytes",
        },
    )

# --- 5 උපසිරැසි සඳහා වන අවසාන සහ නිවැරදි කරන ලද Route එක ---
@routes.get("/subtitle/{path}")
async def get_subtitle_as_vtt(request: web.Request):
    try:
        db_id = request.match_info['path']
        
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]

        if faster_client in class_cache:
            tg_connect = class_cache[faster_client]
        else:
            tg_connect = utils.ByteStreamer(faster_client)
            class_cache[faster_client] = tg_connect
            
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)

        # ffmpeg command එක: stdin වෙතින් input ලබාගෙන, 
        # පළමු උපසිරැසි stream එක webvtt format එකට convert කර stdout වෙත ලබා දෙන්න.
        command = [
            'ffmpeg', '-i', '-', '-map', '0:s:0', '-f', 'webvtt', '-'
        ]
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE # දෝෂ log කිරීමට
        )
        
        # ffmpeg ක්‍රියාවලියට වීඩියෝ දත්ත stream කිරීම සහ ප්‍රතිදානය ලබාගැනීම
        # මෙය සම්පූර්ණ ගොනුවම download නොකර සිදු කරයි
        stdout, stderr = await process.communicate(
            input=b''.join([
                chunk async for chunk in tg_connect.yield_file(file_id, index, 0, 0, file_id.file_size, math.ceil(file_id.file_size / (1024*1024)), 1024*1024)
            ])
        )

        if process.returncode != 0:
            # උපසිරැසි නොමැති වීම දෝෂයක් නොවේ, එය സാധാരണ දෙයක්
            if b"Subtitle stream not found" in stderr:
                logging.info(f"'{utils.get_name(file_id)}' ගොනුවේ උපසිරැසි නොමැත.")
                return web.Response(status=404, text="No Subtitles Found")
            else:
                logging.error(f"ffmpeg දෝෂය: {stderr.decode().strip()}")
                raise web.HTTPInternalServerError()
        
        # සාර්ථකව උපසිරැසි extract කල හොත්, VTT දත්ත response එක ලෙස යැවීම
        return web.Response(
            body=stdout,
            content_type="text/vtt",
            charset="utf-8"
        )

    except Exception as e:
        logging.error(f"get_subtitle_as_vtt හි දෝෂයක්: {e}")
        traceback.print_exc()
        return web.Response(status=500)
