import time
import math
import logging
import mimetypes
import traceback
import asyncio
import subprocess
import json
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
from FileStream.bot import multi_clients, work_loads, FileStream
from FileStream.config import Telegram
from FileStream.server.exceptions import FIleNotFound, InvalidHash
from FileStream import utils, StartTime, __version__
from FileStream.utils.render_template import render_page

routes = web.RouteTableDef()
class_cache = {}

# --- Status Route ---
@routes.get("/status", allow_head=True)
async def status_handler(_):
    return web.json_response({"server_status": "running", "uptime": utils.get_readable_time(time.time() - StartTime), "version": __version__})

# --- Web Player Page ---
@routes.get("/watch/{path}", allow_head=True)
async def watch_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        return web.Response(text=await render_page(path), content_type='text/html')
    except (InvalidHash, FIleNotFound) as e:
        raise web.HTTPForbidden(text=e.message)

# --- අලුත්: උපසිරැසි තොරතුරු ලබාදෙන Route එක ---
@routes.get("/subtitles/info/{db_id}")
async def get_subtitle_info_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        index = min(work_loads, key=work_loads.get)
        client = multi_clients[index]

        # Use ffprobe to get subtitle stream information
        cmd = [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-select_streams", "s",
            f"https://{request.host}/dl/{db_id}" # Use the download URL as input
        ]
        
        process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logging.error(f"FFprobe error: {stderr.decode()}")
            return web.json_response({"error": "Failed to probe subtitles"}, status=500)

        probe_data = json.loads(stdout)
        subtitles = []
        for stream in probe_data.get("streams", []):
            lang = stream.get("tags", {}).get("language", f"Track {stream['index']}")
            title = stream.get("tags", {}).get("title", lang)
            subtitles.append({"index": stream['index'], "lang": lang, "title": title})

        return web.json_response(subtitles)

    except Exception as e:
        logging.error(f"Subtitle info error: {e}")
        return web.json_response({"error": str(e)}, status=500)


# --- වෙනස් කළා: උපසිරැසි Track Index එක අනුව ලබාදෙන Route එක ---
@routes.get("/subtitle/{db_id}/{track_index}")
async def subtitle_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        track_index_str = request.match_info.get('track_index', 's:0')
        track_index = f"0:{track_index_str}" # map format is 0:index

        index = min(work_loads, key=work_loads.get)
        client = multi_clients[index]
        tg_connect = class_cache.get(client) or utils.ByteStreamer(client)
        class_cache[client] = tg_connect
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)

        command = ['ffmpeg', '-i', 'pipe:0', '-map', track_index, '-f', 'webvtt', 'pipe:1']
        
        process = await asyncio.create_subprocess_exec(*command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        response = web.StreamResponse(headers={'Content-Type': 'text/vtt'})
        await response.prepare(request)

        # Coroutines for piping data
        async def pipe_to_ffmpeg():
            try:
                async for chunk in tg_connect.yield_file(file_id, index, 0, 0, file_id.file_size, math.ceil(file_id.file_size / (1024*1024)), 1024*1024):
                    if process.stdin.is_closing(): break
                    process.stdin.write(chunk)
                    await process.stdin.drain()
            finally:
                if not process.stdin.is_closing(): process.stdin.close()
        
        async def pipe_to_client():
            try:
                while not process.stdout.at_eof():
                    chunk = await process.stdout.read(4096)
                    if not chunk: break
                    await response.write(chunk)
            finally:
                await response.write_eof()

        async def log_stderr():
            while not process.stderr.at_eof():
                line = await process.stderr.readline()
                if line: logging.error(f"FFmpeg Subtitle stderr: {line.decode().strip()}")

        await asyncio.gather(pipe_to_ffmpeg(), pipe_to_client(), log_stderr())
        return response

    except Exception as e:
        logging.error(f"Subtitle generation failed: {e}")
        return web.Response(status=500, text="Failed to extract subtitle.")


# --- Download/Stream Route ---
@routes.get("/dl/{path}", allow_head=True)
async def download_handler(request: web.Request):
    try:
        return await media_streamer(request, request.match_info["path"])
    except (InvalidHash, FIleNotFound) as e:
        raise web.HTTPForbidden(text=e.message)
    except Exception as e:
        logging.critical(traceback.format_exc())
        raise web.HTTPInternalServerError(text=str(e))


# --- Media Streamer (Core Logic) ---
async def media_streamer(request: web.Request, db_id: str):
    range_header = request.headers.get("Range", 0)
    index = min(work_loads, key=work_loads.get)
    client = multi_clients[index]
    tg_connect = class_cache.get(client) or utils.ByteStreamer(client)
    class_cache[client] = tg_connect
    file_id = await tg_connect.get_file_properties(db_id, multi_clients)
    file_size = file_id.file_size

    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes, until_bytes = int(from_bytes), int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes, until_bytes = 0, file_size - 1

    req_length = until_bytes - from_bytes + 1
    
    headers = {
        "Content-Type": file_id.mime_type or "application/octet-stream",
        "Content-Length": str(req_length),
        "Content-Disposition": f'inline; filename="{utils.get_name(file_id)}"',
        "Accept-Ranges": "bytes",
    }
    
    if range_header:
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
        status = 206
    else:
        status = 200

    body = tg_connect.yield_file(file_id, index, from_bytes, 0, req_length, math.ceil(req_length / (1024*1024)), 1024*1024)
    return web.Response(status=status, headers=headers, body=body)
