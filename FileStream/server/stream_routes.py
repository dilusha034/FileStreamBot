import time, math, logging, mimetypes, traceback, json, asyncio, subprocess
from aiohttp import web
from FileStream.bot import multi_clients, work_loads, FileStream
from FileStream.server.exceptions import FIleNotFound, InvalidHash
from FileStream import utils, StartTime
from FileStream.utils.render_template import render_page

routes = web.RouteTableDef()
class_cache = {}

# 1. WATCH PAGE ROUTE
@routes.get("/watch/{path}", allow_head=True)
async def watch_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        return web.Response(text=await render_page(path, request), content_type='text/html')
    except (FIleNotFound, InvalidHash) as e: raise web.HTTPNotFound(text=str(e))

# 2. SUBTITLE LISTING ROUTE (The "Menu") - Uses FFprobe
@routes.get("/subtitles/{db_id}")
async def subtitles_handler(request: web.Request):
    try:
        db_id = request.match_info['db_id']
        index = min(work_loads, key=work_loads.get)
        tg_connect = utils.ByteStreamer(multi_clients[index])
        file_id = await tg_connect.get_file_properties(db_id)
        command = ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', '-select_streams', 's', 'pipe:0']
        process = await asyncio.create_subprocess_exec(*command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        file_stream = tg_connect.yield_file(file_id, index, 0, 0, 0, 0, 1024*1024)
        try:
            async for chunk in file_stream:
                if process.stdin.is_closing(): break
                await process.stdin.write(chunk)
        finally:
            if not process.stdin.is_closing(): process.stdin.close()
        stdout, _ = await process.communicate()
        if not stdout: return web.json_response([])
        return web.json_response(json.loads(stdout).get('streams', []))
    except Exception as e:
        logging.error(f"Subtitle Listing Failed: {e}")
        return web.json_response({"error": "Failed to list subtitles"}, status=500)

# 3. SUBTITLE EXTRACTION ROUTE (The "Food") - Uses FFmpeg
@routes.get("/subtitle/{db_id}/{index}")
async def subtitle_extraction_handler(request: web.Request):
    try:
        db_id, stream_index = request.match_info['db_id'], request.match_info['index']
        index = min(work_loads, key=work_loads.get)
        tg_connect = utils.ByteStreamer(multi_clients[index])
        file_id = await tg_connect.get_file_properties(db_id)
        command = ["ffmpeg", "-i", "pipe:0", "-map", f"0:{stream_index}", "-f", "webvtt", "-", "-loglevel", "error"]
        process = await asyncio.create_subprocess_exec(*command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        response = web.StreamResponse(headers={"Content-Type": "text/vtt; charset=utf-8"})
        await response.prepare(request)
        async def pipe_to_ffmpeg():
            file_stream = tg_connect.yield_file(file_id, index, 0, 0, 0, 0, 1024*1024)
            try:
                async for chunk in file_stream:
                    if process.stdin.is_closing(): break
                    await process.stdin.write(chunk)
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
        logging.error(f"Subtitle Extraction Failed: {e}")
        raise web.HTTPInternalServerError

# 4. DOWNLOAD/STREAM ROUTE
@routes.get("/dl/{path}", allow_head=True)
async def download_handler(request: web.Request):
    try:
        db_id = request.match_info["path"]
        index = min(work_loads, key=work_loads.get)
        tg_connect = utils.ByteStreamer(multi_clients[index])
        file_id = await tg_connect.get_file_properties(db_id)
        file_size, mime_type = file_id.file_size, file_id.mime_type or mimetypes.guess_type(utils.get_name(file_id))[0] or "application/octet-stream"
        range_header = request.headers.get("Range")
        if range_header:
            from_bytes, until_bytes = [int(x) for x in range_header.replace("bytes=", "").split("-") if x]
            until_bytes = until_bytes if until_bytes else file_size - 1
            response = web.StreamResponse(status=206, headers={'Content-Type': mime_type, 'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}', 'Content-Length': str(until_bytes - from_bytes + 1)})
        else:
            from_bytes = 0
            response = web.StreamResponse(status=200, headers={'Content-Type': mime_type, 'Content-Length': str(file_size)})
        await response.prepare(request)
        streamer = tg_connect.yield_file(file_id, index, from_bytes, 0, 0, 0, 1024 * 1024)
        async for chunk in streamer:
            try: await response.write(chunk)
            except (asyncio.CancelledError, ConnectionResetError): break
        return response
    except (FIleNotFound, InvalidHash) as e: raise web.HTTPNotFound(text=str(e))
    except Exception as e:
        logging.error(f"Download Handler Failed: {e}")
        raise web.HTTPInternalServerError()
