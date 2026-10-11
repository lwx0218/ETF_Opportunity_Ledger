# CSI 研究序列沙箱回填：入库与 000905 复原

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 24 个容器 CSI 研究序列回填（runs 7/8）入库，复原审计过的 000905 离线价格序列
- Timestamp (UTC): 2026-10-11T14:10:00Z
- Owner: Faye
- Route: direct-execute
- Baseline: dev `f7219fa9dda3eaf989ba7e22d08e113a08453fb3`（回填代码为 dev `f16b708`，记录在 `runs.git_commit`）
- 执行机器: Cursor Cloud sandbox（不是 Pi 服务器）

## 结论先行

- 24 个容器：13 个取得 CSI 全收益（price_only=False），11 个回退价格指数（price_only=True），0 个错误。
- runs 7/8 共 1,036 次 CSI 请求，0 次 HTTP 403；峰值 56 次/分钟。服务器 2026-10-11 约 50 次请求后即 403，说明被限的是服务器 IP，不是端点本身。
- 执行 ETF 37 个代码（tencent_etf，adj=raw）source / 行数 / 起止日期与原库完全一致；既有研究序列未变。
- 回填把 T02 的 000905（审计过的离线导入，PR #23）覆盖成了 CSI 价格序列，本次按原库逐行复原。

## 做了什么

1. 在原库只读副本 `/tmp/mkt-copy.sqlite` 上执行（代码 worktree `/tmp/wt-r2`，dev f16b708）：
   - `python -m src.data backfill --end 2026-09-30 --only T04 --db /tmp/mkt-copy.sqlite` → run 7（13:21:32–13:22:23Z，ok）
   - `python -m src.data backfill --end 2026-09-30 --only T02,T06,T07,T08,T09,T10,T11,T12,T13,T18,T19,T20,T21,T22,T23,T24,T25,T26,T27,T28,T30,T32,T33 --db /tmp/mkt-copy.sqlite` → run 8（13:22:50–13:50:01Z，ok）
   - eastmoney 在沙箱不可达（25 次 RemoteDisconnected），执行路由照常落到 tencent_etf，与服务器行为一致。
2. `git worktree add /tmp/wt-data -b data/csi-backfill-20261011 origin/dev`，`cp /tmp/mkt-copy.sqlite data/market.sqlite`。
3. 复原 000905：单事务内 `DELETE FROM bars WHERE code='000905' AND adj='raw'`（删 5,302 行 csi），再从 `file:/workspace/data/market.sqlite?mode=ro` 按 `PRAGMA table_info(bars)` 全列插入原 5,282 行；同事务把 coverage T02（run 8）的 `price_first_date` 由 2005-01-01 改回 2005-01-04。原因：CSI 版 000905 含 23 个非交易日行、缺 2008/2009/2010-12-31，而离线导入版有完整审计链；主键 (code,adj,date) 使重抓同一代码直接覆盖 source。
4. `PRAGMA integrity_check` ok → `VACUUM` → 无 -wal/-shm/-journal → sha256sum。

## 核对

| 项目 | 结果 |
| --- | --- |
| 000905 raw | 5,282 行，source 仅 tencent_price_index_offline，2005-01-04→2026-09-30，排序行 SHA256 与原库相同（d2650e81…99a2） |
| 执行 ETF（universe retained/flagged 37 个 code，adj=raw） | (source,count,min,max) 37/37 相同，0 差异 |
| 既有研究序列（H00300/H00015/H00852/H20606/399998/000852/399006/BRENT/NDX/SPX/^SP500TR/N225） | 未变 |
| 完整性 | integrity_check ok，journal_mode delete，VACUUM 后 33,648,640 字节 |
| SHA256 before | 448c8f1f3a9568b7cde5ebcf8a4dc5eb8392ca59c9681cea938235430ef8d150 |
| SHA256 after | b56148daf640d4bca6bbd2856a9c36fd9a11472ea9ebe94753476e0bb02e5290 |
| preflight --end 2026-09-30 | exit 1；benchmark_ready true，research_ready false（与回填前相同） |
| observe(2026-09-30, weeks=1) | execution 池 37 / 有效 37；research 池 37 / 有效 34，缺 T16/T36/T38（回填前 10/37） |
| tests.data（fixtures） | 181 项通过 |

## 逐容器表（coverage_latest）

| theme_id | container | route_used | series_code | tr_code_used | price_only | first_date | last_date | rows |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T02 | 中证500 | csi | H00905 | H00905 | False | 2005-01-01 | 2026-09-30 | 5302 |
| T04 | 科创50 | csi | 000688 | | True | 2019-01-01 | 2026-09-30 | 1645 |
| T06 | 半导体 | csi | H20184 | H20184 | False | 2005-01-01 | 2026-09-30 | 5301 |
| T07 | 半导体设备 | csi | 931743CNY010 | 931743CNY010 | False | 2018-01-01 | 2026-09-30 | 1890 |
| T08 | AI/算力 | csi | H20713 | H20713 | False | 2012-01-01 | 2026-09-30 | 3481 |
| T09 | 通信/光模块 | csi | 931160 | | True | 2018-01-01 | 2026-09-30 | 1858 |
| T10 | 软件/信创 | csi | H20202 | H20202 | False | 2005-01-01 | 2026-09-30 | 5301 |
| T11 | 机器人 | csi | H20590 | H20590 | False | 2011-01-01 | 2026-09-30 | 3842 |
| T12 | 消费电子 | csi | 931494 | | True | 2012-01-01 | 2026-09-30 | 3354 |
| T13 | 有色 | csi | H00819 | H00819 | False | 2005-01-01 | 2026-09-30 | 5302 |
| T18 | 化工 | csi | H20187 | H20187 | False | 2005-01-01 | 2026-09-30 | 5301 |
| T19 | 新能源车 | csi | H20997 | H20997 | False | 2014-01-01 | 2026-09-30 | 2870 |
| T20 | 光伏 | csi | 931151 | | True | 2012-01-01 | 2026-09-30 | 3354 |
| T21 | 军工 | csi | 399967 | | True | 2005-01-01 | 2026-09-30 | 5298 |
| T22 | 医药 | csi | H00913 | H00913 | False | 2002-01-01 | 2026-09-30 | 6023 |
| T23 | 创新药 | csi | 931152 | | True | 2014-01-01 | 2026-09-30 | 2869 |
| T24 | 消费 | csi | H00932 | H00932 | False | 2005-01-01 | 2026-09-30 | 5302 |
| T25 | 白酒 | csi | 399987 | | True | 2009-01-01 | 2026-09-30 | 4328 |
| T26 | 农业 | csi | H00949 | H00949 | False | 2005-01-01 | 2026-09-30 | 5302 |
| T27 | 银行 | csi | 399986 | | True | 2005-01-01 | 2026-09-30 | 5302 |
| T28 | 券商 | csi | 399975 | | True | 2007-01-01 | 2026-09-30 | 4700 |
| T30 | 地产 | csi | 931775 | | True | 2005-01-01 | 2026-09-30 | 5301 |
| T32 | 红利低波 | csi | H20269 | H20269 | False | 2005-01-01 | 2026-09-30 | 5061 |
| T33 | 国债 | csi | H11077 | | True | 2008-01-01 | 2026-09-30 | 4331 |

## 已知边界

- CSI 序列只有 close，open/high/low 为 NULL；CSI 在每年 1 月 1 日多出一行、缺 2008/2009/2010-12-31，首年只给一个年末行（T04/T07/T08/T09/T12/T19/T20/T23/T28/T32/T33 的 `最大间隔 36x 天`）。
- price_only 容器试过的全收益候选均返回 0 行：T04 H00688/000688CNY010；T09 931160CNY010；T12 931494CNY010；T20 931151CNY010；T21 399967CNY010/H29967；T23 931152CNY010；T25 399987CNY010/H29987；T27 399986CNY010/H29986；T28 399975CNY010/H29975；T30 931775CNY010；T33 H11077 无全收益标记未采用、H11077CNY010 0 行。
- research_ready 仍为 false：正式门槛要求真实 OHLC 和完整交易日收盘，CSI 路由结构上不满足，与回填前一致；不是本次数据获取的问题。
- 仍无研究序列的 3 个容器：T16 黄金（eastmoney hfq 路由不可达，run 2 既有错误）、T36 纳指科技（NDXTMC 无映射）、T38 恒生科技（^HSTECH 404，无映射）。
- 库内 coverage T02 的 route_used/series_code 仍指向 H00905（全收益，未动）；只有价格序列 000905 复原为离线版。

## 对 Pi 的影响

- 服务器 IP 对 csindex 有限流（约 50 次后 403），沙箱 56 次/分钟不受限。每日 `update` 若要打 ~50 次 CSI 请求，在 Pi 上可能 403：R5 需要加节奏控制与退避，或把 update 放到别的机器跑再同步库文件。
- 再次把 T02 纳入 backfill 会再度覆盖 000905；需要排除 T02 的价格代码或事后重跑离线导入。
