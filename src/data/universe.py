"""data/universe.csv → 各路由的抓取函数。

路由名（写进 coverage.route_used 与 raw 文件的 source 列）：
  csi                 中证官网指数行情
  eastmoney_index     东财指数 K 线（沪 1.000xxx / 深 0.399xxx）
  tencent_index       腾讯指数日线（不复权）
  eastmoney_etf_hfq   东财基金 K 线 fqt=2 后复权（研究 = 执行的容器）
  eastmoney_etf       东财基金 K 线 fqt=0 不复权（执行序列）
  tencent_etf         腾讯基金日线（不复权）
  yahoo / stooq       海外指数
  eia                 EIA 布伦特现货
代码映射只写能确定的；中证 93xxxx / Hxxxxx 指数不猜东财 / 腾讯代码。海外符号映射未经实网验证，以首次 probe 为准。
"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from typing import Callable

from . import sources as S

ROOT = Path(__file__).resolve().parents[2]
UNIVERSE = ROOT / "data" / "universe.csv"
PANEL_STATUSES = ("retained", "flagged")

# universe.research_route → 依次尝试的路由（serenity 的「一条不通退下一条」）
RESEARCH_CHAIN = {
    "csi": ["csi"],
    "eastmoney_index": ["eastmoney_index", "tencent_index"],
    "eastmoney_etf_hfq": ["eastmoney_etf_hfq"],      # 腾讯只有不复权 / 减法前复权，不能顶替后复权
    "yahoo": ["yahoo", "stooq"],
    "eia_or_yahoo": ["eia", "yahoo"],
}
EXEC_CHAIN = ["eastmoney_etf", "tencent_etf"]
PRICE_ONLY_ROUTES = {"csi", "eastmoney_index", "tencent_index", "yahoo", "stooq"}   # 指数价格版本：不含分红

YAHOO = {"NDX": "^NDX", "SPX": "^GSPC", "N225": "^N225", "HSTECH": "HSTECH.HK", "NDXTMC": "^NDXTMC", "BRENT": "BZ=F"}
STOOQ = {"NDX": "^ndx", "SPX": "^spx", "N225": "^nkx"}
EIA = {"BRENT": "PET.RBRTE.D"}

# 拉不到全收益版本时，universe v1 已声明的「研究 = 执行」替代（replan §1 表：国债拉不到财富版则用 511260 后复权）
DECLARED_FALLBACK = {"H11077": ("511260", "eastmoney_etf_hfq")}
# 只作信息探测、不自动采用的近似指数（AGENTS.md：核不到的主题剔除，不用近似指数替代；是否采用由 Cowork 决定）
INFO_ALTERNATIVE = {"NDXTMC": ("^NDXT", "yahoo")}

_CODE = re.compile(r"\^[A-Za-z0-9]+|[A-Za-z]*\d[A-Za-z0-9]*")


def load(path: Path = UNIVERSE) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def in_panel(row: dict) -> bool:
    return row.get("status") in PANEL_STATUSES


def tr_candidates(row: dict) -> list[str]:
    """tr_code_candidates 里的代码（分号分隔；T33 这类自由文本只取像代码的片段）。"""
    out: list[str] = []
    for tok in _CODE.findall(row.get("tr_code_candidates") or ""):
        if tok not in out:
            out.append(tok)
    return out


# ------------------------------------------------------------------ 代码映射
def index_secid(code: str) -> str | None:
    if re.fullmatch(r"399\d{3}", code):
        return f"0.{code}"
    if re.fullmatch(r"000\d{3}", code):
        return f"1.{code}"
    return None


def index_tencent(code: str) -> str | None:
    s = index_secid(code)
    return None if s is None else ("sz" if s[0] == "0" else "sh") + code


def fund_secid(code: str) -> str | None:
    if re.fullmatch(r"5\d{5}", code):
        return f"1.{code}"
    if re.fullmatch(r"1[56]\d{4}", code):
        return f"0.{code}"
    return None


def fund_tencent(code: str) -> str | None:
    s = fund_secid(code)
    return None if s is None else ("sh" if s[0] == "1" else "sz") + code


def yahoo_symbol(code: str) -> str | None:
    return code if code.startswith("^") else YAHOO.get(code)


def route_fn(route: str, code: str) -> Callable[[date, date], S.Fetched] | None:
    """路由 + 代码 → fetch(start, end)；代码无法映射到该路由时返回 None。"""
    if route == "csi":
        return lambda b, e: S.fetch_csindex(code, b, e)
    if route == "eastmoney_index" and index_secid(code):
        return lambda b, e: S.fetch_eastmoney(index_secid(code), b, e, fqt=0)
    if route == "tencent_index" and index_tencent(code):
        return lambda b, e: S.fetch_tencent(index_tencent(code), b, e)
    if route == "eastmoney_etf_hfq" and fund_secid(code):
        return lambda b, e: S.fetch_eastmoney(fund_secid(code), b, e, fqt=2)
    if route == "eastmoney_etf" and fund_secid(code):
        return lambda b, e: S.fetch_eastmoney(fund_secid(code), b, e, fqt=0)
    if route == "tencent_etf" and fund_tencent(code):
        return lambda b, e: S.fetch_tencent(fund_tencent(code), b, e)
    if route == "yahoo" and yahoo_symbol(code):
        return lambda b, e: S.fetch_yahoo(yahoo_symbol(code), b, e)
    if route == "stooq" and code in STOOQ:
        return lambda b, e: S.fetch_stooq(STOOQ[code], b, e)
    if route == "eia" and code in EIA:
        return lambda b, e: S.fetch_eia(EIA[code], b, e)
    return None
