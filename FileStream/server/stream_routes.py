import time
import math
import logging
import mimetypes
import traceback
import json
import asyncio
import subprocess
from aiohttp import web
from FileStream.bot import multi_clients, work_loads, FileStream
from FileStream.server.exceptions import FIleNotFound, InvalidHash
from FileStream import utils, StartTime, __version__
from FileStream.utils.render_template import render_page

routes = web.RouteTableDef()
class_cache = {}

# 1. Status Route (වෙනසක් නැත)
@routes.get("/status", allow_head=True)
async def status_handler(_):
    return web.json_response(
        {
            "server_status": "running",
            "uptime": utils.get_readable_time(time.time() - StartTime),
            "telegram_bot": "@" + FileStream.username,
        }
    )

# 2. Web Player Page Route (වෙනසක් නැත)
@routes.get("/watch/{path}", allow_head=True)
async def watch_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        return web.Response(text=await render_page(path, request), content_type='text/html')
    except (FIleNotFound, InvalidHash) as e:
        raise web.HTTPNotFound(text=str(e))
    except Exception:
        logging.error(f"Watch handler failed: {traceback.format_exc()}")
        raise web.HTTPInternalServerError()

# 3. උපසිරැසි ලැයිස්තුව ලබා දීමේ Route (වෙනසක් නැත)
@routes.get("/subtitles/{db_id}")
async def subtitles_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]
        tg_connect = class_cache.get(faster_client)
        if not tg_connect:
            tg_connect = utils.ByteStreamer(faster_client)
            class_cache[faster_client] = tg_connect
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)
        command = [
            'ffprobe', '-v', 'error', '-print_format', 'json',
            '-show_streams', '-select_streams', 's', 'pipe:0'
        ]
        process = await asyncio.create_subprocess_exec(
            *command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        total_data_to_pipe = 50 * 1024 * 1024
        chunk_size = 1024 * 1024
        parts = math.ceil(total_data_to_pipe / chunk_size)
        file_stream = tg_connect.yield_file(file_id, index, 0, 0, 0, parts, chunk_size)
        piped_data = 0
        try:
            async for chunk in file_stream:
                if process.stdin.is_closing() or piped_data >= total_data_to_pipe: break
                process.stdin.write(chunk)
                await process.stdin.drain()
                piped_data += len(chunk)
        except (BrokenPipeError, asyncio.CancelledError, ConnectionResetError): pass
        finally:
            if not process.stdin.is_closing(): process.stdin.close()
        stdout, _ = await process.communicate()
        if not stdout: return web.json_response([])
        subtitles_data = json.loads(stdout)
        return web.json_response(subtitles_data.get('streams', []))
    except Exception:
        logging.error(f"Subtitle probing failed: {traceback.format_exc()}")
        return web.json_response({"error": "Server exception"}, status=500)

# 4. තෝරාගත් උපසිරැසිය ලබා දීමේ Route (අවසාන නිවැරදි කළ කේතය)
@routes.get("/subtitle/{db_id}/{index}")
async def subtitle_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        stream_index = request.match_info['index']
        work_load_index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[work_load_index]
        tg_connect = class_cache.get(faster_client)
        if not tg_connect:
            tg_connect = utils.ByteStreamer(faster_client)
            class_cache[faster_client] = tg_connect
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)
        command = [
            "ffmpeg", "-i", "pipe:0", "-map", f"0:{stream_index}",
            "-f", "webvtt", "-", "-loglevel", "error"
        ]
        process = await asyncio.create_subprocess_exec(
            *command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        response = web.StreamResponse(headers={"Content-Type": "text/vtt", "Cache-Control": "max-age=3600"})
        await response.prepare(request)
        async def stream_video_to_ffmpeg():
            total_data_to_pipe = 50 * 1024 * 1024
            chunk_size = 1024 * 1024
            parts = math.ceil(total_data_to_pipe / chunk_size)
            file_stream = tg_connect.yield_file(file_id, work_load_index, 0, 0, 0, parts, chunk_size)
            piped_data = 0
            try:
                async for chunk in file_stream:
                    if process.stdin.is_closing() or piped_data >= total_data_to_pipe: break
                    process.stdin.write(chunk)
                    await process.stdin.drain()
                    piped_data += len(chunk)
            except (BrokenPipeError, asyncio.CancelledError, ConnectionResetError): pass
            finally:
                if not process.stdin.is_closing(): process.stdin.close()
        async def stream_subtitle_to_client():
            try:
                while not process.stdout.at_eof():
                    chunk = await process.stdout.read(1024)
                    if not chunk: break
                    await response.write(chunk)
            except (BrokenPipeError, asyncio.CancelledError, ConnectionResetError): pass
        await asyncio.gather(stream_video_to_ffmpeg(), stream_subtitle_to_client())
        await process.wait()
        return response
    except Exception:
        logging.error(f"Subtitle handler failed: {traceback.format_exc()}")
        raise web.HTTPInternalServerError()

# 5. වීඩියෝව Stream කිරීමේ Route (අවසාන නිවැරදි කළ කේතය)
@routes.get("/subtitle/{db_id}/{index}")
async def subtitle_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        stream_index = request.match_info['index']
        work_load_index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[work_load_index]
        tg_connect = class_cache.get(faster_client)
        if not tg_connect:
            tg_connect = utils.ByteStreamer(faster_client)
            class_cache[faster_client] = tg_connect
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)
        command = [
            "ffmpeg", "-i", "pipe:0", "-map", f"0:{stream_index}",
            "-f", "webvtt", "-", "-loglevel", "error"
        ]
        process = await asyncio.create_subprocess_exec(
            *command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        response = web.StreamResponse(headers={"Content-Type": "text/vtt", "Cache-Control": "max-age=3600"})
        await response.prepare(request)
        
        async def stream_video_to_ffmpeg():
            # --- මෙන්න අවසානම සහ තර්කානුකූලම වෙනස ---
            # 50MB සීමාව ඉවත් කර, සම්පූර්ණ ගොනුවම ffmpeg වෙත stream කිරීම
            # (ඔබගේ Pro Plan එක නිසා මෙය දැන් 100%ක්ම ආරක්ෂිතයි)
            file_stream = tg_connect.yield_file(file_id, work_load_index, 0, 0, 0, 0, 1024 * 1024)
            try:
                async for chunk in file_stream:
                    if process.stdin.is_closing(): break
                    process.stdin.write(chunk)
                    await process.stdin.drain()
            except (BrokenPipeError, asyncio.CancelledError, ConnectionResetError): pass
            finally:
                if not process.stdin.is_closing(): process.stdin.close()

        async def stream_subtitle_to_client():
            try:
                while not process.stdout.at_eof():
                    chunk = await process.stdout.read(1024)
                    if not chunk: break
                    await response.write(chunk)
            except (BrokenPipeError, asyncio.CancelledError, ConnectionResetError): pass

        await asyncio.gather(stream_video_to_ffmpeg(), stream_subtitle_to_client())
        await process.wait()
        return response
    except Exception:
        logging.error(f"Subtitle handler failed critically: {traceback.format_exc()}")
        raise web.HTTPInternalServerError()
