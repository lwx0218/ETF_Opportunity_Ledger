# -*- coding: utf-8 -*-
"""2026 进攻信号的赔付分解（etf-rotation-prereg-v1 §1 与 intake §2 第 2 条的数字来源）。
读 data/signals_2026.csv（由 signals.py 生成），只看已平仓的进攻信号：胜率、赢/输均值、盈亏比、期望、去掉最好 1/2/3 笔后的期望、t 统计量。
原为 2026-09-18 会话内一次性脚本，2026-09-25 原样留存为文件，逻辑未改。"""
from pathlib import Path as _Path
ROOT_S = str(_Path(__file__).resolve().parents[2])  # 仓库根目录（src/<组>/<脚本>.py 上两级）
import pandas as pd, numpy as np

s = pd.read_csv(f"{ROOT_S}/data/signals_2026.csv")
a = s[(s["mode"] == "进攻") & (~s.open.astype(bool))].copy().sort_values("excess")
print("n =", len(a)); print(a[["cont", "entry", "state", "days", "ret", "bench", "excess", "exit_why"]].to_string(index=False))
e = a.excess.values; w = e[e > 0]; l = e[e <= 0]
print("\n中位 %.1f%%  均值 %.1f%%  胜率 %.0f%%" % (np.median(e)*100, e.mean()*100, (e > 0).mean()*100))
for k in (1, 2, 3): print("去掉最好的 %d 笔后均值 %.1f%%" % (k, np.sort(e)[:-k].mean()*100))
print("赢的均值 %.1f%% (n=%d)  输的均值 %.1f%% (n=%d)  盈亏比 %.2f" % (w.mean()*100, len(w), l.mean()*100, len(l), w.mean()/abs(l.mean())))
print("期望 = %.0f%% × %.1f%% + %.0f%% × %.1f%% = %.2f%%" % ((e>0).mean()*100, w.mean()*100, (e<=0).mean()*100, l.mean()*100, e.mean()*100))
print("前 3 大贡献占总和的比例: %.0f%%" % (np.sort(e)[-3:].sum() / e.sum() * 100))
print("t 统计量 = %.2f" % (e.mean() / (e.std() / np.sqrt(len(e)))))
