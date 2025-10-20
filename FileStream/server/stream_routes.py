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

# --- 1. ඔබගේ මුල්, වැඩ කරමින් තිබුණු /status සහ /watch routes ---
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
        # මෙන්න මේ function එක තමයි ඔබගේ player page එක පෙන්නන්නේ
        return web.Response(text=await render_page(path), content_type='text/html')
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass

# --- 2. අපේ අලුත්, නිවැරදි කළ /dl route එක (Traffic Controller) ---
@routes.get("/dl/{path}", allow_head=True)
async def stream_handler(request: web.Request):
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

        # MKV, AVI වැනි web browser වලට සෘජුවම play කල නොහැකි format මෙහිදී හඳුනාගන්නවා
        remux_formats = ["video/x-matroska", "video/x-msvideo"] # ඔබට අවශ්‍ය අනෙකුත් format මෙතනට එකතු කරන්න (උදා: "video/avi")

        if file_id.mime_type in remux_formats:
            
            # ගොනුවේ නමෙන් .mkv හෝ .avi වැනි extension ඉවත් කර .mp4 එකතු කිරීම
            original_name = utils.get_name(file_id)
            new_name = original_name.rsplit('.', 1)[0] + ".mp4" if '.' in original_name else original_name + ".mp4"
            logging.info(f"Detected a non-streamable format ({file_id.mime_type}). Starting remux for: {original_name}")

            # FFmpeg command එක stdin (-) වෙතින් input ලබාගන්නා ලෙස සකස් කිරීම
            command = [
                'ffmpeg', '-i', '-', '-c', 'copy', '-f', 'mp4',
                '-movflags', 'frag_keyframe+empty_moov', 'pipe:1'
            ]
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE  # stderr එකත් අපි ලබාගන්නවා
            )

            response = web.StreamResponse(
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Disposition": f"inline; filename=\"{new_name}\""
                }
            )
            await response.prepare(request)

            # Telegram වෙතින් download කර FFmpeg වෙත pipe කිරීම සහ FFmpeg වෙතින් එන output client වෙත යැවීම එකවර කිරීම
            try:
                # FFmpeg ක්‍රියාවලියට දත්ත යැවීමේ සහ දෝෂ නිරීක්ෂණය කිරීමේ කාර්යය
                async def pipe_to_ffmpeg():
                    try:
                        # Telegram වෙතින් file එක chunk වශයෙන් download කර ffmpeg stdin වෙත යැවීම
                        async for chunk in tg_connect.yield_file(file_id, index, 0, 0, file_id.file_size, math.ceil(file_id.file_size / (1024*1024)), 1024*1024):
                            if process.stdin.is_closing():
                                break
                            process.stdin.write(chunk)
                            await process.stdin.drain()
                    except (asyncio.CancelledError, ConnectionResetError):
                        pass # Client connection close උනොත් මෙතනින් නවතිනවා
                    finally:
                        if not process.stdin.is_closing():
                            process.stdin.close()
                
                # FFmpeg වෙතින් එන output client වෙත යැවීමේ කාර්යය
                async def pipe_to_client():
                    try:
                        while not process.stdout.at_eof():
                            chunk = await process.stdout.read(4096)
                            if not chunk:
                                break
                            await response.write(chunk)
                    except (asyncio.CancelledError, ConnectionResetError):
                        pass # Client connection close උනොත් මෙතනින් නවතිනවා
                
                # FFmpeg දෝෂ log කිරීමේ කාර්යය
                async def log_stderr():
                    while not process.stderr.at_eof():
                        line = await process.stderr.readline()
                        if line:
                            logging.error(f"FFmpeg stderr: {line.decode().strip()}")

                # ඉහත කාර්යයන් 3ම එකවර ක්‍රියාත්මක කිරීම
                await asyncio.gather(pipe_to_ffmpeg(), pipe_to_client(), log_stderr())
                
                await response.write_eof()
                return response
                
            except asyncio.CancelledError:
                # Client connection එක cancel උනොත් FFmpeg process එක kill කරනවා
                logging.info(f"Client disconnected. Killing remux process for {original_name}")
                process.kill()
                await process.wait()
                return response
            finally:
                # ක්‍රියාවලිය අවසානයේදී සම්පත් නිදහස් කිරීම
                if process.returncode is None:
                    process.kill()
                await process.wait()
                logging.info(f"Remux process for {original_name} finished with exit code {process.returncode}")

        # MKV, AVI නොවේ නම් (MP4 වැනි), පරණ, වැඩ කරන ක්‍රමයටම යොමු කිරීම
        else:
            logging.info(f"Passing to standard streamer: {utils.get_name(file_id)}")
            return await media_streamer(request, db_id)

    except (InvalidHash, FIleNotFound) as e:
        raise web.HTTPForbidden(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass # Client disconnected, no need to log an error
    except Exception as e:
        traceback.print_exc()
        logging.critical(e)
        raise web.HTTPInternalServerError(text=str(e))
