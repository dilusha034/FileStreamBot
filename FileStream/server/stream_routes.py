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

# --- Helper Functions ---
def get_tg_connect(index):
    client = multi_clients[index]
    if client not in class_cache:
        class_cache[client] = utils.ByteStreamer(client)
    return class_cache[client]

async def pipe_chunks(writer, chunk_generator):
    try:
        async for chunk in chunk_generator:
            if writer.is_closing(): break
            writer.write(chunk)
            await writer.drain()
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    finally:
        if not writer.is_closing():
            writer.close()

# --- Routes ---
@routes.get("/status", allow_head=True)
async def status_handler(_): return web.json_response({"server_status": "running", "version": __version__})

@routes.get("/watch/{path}", allow_head=True)
async def watch_handler(request: web.Request):
    try:
        return web.Response(text=await render_page(request.match_info["path"]), content_type='text/html')
    except (InvalidHash, FIleNotFound) as e:
        raise web.HTTPNotFound(text=e.message)

# --- Subtitle Routes (Operation Eagle Eye) ---
@routes.get("/subtitles/list/{db_id}")
async def list_subtitles_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        index = min(work_loads, key=work_loads.get)
        tg_connect = get_tg_connect(index)
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)
        
        ffprobe_cmd = ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', '-select_streams', 's', 'pipe:0']
        
        process = await asyncio.create_subprocess_exec(
            *ffprobe_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        # Correctly pipe the file stream to ffprobe
        chunk_generator = tg_connect.yield_file(file_id, index)
        await pipe_chunks(process.stdin, chunk_generator)

        stdout, stderr = await process.wait_for_exit(), await process.stderr.read()
        
        if process.returncode != 0:
            logging.error(f"FFprobe error: {stderr.decode().strip()}")
            return web.json_response([], status=500)
            
        info = json.loads(await process.stdout.read())
        subtitles = [
            {"index": s.get("index"), "map_index": i, "lang": s.get("tags", {}).get("language", f"Track {i}")}
            for i, s in enumerate(info.get("streams", []))
        ]
        
        return web.json_response(subtitles)

    except Exception as e:
        logging.error(f"Eagle Eye (Listing) Failed: {traceback.format_exc()}")
        return web.json_response([], status=500)

@routes.get("/subtitle/{db_id}/{track_index}")
async def subtitle_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        track_index = int(request.match_info['track_index'])
        index = min(work_loads, key=work_loads.get)
        tg_connect = get_tg_connect(index)
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)

        command = ['ffmpeg', '-i', 'pipe:0', '-map', f'0:s:{track_index}', '-f', 'webvtt', 'pipe:1']
        
        process = await asyncio.create_subprocess_exec(
            *command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        response = web.StreamResponse(headers={'Content-Type': 'text/vtt'})
        await response.prepare(request)

        await asyncio.gather(
            pipe_chunks(process.stdin, tg_connect.yield_file(file_id, index)),
            pipe_chunks(response, process.stdout),
            utils.log_stderr(process.stderr, "Subtitle Extraction")
        )
        return response

    except Exception as e:
        logging.error(f"Eagle Eye (Extraction) Failed: {traceback.format_exc()}")
        return web.Response(status=500, text="Failed to extract subtitle.")

# --- Main Download & Stream Route ---
@routes.get("/dl/{path}", allow_head=True)
async def download_handler(request: web.Request):
    try:
        db_id = request.match_info["path"]
        range_header = request.headers.get("Range", 0)
        index = min(work_loads, key=work_loads.get)
        tg_connect = get_tg_connect(index)
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)
        file_size = file_id.file_size
        
        if range_header:
            from_bytes, until_bytes = utils.parse_range_header(range_header, file_size)
        else:
            from_bytes, until_bytes = 0, file_size - 1

        if from_bytes > until_bytes or from_bytes < 0: return web.Response(status=416)

        headers = {
            "Content-Type": file_id.mime_type or "application/octet-stream",
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(until_bytes - from_bytes + 1),
            "Content-Disposition": f'inline; filename="{utils.get_name(file_id)}"',
            "Accept-Ranges": "bytes",
        }
        
        return web.Response(
            status=206, 
            headers=headers,
            body=tg_connect.yield_file_from_range(file_id, index, from_bytes, until_bytes - from_bytes + 1)
        )
    except (FIleNotFound, InvalidHash):
        raise web.HTTPNotFound
    except Exception:
        logging.error(traceback.format_exc())
        raise web.HTTPInternalServerError
