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
from FileStream import utils
from FileStream.utils.render_template import render_page

routes = web.RouteTableDef()
class_cache = {}

@routes.get("/status", allow_head=True)
async def status_handler(_):
    return web.json_response({"server_status": "running"})

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

# උපසිරැසි ලැයිස්තුව ලබා දෙන ස්ථානය
@routes.get("/subtitles/{db_id}")
async def subtitles_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]
        tg_connect = class_cache.get(faster_client) or utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)
        
        command = ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', '-select_streams', 's', 'pipe:0']
        process = await asyncio.create_subprocess_exec(*command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # --- ගැටළුවට හේතුව: ffprobe වෙත යොමු කරන්නේ වීඩියෝවේ මුල් 50MB පමණි ---
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

        stdout, stderr = await process.communicate()
        if process.returncode != 0: return web.json_response({"error": f"FFprobe failed: {stderr.decode()}"}, status=500)
        if not stdout: return web.json_response([])
        return web.json_response(json.loads(stdout).get('streams', []))
    except Exception:
        logging.error(f"Subtitle probing failed: {traceback.format_exc()}")
        return web.json_response({"error": "Server exception"}, status=500)

# තෝරාගත් උපසිරැසිය ලබා දෙන ස්ථානය
@routes.get("/subtitle/{db_id}/{index}")
async def subtitle_handler(request: web.Request):
    try:
        db_id, stream_index = request.match_info['db_id'], request.match_info['index']
        work_load_index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[work_load_index]
        tg_connect = class_cache.get(faster_client) or utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)
        
        command = ["ffmpeg", "-i", "pipe:0", "-map", f"0:{stream_index}", "-f", "webvtt", "-", "-loglevel", "error"]
        process = await asyncio.create_subprocess_exec(*command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        response = web.StreamResponse(headers={"Content-Type": "text/vtt; charset=utf-8", "Cache-Control": "max-age=3600"})
        await response.prepare(request)
        
        async def stream_video_to_ffmpeg():
            file_stream = tg_connect.yield_file(file_id, work_load_index, 0, 0, 0, 0, 1024 * 1024)
            try:
                async for chunk in file_stream:
                    if process.stdin.is_closing(): break
                    await process.stdin.write(chunk)
            except (BrokenPipeError, asyncio.CancelledError, ConnectionResetError): pass
            finally:
                if not process.stdin.is_closing(): process.stdin.close()
                
        async def stream_subtitle_to_client():
            try:
                while not process.stdout.at_eof():
                    chunk = await process.stdout.read(4096)
                    if not chunk: break
                    await response.write(chunk)
            except (BrokenPipeError, asyncio.CancelledError, ConnectionResetError): pass
            
        await asyncio.gather(stream_video_to_ffmpeg(), stream_subtitle_to_client())
        await process.wait()
        return response
    except Exception:
        logging.error(f"Subtitle handler failed: {traceback.format_exc()}")
        raise web.HTTPInternalServerError()

# වීඩියෝව Stream කරන ස්ථානය
@routes.get("/dl/{path}", allow_head=True)
async def download_handler(request: web.Request):
    try:
        db_id = request.match_info["path"]
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]
        tg_connect = class_cache.get(faster_client) or utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)
        file_size = file_id.file_size
        file_name = utils.get_name(file_id)
        mime_type = file_id.mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        range_header = request.headers.get("Range")
        from_bytes = 0
        if range_header:
            try:
                from_bytes_str, until_bytes_str = range_header.replace("bytes=", "").split("-")
                from_bytes = int(from_bytes_str)
                until_bytes = int(until_bytes_str) if until_bytes_str else file_size - 1
                if (until_bytes >= file_size) or (from_bytes < 0) or (from_bytes > until_bytes):
                    return web.Response(status=416, reason="Range Not Satisfiable")
                response_length = until_bytes - from_bytes + 1
                response = web.StreamResponse(status=206, headers={'Content-Type': mime_type, 'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}', 'Content-Length': str(response_length), 'Accept-Ranges': 'bytes'})
            except (ValueError, IndexError):
                return web.Response(status=416, reason="Range Not Satisfiable")
        else:
            response = web.StreamResponse(status=200, headers={'Content-Type': mime_type, 'Content-Length': str(file_size), 'Accept-Ranges': 'bytes'})
        
        await response.prepare(request)
        
        chunk_size = 1024 * 1024
        offset = from_bytes - (from_bytes % chunk_size)
        first_part_cut = from_bytes - offset
        
        req_length = (until_bytes - from_bytes) + 1 if range_header else file_size
        parts = math.ceil((req_length + first_part_cut) / chunk_size)
        last_part_cut = (req_length + first_part_cut) % chunk_size if parts > 1 else 0
        
        streamer = tg_connect.yield_file(file_id, index, offset, first_part_cut, last_part_cut, parts, chunk_size)
        
        try:
            async for chunk in streamer:
                await response.write(chunk)
        except (asyncio.CancelledError, ConnectionResetError): pass
        return response
    except FIleNotFound as e: raise web.HTTPNotFound(text=str(e))
    except Exception:
        logging.error(f"Download handler critical error: {traceback.format_exc()}")
        raise web.HTTPInternalServerError()
