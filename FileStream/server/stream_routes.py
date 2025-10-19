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

@routes.get("/status", allow_head=True)
async def root_route_handler(_):
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

@routes.get("/watch/{path}", allow_head=True)
async def stream_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        return web.Response(text=await render_page(path), content_type='text/html')
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass

# --- මෙන්න අපේ අලුත් "Traffic Controller" ---
@routes.get("/dl/{path}", allow_head=True)
async def stream_handler(request: web.Request):
    try:
        db_id = request.match_info["path"]
        
        # 1. MKV ද කියා පරීක්ෂා කිරීමට File Properties ලබා ගැනීම
        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]
        
        if faster_client in class_cache:
            tg_connect = class_cache[faster_client]
        else:
            tg_connect = utils.ByteStreamer(faster_client)
            class_cache[faster_client] = tg_connect
        
        file_id = await tg_connect.get_file_properties(db_id, multi_clients)

        # 2. MKV නම්, FFmpeg ක්‍රියාවලියට යොමු කිරීම
        if "video/x-matroska" in file_id.mime_type:
            logging.info(f"Detected MKV, starting remux for: {utils.get_name(file_id)}")
            download_url = await faster_client.get_download_link(file_id.file_id)
            
            command = ['ffmpeg', '-i', download_url, '-c', 'copy', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']
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
        
        # 3. MKV නොවේ නම්, පරණ, වැඩ කරන ක්‍රමයටම යොමු කිරීම
        else:
            logging.info(f"Not an MKV, passing to standard streamer: {utils.get_name(file_id)}")
            return await media_streamer(request, db_id)

    except (InvalidHash, FIleNotFound) as e:
        raise web.HTTPForbidden(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        traceback.print_exc()
        logging.critical(e)
        raise web.HTTPInternalServerError(text=str(e))

class_cache = {}

# --- මෙම media_streamer function එකට කිසිම වෙනසක් කර නෑ! ---
async def media_streamer(request: web.Request, db_id: str):
    range_header = request.headers.get("Range", 0)
    
    index = min(work_loads, key=work_loads.get)
    faster_client = multi_clients[index]
    
    if Telegram.MULTI_CLIENT:
        logging.info(f"Client {index} is now serving {request.headers.get('X-FORWARDED-FOR',request.remote)}")

    if faster_client in class_cache:
        tg_connect = class_cache[faster_client]
        logging.debug(f"Using cached ByteStreamer object for client {index}")
    else:
        logging.debug(f"Creating new ByteStreamer object for client {index}")
        tg_connect = utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
    logging.debug("before calling get_file_properties")
    file_id = await tg_connect.get_file_properties(db_id, multi_clients)
    logging.debug("after calling get_file_properties")
    
    file_size = file_id.file_size

    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes = request.http_range.start or 0
        until_bytes = (request.http_range.stop or file_size) - 1

    if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(
            status=416,
            body="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = 1024 * 1024
    until_bytes = min(until_bytes, file_size - 1)

    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1

    req_length = until_bytes - from_bytes + 1
    part_count = math.ceil(until_bytes / chunk_size) - math.floor(offset / chunk_size)
    body = tg_connect.yield_file(
        file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
    )

    mime_type = file_id.mime_type
    file_name = utils.get_name(file_id)
    disposition = "inline" # Ensure it's inline for streaming

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
