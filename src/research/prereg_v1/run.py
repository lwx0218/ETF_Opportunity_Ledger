#!/usr/bin/env python3
"""prereg-v1 执行入口。步骤必须按顺序，后一步检查前一步的产物：

    python -m src.research.prereg_v1.run check        --panel P   # 只校验形状与覆盖，不算收益
    python -m src.research.prereg_v1.run characterize --panel P   # §10-2 设计期刻画；分不开就写 STOP
    python -m src.research.prereg_v1.run design       --panel P   # §10-3 设计期 ±20% 扰动
    python -m src.research.prereg_v1.run oos          --panel P   # §10-4 冻结样本外，只允许一次
    python -m src.research.prereg_v1.run rolling      --panel P   # §10-5 逐年表（须已有 OOS 锁）

P = 指标层 build 产出的面板库 outputs/panel-D.sqlite（panel、bench 两表）；--bench 默认同一个库。

产物写到 outputs/prereg_v1/（不入 Git）；结论由人追加进 docs/etf-rotation-prereg-v1.md §13。
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .characterize import characterize
from .config import DESIGN_END, OOS_END, OOS_START, PERTURB_FACTORS, PERTURB_PARAMS, Params
from .engine import random_entry_null, simulate
from .metrics import acceptance, avg_pairwise_corr, is_fragile, portfolio_stats, r_by, r_stats
from .panel import PanelError, content_sha256, hole_runs, read_table, validate_bench, validate_panel

ROOT = Path(__file__).resolve().parents[3]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head():
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def stale_segments(panel_path):
    """build 旁边的 panel-D.build-report.json（同 src/indicators/build.py 的 report_path 规则）里各容器的整段平盘
    （stale_runs，≥ 5 行）；没有报告时返回 None，报告读不懂时报 PanelError。"""
    rp = Path(panel_path).with_name(Path(panel_path).stem + ".build-report.json")
    if not rp.exists():
        return None
    try:
        rep = json.loads(rp.read_text(encoding="utf-8"))
        rows = [dict(container=c, first=r["first"], last=r["last"], rows=int(r["rows"]), hole_rows=int(r["hole_rows"]),
                     trailing=bool(r["trailing"]))
                for c, v in rep["containers"].items() for r in v.get("stale_runs", [])]
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise PanelError(f"{rp.name} 读不懂（{type(e).__name__}: {str(e)[:80]}）：重新 build") from e
    return pd.DataFrame(rows, columns=["container", "first", "last", "rows", "hole_rows", "trailing"])


def fmt(d):
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items() if not isinstance(v, pd.DataFrame)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["check", "characterize", "design", "oos", "rolling"])
    ap.add_argument("--panel", required=True)
    ap.add_argument("--bench", default=None, help="默认与 --panel 同一个库")
    ap.add_argument("--out", default=str(ROOT / "outputs" / "prereg_v1"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    p = Params()
    a.bench = a.bench or a.panel
    full = panel = validate_panel(read_table(a.panel, "panel"))
    hs300 = validate_bench(read_table(a.bench, "bench"))
    panel = panel[panel["date"] <= pd.Timestamp(OOS_END)]            # 冻结样本外之后的数据一律不进 V1
    design = panel[panel["date"] <= pd.Timestamp(DESIGN_END)]
    stop_file, char_file, design_file = out / "STOP", out / "characterize.json", out / "design.json"
    lock = out / "OOS_LOCK.json"

    if a.step == "check":
        cov = panel.groupby("container")["date"].agg(["min", "max", "count"])
        print(cov.to_string())
        print(f"\n容器 {len(cov)} 个；设计期行数 {len(design)}；基准 {hs300.index.min().date()} → {hs300.index.max().date()}")
        print("提醒（I-18）：hs300 必须是沪深300全收益指数 H00300；容器价格必须是全收益或后复权口径。")
        try:
            segs = stale_segments(a.panel)
        except PanelError as e:
            print(f"⚠ {e}")
            return 2
        if segs is None:
            holes = hole_runs(panel)
            print("\n⚠ 面板旁边没有 build-report（panel-D.build-report.json），整段平盘的起止不详；"
                  "下面只是 data_hole = 1 的段（起点是连续平盘的第 5 行）：" + ("无" if holes.empty else ""))
            if not holes.empty:
                print(holes.to_string(index=False))
            return 0
        if segs.empty:
            print("数据断档（I-25）：无")
        else:
            print(f"\n数据断档（I-25 / I-26；V1 报告按整段列出）：{len(segs)} 段 {int(segs['rows'].sum())} 行平盘，"
                  f"其中 data_hole = 1 {int(segs['hole_rows'].sum())} 行")
            print("（整段 = build-report 的 stale_runs。每段从第 5 行起 data_hole = 1：不产生入场信号、不成交、不参与横截面排名、"
                  "不进刻画与零模型；前 4 行与真实休市同样对待）")
            print(segs.to_string(index=False))
        got = full.groupby("container")["data_hole"].sum()          # 用未截断的面板：报告是整个数据包的
        want = segs.groupby("container")["hole_rows"].sum() if not segs.empty else pd.Series(dtype=int)
        idx = got.index.union(want.index)
        diff = got.reindex(idx, fill_value=0) - want.reindex(idx, fill_value=0)
        if diff.ne(0).any():
            print(f"⚠ 面板的 data_hole 行数与 build-report 对不上（不是同一次 build？面板 − 报告）：{diff[diff.ne(0)].astype(int).to_dict()}")
            return 1
        return 0

    if a.step == "characterize":
        c = characterize(design, p, DESIGN_END)
        print(c["by_class"].to_string()); print(); print(c["by_state"].to_string())
        print(f"\n可进 − 非可进：{c['diff_entry_minus_rest']:+.4f}，95% 区间 {c['ci95'][0]:+.4f} ~ {c['ci95'][1]:+.4f}（{c['n_blocks']} 个季度块）")
        char_file.write_text(json.dumps({k: v for k, v in c.items() if k not in ("by_state", "by_class")}, ensure_ascii=False, indent=1))
        if not c["separable"]:
            stop_file.write_text("形态状态在设计期无区分度：按 prereg-v1 §10 第 2 步就地停止，不进回测。\n")
            print("\n→ 分不开：已写 STOP，按预注册就地停止。")
        return 0

    if stop_file.exists():
        print(f"{stop_file} 存在：刻画已判定无区分度，按预注册不进回测。"); return 2
    if a.step in ("design", "oos", "rolling") and not char_file.exists():
        print("先跑 characterize。"); return 2

    if a.step == "design":
        start = design["date"].min()
        rows = []
        for name, f in [(None, 1.0)] + [(n, f) for n in PERTURB_PARAMS for f in PERTURB_FACTORS]:
            q = p if name is None else p.perturbed(name, f)
            rs = r_stats(simulate(design, q, start, DESIGN_END).trades)
            rows.append(dict(variant="基准" if name is None else f"{name}×{f}", **{k: rs.get(k) for k in ("n", "mean_R", "mean_R_drop_best_3", "share_lt_neg1R")}))
        t = pd.DataFrame(rows)
        base = t.loc[0, "mean_R"]
        fragile = is_fragile(base, t["mean_R"].iloc[1:])
        print(t.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
        print(f"\n脆弱（任一扰动变号或不到基准一半）：{fragile}（只报告，不阻断冻结样本外）")
        design_file.write_text(json.dumps({"table": t.to_dict("records"), "fragile": fragile}, ensure_ascii=False, indent=1, default=float))
        return 0

    if a.step == "oos":
        if lock.exists():
            print(f"冻结样本外已经跑过（{lock}）。prereg-v1 §9：只跑一次，不允许重跑。"); return 3
        if not design_file.exists():
            print("先跑 design。"); return 2
        res = simulate(panel, p, OOS_START, OOS_END)
        rs, port = r_stats(res.trades), portfolio_stats(res, panel, hs300, p)
        acc = acceptance(res.trades, port, p)
        null = {}
        if p.null_reps:
            n_sig = len(res.trades) + len(res.skipped)
            nr = random_entry_null(panel, p, OOS_START, OOS_END, n_sig, p.null_reps)
            null = dict(reps=p.null_reps, n_signals=n_sig, null_mean_R_median=float(np.nanmedian(nr)),
                        null_p95=float(np.nanpercentile(nr, 95)),
                        v1_percentile=float((nr < rs.get("mean_R", np.nan)).mean()))
        lock.write_text(json.dumps(dict(
            ran_at_utc=datetime.now(timezone.utc).isoformat(), git_head=git_head(),
            panel_sha256=sha256(a.panel), bench_sha256=sha256(a.bench), panel_content_sha256=content_sha256(a.panel), params=repr(p),
            r_stats=fmt(rs), portfolio=fmt(port), acceptance=acc, random_entry_null=null), ensure_ascii=False, indent=1, default=float))
        res.trades.to_csv(out / "oos_trades.csv", index=False)
        res.skipped.to_csv(out / "oos_skipped.csv", index=False)
        res.nav.to_csv(out / "oos_nav.csv", header=["nav"])
        print(json.dumps(fmt(rs), ensure_ascii=False, indent=1, default=float))
        print(r_by(res.trades, "branch").to_string()); print(r_by(res.trades, res.trades["entry_date"].dt.year).to_string())
        print(json.dumps(fmt(port), ensure_ascii=False, indent=1, default=float)); print(port["yearly"].to_string())
        print(f"同时持仓平均两两相关：{avg_pairwise_corr(res, panel, p.corr_window):.3f}")
        for k, v in acc.items():
            print(("通过 " if v else "不通过 ") + k)
        if null:
            print(f"随机入场对照（诊断，非验收）：{null}")
        return 0

    if a.step == "rolling":
        if not lock.exists():
            print("逐年表只能在冻结样本外之后做。"); return 2
        res = simulate(panel, p, panel["date"].min(), OOS_END)
        port = portfolio_stats(res, panel, hs300, p)
        print(r_by(res.trades, res.trades["entry_date"].dt.year).to_string()); print(port["yearly"].to_string())
        return 0


if __name__ == "__main__":
    sys.exit(main())
