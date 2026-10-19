"""默认本机的标准库 HTTP 服务；远程仅允许纯演示或行情只读，不提供数据库下载。"""
from __future__ import annotations

import ipaddress
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
CARD_ROUTE = re.compile(r"/api/cards/(T-[0-9]{4}-[0-9]{3,})(?:/(void|exit-signal|spot-check))?\Z")


def validate_binding(host, public_host, demo_only, *, mode="demo", write=False):
    """仅 IPv4 字面量；远程须显式纯演示、行情只读，或已开启口令的正式记账。"""
    address = ipaddress.IPv4Address(host)
    public_safe = (mode == "demo" and demo_only) or mode == "market" or (mode == "readonly" and write)
    if public_host is not None:
        public = ipaddress.IPv4Address(public_host)
        if public.is_unspecified or public.is_multicast or public.is_loopback:
            raise ValueError("public-host 必须是明确的非 loopback 单播 IPv4 地址")
        if not public_safe:
            raise ValueError("public-host 须启用 --demo-only、--mode market，或 --mode readonly --write")
    if not address.is_loopback and (not public_safe or public_host is None):
        raise ValueError("非 loopback 监听须指定 --public-host，并启用 --demo-only、--mode market，或 --mode readonly --write")


def session_cookie(header):
    for part in (header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == "ledger_session" and value:
            return value
    return None


def cookie_header(token, clear=False):
    value = "" if clear else token
    age = 0 if clear else 12 * 3600
    return f"ledger_session={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}"


def create_server(app: Application, port=8765, *, host="127.0.0.1", public_host=None):
    validate_binding(host, public_host, app.demo_only, mode=app.mode, write=app.write)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # 避免评分理由等用户输入落入访问日志。
            return

        def send(self, status, body, content_type="application/json; charset=utf-8", set_cookie=None):
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if isinstance(body, (dict, list)) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if set_cookie:
                self.send_header("Set-Cookie", set_cookie)
            self.end_headers()
            self.wfile.write(data)

        def dispatch(self, write=False):
            try:
                host = self.headers.get("Host", "")
                allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
                if public_host is not None:
                    allowed.add(f"{public_host}:{self.server.server_port}")
                if host not in allowed:
                    raise RequestError("不接受此 Host 地址", 403)
                origin = self.headers.get("Origin")
                if origin and origin != f"http://{host}":
                    raise RequestError("拒绝跨站请求", 403)
                url = urlsplit(self.path)
                query = parse_qs(url.query, keep_blank_values=True)
                page = url.path in ("/", "/rotation", "/market", "/new", "/events")
                session = session_cookie(self.headers.get("Cookie"))
                permitted = ({"date", "mode"} if url.path in ("/events", "/api/events") else
                             {"mode", "as_of", "theme", "series", "card", "supersedes"} if page else
                             {"mode", "as_of", "theme", "series", "weeks"} if url.path == "/api/observation" else
                             {"mode", "theme"} if url.path == "/api/quote" else {"mode"})
                if set(query) - permitted or any(len(values) != 1 for values in query.values()):
                    raise RequestError("不允许此查询参数")
                mode = app.effective_mode(query.get("mode", [None])[0])
                if "theme" in query and not re.fullmatch(r"T[0-9]{2}", query["theme"][0]):
                    raise RequestError("容器编号不合法")
                if "card" in query and not re.fullmatch(r"T-[0-9]{4}-[0-9]{3,}", query["card"][0]):
                    raise RequestError("卡片编号不合法")
                if "supersedes" in query and not re.fullmatch(r"T-[0-9]{4}-[0-9]{3,}", query["supersedes"][0]):
                    raise RequestError("卡片编号不合法")
                match = CARD_ROUTE.fullmatch(url.path)
                if write:
                    if app.mode == "market":
                        raise RequestError("行情预览仅允许读取", 403)
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
                    if url.path == "/api/login":
                        token = app.login(body)
                        self.send(200, app.state(mode, token), set_cookie=cookie_header(token))
                        return
                    if url.path == "/api/logout":
                        if not app.session_ok(session):
                            raise RequestError("未登录，不能记账", 403)
                        app._check_revision(body)
                        app.logout(session)
                        self.send(200, app.state(mode), set_cookie=cookie_header("", clear=True))
                        return
                    if app.mode == "readonly" and not app.session_ok(session):
                        raise RequestError("未登录，不能记账", 403)
                    if match and match[2]:
                        result = app.mutate(match[2], body, card_id=match[1], mode=mode, session=session)
                    elif url.path == "/api/cards":
                        result = app.mutate("create", body, mode=mode, session=session)
                    elif url.path in ("/api/demo/advance", "/api/demo/reset"):
                        result = app.mutate(url.path.rsplit("/", 1)[1], body, mode=mode, session=session)
                    else:
                        raise RequestError("未找到操作", 404)
                    self.send(200, result)
                elif url.path == "/api/state":
                    self.send(200, app.state(mode, session))
                elif url.path == "/api/observation":
                    window = query.get("weeks", ["12"])[0]
                    if not window.isascii() or not window.isdigit():
                        raise RequestError("周窗口须为 1–26")
                    self.send(200, app.observation(mode, as_of=query.get("as_of", [None])[0],
                              theme=query.get("theme", [None])[0],
                              series=query.get("series", ["execution"])[0], weeks=int(window)))
                elif url.path == "/api/events":
                    self.send(200, app.event_feed(query.get("date", [None])[0]))
                elif url.path == "/api/quote":
                    if not app.session_ok(session):
                        raise RequestError("未登录，不能记账", 403)
                    self.send(200, app.quote(query.get("theme", [None])[0], mode))
                elif match and not match[2]:
                    self.send(200, app.detail(match[1], mode, session))
                else:
                    name = "index.html" if page else url.path.removeprefix("/")
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

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
