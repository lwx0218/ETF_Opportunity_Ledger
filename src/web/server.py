"""仅本机的标准库 HTTP 服务；静态文件与 JSON API，不提供数据库下载。"""
from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from src.ledger.store import LedgerError
from .application import Application, RequestError

STATIC = Path(__file__).with_name("static")
CARD_ROUTE = re.compile(r"/api/cards/(T-[0-9]{4}-[0-9]{3,})(?:/(score|void|exit-signal))?\Z")


def create_server(app: Application, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # 避免评分理由等用户输入落入访问日志。
            return

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if isinstance(body, (dict, list)) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def dispatch(self, write=False):
            try:
                host = self.headers.get("Host", "")
                allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
                if host not in allowed:
                    raise RequestError("仅接受本机地址", 403)
                origin = self.headers.get("Origin")
                if origin and origin != f"http://{host}":
                    raise RequestError("拒绝跨站请求", 403)
                url = urlsplit(self.path)
                query = parse_qs(url.query, keep_blank_values=True)
                if set(query) - {"mode"} or len(query.get("mode", [])) > 1:
                    raise RequestError("不允许此查询参数")
                mode = app.effective_mode(query.get("mode", [None])[0])
                match = CARD_ROUTE.fullmatch(url.path)
                if write:
                    if self.headers.get("X-CSRF-Token") != app.csrf_token:
                        raise RequestError("页面凭证失效，请刷新", 403)
                    if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                        raise RequestError("须提交 JSON", 415)
                    length = self.headers.get("Content-Length", "")
                    if not length.isdigit() or not 0 < int(length) <= 16384 or self.headers.get("Transfer-Encoding"):
                        raise RequestError("请求大小不合法", 413)
                    try:
                        body = json.loads(self.rfile.read(int(length)))
                    except (ValueError, UnicodeDecodeError):
                        raise RequestError("JSON 格式不合法") from None
                    if match and match[2]:
                        result = app.mutate(match[2], body, card_id=match[1], mode=mode)
                    elif url.path in ("/api/demo/advance", "/api/demo/reset"):
                        result = app.mutate(url.path.rsplit("/", 1)[1], body, mode=mode)
                    else:
                        raise RequestError("未找到操作", 404)
                    self.send(200, result)
                elif url.path == "/api/state":
                    self.send(200, app.state(mode))
                elif match and not match[2]:
                    self.send(200, app.detail(match[1], mode))
                else:
                    name = "index.html" if url.path == "/" else url.path.removeprefix("/")
                    file = (STATIC / name).resolve()
                    if not file.is_relative_to(STATIC.resolve()) or not file.is_file():
                        raise RequestError("未找到页面", 404)
                    self.send(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            except RequestError as err:
                self.send(err.status, {"error": str(err)})
            except (LedgerError, sqlite3.IntegrityError) as err:
                self.send(409, {"error": str(err)})
            except (sqlite3.Error, OSError, ValueError):
                self.send(503, {"error": "数据暂不可用；未执行迁移，请检查服务器日志与数据库版本。"})

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch(write=True)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
