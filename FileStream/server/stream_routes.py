import time
import math
import logging
import json
import subprocess
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

# --- Status Route එක ---
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

# --- Web Player Page එක ---
@routes.get("/watch/{path}", allow_head=True)
async def watch_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        return web.Response(text=await render_page(path), content_type='text/html')
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)

# --- අපේ අලුත් Subtitle Route එක ---
@routes.get("/subtitle/{db_id}")
async def subtitle_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]

        tg_connect = class_cache.get(faster_client)
        if not tg_connect:
            tg_connect = utils.ByteStreamer(faster_client)
            class_cache[faster_client] = tg_connect
        
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)

        # ffmpeg command to extract the first subtitle track and convert to webvtt
        command = [
            'ffmpeg', '-i', 'pipe:0',
            '-map', '0:s:0',
            '-f', 'webvtt',
            'pipe:1'
        ]
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        response = web.StreamResponse(headers={'Content-Type': 'text/vtt'})
        await response.prepare(request)

        async def pipe_to_ffmpeg():
            try:
                async for chunk in tg_connect.yield_file(file_id, index, 0, 0, file_id.file_size, math.ceil(file_id.file_size / (1024*1024)), 1024*1024):
                    if process.stdin.is_closing(): break
                    process.stdin.write(chunk)
                    await process.stdin.drain()
            except (asyncio.CancelledError, ConnectionResetError):
                pass
            finally:
                if not process.stdin.is_closing():
                    process.stdin.close()

        async def pipe_to_client():
            try:
                while not process.stdout.at_eof():
                    chunk = await process.stdout.read(4096)
                    if not chunk: break
                    await response.write(chunk)
            except (asyncio.CancelledError, ConnectionResetError):
                pass
        
        async def log_stderr():
            while not process.stderr.at_eof():
                line = await process.stderr.readline()
                if line: logging.error(f"FFmpeg Subtitle stderr: {line.decode().strip()}")


        await asyncio.gather(pipe_to_ffmpeg(), pipe_to_client(), log_stderr())
        await response.write_eof()
        return response

    except Exception as e:
        logging.error(f"Subtitle generation failed: {e}")
        return web.Response(status=500, text="Failed to extract subtitle.")

# --- අපේ අලුත් Subtitle Routes දෙක ---
@routes.get("/subtitles/list/{db_id}")
async def list_subtitles_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]
        tg_connect = class_cache.get(faster_client) or utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect

        file_id = await tg_connect.get_file_properties(db_id, multi_clients)
        
        # Use ffprobe to get stream info as JSON
        ffprobe_cmd = ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', '-select_streams', 's', 'pipe:0']
        
        process = await asyncio.create_subprocess_exec(
            *ffprobe_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        # We need the first part of the file to probe it
        file_head = b""
        async for chunk in tg_connect.yield_file(file_id, index, offset=0, first_part_cut=0, last_part_cut=1024*1024, part_count=1, chunk_size=1024*1024):
            file_head += chunk

        stdout, stderr = await process.communicate(input=file_head)
        
        if process.returncode != 0:
            logging.error(f"FFprobe error: {stderr.decode()}")
            return web.json_response([], status=500)
            
        info = json.loads(stdout)
        subtitles = [
            {"index": s.get("index"), "map_index": i, "lang": s.get("tags", {}).get("language", f"Track {i}")}
            for i, s in enumerate(info.get("streams", []))
        ]
        
        return web.json_response(subtitles)

    except Exception as e:
        logging.error(f"Subtitle listing failed: {e}")
        return web.json_response([], status=500)

@routes.get("/subtitle/{db_id}/{track_index}")
async def subtitle_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        track_index = int(request.match_info['track_index'])
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]
        tg_connect = class_cache.get(faster_client) or utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
        
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)

        command = ['ffmpeg', '-i', 'pipe:0', '-map', f'0:s:{track_index}', '-f', 'webvtt', 'pipe:1']
        
        process = await asyncio.create_subprocess_exec(
            *command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        response = web.StreamResponse(headers={'Content-Type': 'text/vtt'})
        await response.prepare(request)

        async def pipe_to_ffmpeg():
            try:
                file_size = file_id.file_size
                part_count = math.ceil(file_size / (1024*1024))
                async for chunk in tg_connect.yield_file(file_id, index, 0, 0, file_size, part_count, 1024*1024):
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
        
        await asyncio.gather(pipe_to_ffmpeg(), pipe_to_client())
        return response

    except Exception as e:
        logging.error(f"Subtitle generation for track {track_index} failed: {e}")
        return web.Response(status=500, text="Failed to extract subtitle.")
    
# --- Video/File Download Route එක ---
@routes.get("/dl/{path}", allow_head=True)
async def download_handler(request: web.Request):
    try:
        return await media_streamer(request, request.match_info["path"])
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logging.critical(traceback.format_exc())
        raise web.HTTPInternalServerError(text=str(e))

# --- Media Streamer (Core Logic) ---
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
