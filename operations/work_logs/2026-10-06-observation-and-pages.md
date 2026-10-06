# 真实观察读模型与双页恢复

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: observation-and-pages 第一至三节
- Timestamp (UTC): 2026-10-06T11:32:00Z
- Owner: Faye
- Route: direct-execute
- Source of truth: Owner 本轮指令；operations/planning/2026-10-06-observation-and-pages.md §1–3；AGENTS.md

## 范围与实现

从最新 `main=ae7b63d` 建立 `codex/observation-and-pages`。开发前对照完整 intake、framework §12–13、冻结卡片合同、Main/Detail/Scroll 与轮动方向稿和深浅设计规则。复核者先读原始要求，再读本轮执行单；没有把旧原型的 17 容器、510300、回放成绩或参数带入产品。

新增 `src/observation`，仅在调用方提供的只读快照上执行 SELECT。研究选择来自当前 coverage；执行 ETF、独立价格候选分别显示，不替换研究选择。观察日按北京时间 15:00 与官方日历裁定，不把行情末日冒充当前观察日。海外遵守 D−1 与原生指标、第五个连续平盘日断档；每一历史周先截至自身日期再选量源。字段返回身份、用途、价格口径、观察日、原生日、窗口、获取时刻及具体不可用原因。

复用既有 RS、ATR20、月末 z 和形态函数：22 个完整对齐收盘点才算 RS；状态要求完整历史 close/来源及最近 70 根真实 OHLC，不重启 EMA；ext 使用内部 ATR14。原始异常保留，不补 OHL 或扩包络；无效量仅在计算副本遮为缺失，避免负量伪造放量状态。未核定单位不画量柱。声明池仍是 37 个容器，未知缺口时全池 rank=null；已知上市/预热排除与未知缺口分开，排名为 method=min。完整研究质量资格另行显示，未由字段可用性放行研究。

恢复 `/` 三态与六问、`/rotation` 37×周矩阵、同页原生价格/字段依据、冻结详情、价格窗口及历史选样不足说明。两页 URL 保留模式/日期/容器/序列与卡片；刷新、Back、键盘、深浅和窄屏均有实际旅程验证。全序列登记移入默认收起的辅助检查，并注明其全历史范围与观察日期不同。NAV/份额/金额/四层证据的具体欠项保留责任归属。

`market` 不读正式台账、规则或扫描记录，只写“此观察入口不载入正式判断/扫描结果”；`readonly` 读取真实台账与配置，单独列台账已处理日；`demo/demo-only` 观察与规则全部合成，37 容器内存行情复用六张原演示卡的价格公式。原有盲评分、作废、信号与次日开盘流程保留；demo-only 不显示不可访问的正式入口。

执行单要求的 live 缺口同时收口：与 build 共用全池只读质量门、官方 calendar 和 strict 输入，不填 OHL、不跳缺容器。保留正式研究的既有高低价扩包络政策、海外休市规则；历史 I-21 量源比例先截至消费窗口。这不表示执行过真实 live 或正式研究。

## 实际验证

最终测试无失败、无跳过；下面记录最终代码的实际结果。

| 门禁 | 结果 |
| --- | --- |
| 开发 SQLite 3.53.1 全套 | 444 项通过，83.616 秒 |
| 精确 SQLite 3.42.0 全套 | 444 项通过，87.565 秒 |
| 独立正确性复核 | approve；独立 43 项相关测试通过，含负量增量 |
| 独立产品复核 | approve；真实 market、readonly 与完整隔离演示旅程 |
| Ponytail 4.10.3 官方 skill | 最终及所有增量：Lean already. Ship.；独立 2 项合成 smoke 通过 |
| 静态检查 | node --check、git diff --check 通过 |
| 正式库保全 | SHA256 不变、只读 integrity_check=ok、未创建正式台账 |

全套命令：`.venv/bin/python -m unittest discover -s tests -t .` 与 `/workspace/scratch/sqlite-3.42.0/python -m unittest discover -s tests -t .`。独立 reviewer 按 `.pi/agents/reviewer.md` 只读执行；Ponytail 实际读取 `/workspace/scratch/ponytail-4.10.3/package/skills/ponytail-review/SKILL.md`，复杂度复核与正确性/产品复核分开。

复核发现并修复了：已登记历史前缀缺口隐性重置 EMA；海外原生根数误作 A 股对齐预热数；官方周五休市的周尾标签；缺失日期 NaT 的 JSON 序列化；负成交量伪造放量形态；demo 重置沿用旧观察；卡片最新 R 错标创建日；demo-only 暴露不可用入口；RS 缺可见基准/窗口/混合口径；readonly 空台账缺规则价值的不足回答。没有跳过失败测试：SQLite 3.42 驱动缺 `iterdump` 的失败改为 schema 与全部表行的只读保全快照，并重跑全套。

完整测试中的研究/随机诊断输出来自既有合成 fixture，与正式研究无关。没有改策略参数、研究选择、universe、coverage、正式行情/台账、规则或 cron、治理文件。正式规则配置保持关闭，正式台账文件原本不存在且仍不存在。

## 真实查看登记与截图

本轮确实查看了真实数据，不能再称“未看过”。只读库 SHA256 在前后均为 `448c8f1f3a9568b7cde5ebcf8a4dc5eb8392ca59c9681cea938235430ef8d150`。观察主日为 2026-09-30；12 个周截面为 07-17、07-24、07-31、08-07、08-14、08-21、08-28、09-04、09-11、09-18、09-24、09-30，另验请求 09-27 映射官方有效日 09-24。计算按各列截至日读取此前历史预热；没有扫描或形成真实机会卡。

查看全部 37 个声明容器的身份、缺口、close、RS21、ATR20、state、ext、月末 z、排名资格。09-30 可读研究收盘及 RS 的 10 条序列为 H00300/csi、H00852/csi、399006/tencent_index、399998/csi、BRENT/yahoo、H20606/csi、H00015/csi、NDX/yahoo、^SP500TR/yahoo、N225/yahoo，均 raw；海外原生末日为 09-29，国内为 09-30。27 条未知缺口保留位置，完整排名不提供；此范围不能称当前市场机会排序。

09-30 实测 benchmark_ready=true、research_ready=false；close/RS 有效各 10，ATR20 有效 6，state/ext 有效各 5，月末 z 有效 10，rank 有效 0。该日已看到的 RS 范围约 −3.30% 至 +20.46%，ext 约 −1.563 至 +0.420，月末 z 约 −1.144 至 +1.759；这些是观察值，不是策略效力结论。

价格详情实际查看 T01 H00300 全收益研究、T02 510500 不复权执行、T02 000905 独立价格候选（tencent_price_index_offline，price_only=true）；API 载最近 260 个原生位置，图默认显示 90。H00300 260 位窗口为 2025-09-04 至 2026-09-30。亦查看全库 51 条序列辅助登记（152,408 行）。数据陷阱仍适用：主题回填偏差、指数与 ETF 差异及每年 1% 折扣、腾讯减法 qfq 不可直接算收益、价格与全收益不可混作同口径成绩。

本地证据保存在忽略的 `outputs/`，不把大型 JSON 或回放库入 Git：

- `outputs/observation-preview/index.json`：实际双页深浅、窄屏、执行/候选详情截图的 URL、源码与图片哈希；`frontend-journey.json`：前端旅程断言。
- `outputs/independent-product-review/market/product-review.json`：独立真实双页产品复核及截图；相邻 `demo/` 含独立评分、作废、出场信号、次日开盘、连续 20 个出场后观察到“已结”的证据。
- 本轮早期 37×12 首算约 5.36 秒；同一快照与参数的缓存请求约 0.08 秒。缓存按文件版本、北京时间日期/15:00 边界及请求身份隔离，未用末日量源污染历史列。

## 复现与剩余范围

```bash
.venv/bin/python -m src.web --mode market --port 8770
# http://127.0.0.1:8770/?mode=market&as_of=2026-09-30&theme=T01
# http://127.0.0.1:8770/rotation?mode=market&as_of=2026-09-30&theme=T01
```

独立终端演示：`.venv/bin/python -m src.web --demo-only --port 8771 --demo-dir outputs/observation-demo`。本地正式只读：`.venv/bin/python -m src.web --mode readonly --port 8773`。安装、Pi 既有入口与完整验收步骤见 [使用说明](../../docs/runnable-ledger.md)。未替换 Pi 服务、改防火墙或宣称服务器已部署；Pi 应部署准确提交后按原授权模式复验，不自行切换公开模式。

本包完成“两页真实观察与隔离演示”，不等于全产品完工。编排仍负责口径/异常裁定；Codex 后续负责证据采集/草稿/确认、完整四层判断、正式盲评分/作废重建/出场入口和完整 R6；Pi 负责经授权的量额/NAV/份额与增量取证、A7 后真实卡片及五日无人值守。正式研究与正式规则保持关闭。

分支推送、PR 与远端必需检查的实际结果由本轮交付记录补充；不绕过 API 权限、分支保护或检查。
