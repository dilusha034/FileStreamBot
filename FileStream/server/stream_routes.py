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

def get_tg_connect(index):
    faster_client = multi_clients[index]
    if faster_client in class_cache:
        return class_cache[faster_client]
    else:
        tg_connect = utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
        return tg_connect

@routes.get("/status", allow_head=True)
async def status_handler(_):
    return web.json_response({"server_status": "running", "version": __version__})

@routes.get("/watch/{path}", allow_head=True)
async def watch_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        return web.Response(text=await render_page(path), content_type='text/html')
    except (InvalidHash, FIleNotFound) as e:
        raise web.HTTPNotFound(text=e.message)

@routes.get("/subtitles/list/{db_id}")
async def list_subtitles_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        index = min(work_loads, key=work_loads.get)
        tg_connect = get_tg_connect(index)
        
        # We need the whole file to probe it, let's download it to memory
        file_data = await tg_connect.get_file_for_probe(db_id, multi_clients)
        if not file_data:
            return web.json_response([], status=404)

        ffprobe_cmd = [
            'ffprobe', '-v', 'error', '-print_format', 'json',
            '-show_streams', '-select_streams', 's', 'pipe:0'
        ]
        
        process = await asyncio.create_subprocess_exec(
            *ffprobe_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        stdout, stderr = await process.communicate(input=file_data)
        
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
        tg_connect = get_tg_connect(index)
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)

        command = [
            'ffmpeg', '-i', 'pipe:0',
            '-map', f'0:s:{track_index}',
            '-f', 'webvtt', 'pipe:1'
        ]
        
        process = await asyncio.create_subprocess_exec(
            *command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        response = web.StreamResponse(headers={'Content-Type': 'text/vtt'})
        await response.prepare(request)

        async def pipe_to_ffmpeg():
            try:
                async for chunk in tg_connect.yield_file(file_id, index):
                    if process.stdin.is_closing(): break
                    process.stdin.write(chunk)
                    await process.stdin.drain()
            finally:
                if not process.stdin.is_closing():
                    process.stdin.close()
        
        async def pipe_to_client():
            try:
                while not process.stdout.at_eof():
                    chunk = await process.stdout.read(4096)
                    if not chunk: break
                    await response.write(chunk)
            finally:
                pass
        
        async def log_stderr():
            while not process.stderr.at_eof():
                line = await process.stderr.readline()
                if line: logging.error(f"FFmpeg Subtitle stderr: {line.decode().strip()}")

        await asyncio.gather(pipe_to_ffmpeg(), pipe_to_client(), log_stderr())
        return response

    except Exception as e:
        logging.error(f"Subtitle generation failed for track {track_index}: {e}")
        return web.Response(status=500, text="Failed to extract subtitle.")


@routes.get("/dl/{path}", allow_head=True)
async def download_handler(request: web.Request):
    return await media_streamer(request, request.match_info["path"])

async def media_streamer(request: web.Request, db_id: str):
    range_header = request.headers.get("Range", 0)
    index = min(work_loads, key=work_loads.get)
    tg_connect = get_tg_connect(index)
    file_id = await tg_connect.get_file_properties(db_id, multi_clients)
    file_size = file_id.file_size
    
    if range_header:
        from_bytes, until_bytes = utils.parse_range_header(range_header, file_size)
    else:
        from_bytes, until_bytes = 0, file_size - 1

    if from_bytes > until_bytes or from_bytes < 0:
        return web.Response(status=416)

    req_length = until_bytes - from_bytes + 1
    
    headers = {
        "Content-Type": file_id.mime_type or "application/octet-stream",
        "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
        "Content-Length": str(req_length),
        "Content-Disposition": f'inline; filename="{utils.get_name(file_id)}"',
        "Accept-Ranges": "bytes",
    }
    
    return web.Response(
        status=206, 
        headers=headers,
        body=tg_connect.yield_file(file_id, index, from_bytes, until_bytes)
    )
