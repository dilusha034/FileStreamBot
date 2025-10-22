import time
import math
import logging
import mimetypes
import traceback
import json
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
        # මෙතන request එක render_page function එකට pass කරනවා
        return web.Response(text=await render_page(path, request), content_type='text/html')
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)

# --- අවසානම සහ ස්ථිරම උපසිරැසි ලබා දීමේ Route එක ---
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
            'ffprobe',
            '-v', 'error',
            '-print_format', 'json',
            '-show_streams',
            '-select_streams', 's',
            'pipe:0'
        ]
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # --- **මෙන්න ප්‍රධානම වෙනස්කම** ---
        # ffprobe එකට යවන දත්ත ප්‍රමාණය 50MB දක්වා වැඩි කිරීම
        total_data_to_pipe = 50 * 1024 * 1024
        
        chunk_size = 1024 * 1024
        parts = math.ceil(total_data_to_pipe / chunk_size)
        
        offset = 0
        piped_data = 0
        file_stream = tg_connect.yield_file(file_id, index, offset, 0, 0, parts, chunk_size)

        try:
            async for chunk in file_stream:
                if process.stdin.is_closing() or piped_data >= total_data_to_pipe:
                    break
                process.stdin.write(chunk)
                await process.stdin.drain()
                piped_data += len(chunk)
        except BrokenPipeError:
            logging.warning("BrokenPipeError: FFprobe closed the pipe early (this is often normal).")
            pass
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            if not process.stdin.is_closing():
                process.stdin.close()

        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_message = stderr.decode().strip()
            logging.error(f"FFprobe error: {error_message}")
            return web.json_response({"error": f"FFprobe failed: {error_message}"}, status=500)

        if not stdout:
            logging.warning("FFprobe returned no stdout. No subtitles found or error during probe.")
            return web.json_response([])

        subtitles_data = json.loads(stdout)
        return web.json_response(subtitles_data.get('streams', []))

    except Exception as e:
        error_trace = traceback.format_exc()
        logging.error(f"Subtitle probing failed critically: {e}\n{error_trace}")
        return web.json_response({"error": f"Server exception: {str(e)}"}, status=500)

# --- උපසිරැසි පථය (Subtitle Track) ලබා දීමේ නව Route එක ---
# FileStream/server/stream_routes.py ගොනුවට මෙය එක් කරන්න

@routes.get("/subtitle/{db_id}/{index}")
async def subtitle_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        stream_index = request.match_info['index']

        # Download එක සඳහා වේගවත්ම client තෝරා ගැනීම
        work_load_index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[work_load_index]
        
        tg_connect = class_cache.get(faster_client)
        if not tg_connect:
            tg_connect = utils.ByteStreamer(faster_client)
            class_cache[faster_client] = tg_connect

        file_id = await tg_connect.get_file_properties(db_id, multi_clients)
        
        # FFmpeg විධානය: නිශ්චිත උපසිරැසි පථය ගෙන එය VTT බවට පරිවර්තනය කිරීම
        command = [
            "ffmpeg",
            "-i", "pipe:0",               # Input එක stdin (standard input) වෙතින් ලබාගන්න
            "-map", f"0:{stream_index}",  # ලබාදුන් index එකට අදාල stream එක තෝරන්න
            "-f", "webvtt",               # ආකෘතිය WebVTT ලෙස සකසන්න
            "-",                          # Output එක stdout (standard output) වෙත යවන්න
            "-loglevel", "error"          # දෝෂ පමණක් ලොග් කරන්න
        ]

        # ffmpeg ක්‍රියාවලිය ආරම්භ කිරීම
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Streaming response එකක් සැකසීම
        response = web.StreamResponse(
            headers={ "Content-Type": "text/vtt", "Cache-Control": "max-age=3600" }
        )
        await response.prepare(request)
        
        # එකවර ක්‍රියාත්මක වන කාර්යයන් දෙකක්:
        # 1. ටෙලිග්‍රෑම් වෙතින් වීඩියෝව ffmpeg වෙත stream කිරීම
        # 2. ffmpeg වෙතින් එන VTT උපසිරැසිය client (browser) වෙත stream කිරීම
        
        async def stream_video_to_ffmpeg():
            file_stream = tg_connect.yield_file(file_id, work_load_index, 0, 0, 0, 0, 1024*1024)
            try:
                async for chunk in file_stream:
                    if process.stdin.is_closing(): break
                    try:
                        process.stdin.write(chunk)
                        await process.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        break
            except (asyncio.CancelledError, ConnectionResetError):
                pass
            finally:
                if not process.stdin.is_closing():
                    process.stdin.close()

        async def stream_subtitle_to_client():
            try:
                while not process.stdout.at_eof():
                    chunk = await process.stdout.read(1024)
                    if not chunk: break
                    try:
                        await response.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        break
            except (asyncio.CancelledError, ConnectionResetError):
                pass

        await asyncio.gather(stream_video_to_ffmpeg(), stream_subtitle_to_client())

        await process.wait()
        return response

    except Exception:
        logging.error(f"Subtitle handler failed critically: {traceback.format_exc()}")
        raise web.HTTPInternalServerError(text="Failed to process subtitle.")

# FileStream/server/stream_routes.py ගොනුවට මෙය යොදන්න
@routes.get("/dl/{path}", allow_head=True)
async def download_handler(request: web.Request):
    try:
        db_id = request.match_info["path"]
        
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]
        tg_connect = class_cache.get(faster_client)
        if not tg_connect:
            tg_connect = utils.ByteStreamer(faster_client)
            class_cache[faster_client] = tg_connect
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)

        file_name = utils.get_name(file_id)
        file_size = file_id.file_size
        mime_type = file_id.mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"

        range_header = request.headers.get("Range")
        
        response = web.StreamResponse(
            headers={ "Content-Type": mime_type, "Accept-Ranges": "bytes" }
        )

        from_bytes = 0
        until_bytes = file_size -1

        if range_header:
            try:
                from_bytes_str, until_bytes_str = range_header.replace("bytes=", "").split("-")
                from_bytes = int(from_bytes_str)
                until_bytes = int(until_bytes_str) if until_bytes_str else file_size - 1
                
                if (until_bytes >= file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
                    raise ValueError
                
                response.set_status(206)
                response.headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
            
            except (ValueError, IndexError):
                return web.Response(status=416, text="416: Range Not Satisfiable")
        else:
            response.set_status(200)

        req_length = (until_bytes - from_bytes) + 1
        response.headers["Content-Length"] = str(req_length)

        # --- මෙන්න අවසානම සහ නිවැරදිම ගණනය කිරීම ---
        # ඔබගේ yield_file function එකට ගැළපෙන ලෙස parameters සකස් කිරීම
        chunk_size = 1024 * 1024
        offset = from_bytes - (from_bytes % chunk_size)
        first_part_cut = from_bytes - offset
        last_part_cut = (until_bytes % chunk_size) + 1 if until_bytes % chunk_size != 0 else chunk_size
        part_count = math.ceil((until_bytes - offset + 1) / chunk_size)
        # -----------------------------------------------

        # --- Streaming ක්‍රියාවලිය ---
        await response.prepare(request)
        
        file_stream = tg_connect.yield_file(
            file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
        )

        streamed_bytes = 0
        try:
            async for chunk in file_stream:
                if streamed_bytes + len(chunk) > req_length:
                    chunk = chunk[:req_length - streamed_bytes]
                
                await response.write(chunk)
                streamed_bytes += len(chunk)

                if streamed_bytes >= req_length:
                    break
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        
        return response

    except FIleNotFound as e:
        raise web.HTTPNotFound(text=str(e))
    except Exception:
        logging.error(f"Download handler critical error: {traceback.format_exc()}")
        raise web.HTTPInternalServerError()
