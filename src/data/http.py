"""标准库 HTTP：统一 UA、超时、至多重试一次、JSON。所有数据源只经这里出网。

模式抄自 serenity_quant_research（physical-first）api/app/ingest/http.py，不引用其代码包。
每次请求在 LOG 里留一条（url、时刻、字节数、sha256、错误）——工程任务的证据标准是
「URL + 获取日期 + 文件哈希」（replan §6.1），probe 把它写到 outputs/data/probe-requests.jsonl。
"""
from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 ETFLedgerData/0.1")
DEFAULT_TIMEOUT = 20
RETRIES = 1                 # replan §6.4：任何数据源失败不重试超过一次

LOG: list[dict] = []        # 本进程的请求记录（URL 已脱敏）
RECORD_DIR: Path | None = None   # 设了就把原始响应落盘（probe --record），供日后替换构造的 fixtures


_SECRET = re.compile(r"((?:api_?key|token|apikey)=)[^&\s]+", re.I)


def redact(text: str) -> str:
    """URL / 错误信息里的密钥换成 ***：请求记录与 coverage 会进研究数据包。"""
    return _SECRET.sub(r"\1***", text)


class FetchError(RuntimeError):
    """一次抓取失败（网络 / 状态码 / 解析），带上可读原因写进 coverage.error。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record(url: str, raw: bytes | None, error: str | None) -> None:
    ent = {"url": redact(url), "fetched_at": _now(), "bytes": len(raw) if raw is not None else None,
           "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None, "error": error}
    if raw is not None and RECORD_DIR is not None:
        RECORD_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{hashlib.sha1(redact(url).encode()).hexdigest()[:12]}.body"
        (RECORD_DIR / name).write_bytes(raw)
        ent["file"] = name
    LOG.append(ent)


def get(url: str, params: dict | None = None, *, timeout: int = DEFAULT_TIMEOUT, headers: dict | None = None,
        retries: int = RETRIES, backoff: float = 1.5) -> bytes:
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip", **(headers or {})})
            with urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            _record(url, raw, None)
            return raw
        except HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 404):
                break
        except (URLError, TimeoutError, OSError, http.client.HTTPException) as e:     # 含 IncompleteRead（长窗口断连）
            last = e
            if "Tunnel connection failed: 403" in str(e):     # 出网策略拒绝：重试也不会过
                break
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
    msg = redact(f"{type(last).__name__}: {str(last)[:160]}")
    _record(url, None, msg)
    raise FetchError(f"{msg}  ← {redact(url)[:160]}")


def get_json(url: str, params: dict | None = None, **kw) -> Any:
    raw = get(url, params, **kw)
    text = raw.decode("utf-8", "ignore").strip()
    # 东财有的接口包 jQuery 回调：cb({...})
    if text and not text.startswith(("{", "[")):
        i, j = text.find("("), text.rfind(")")
        if 0 <= i < j:
            text = text[i + 1:j]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise FetchError(f"not JSON ({e.msg}): {text[:120]!r}  ← {redact(url)[:120]}") from e
