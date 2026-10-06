# ETF_Opportunity_Ledger

<!-- HARNESS:README:MANAGED:START -->
## Harness / Pi Onboarding

- 模型合同：`AGENTS.md`
- 人类手册：`Harness_manual.md`
- Pi capabilities：`.pi/`
- 项目 evidence：`docs/project-intake/`、`operations/`

第一次进入：

```bash
pi --name "00-orchestration"
```

在 Orchestration session 里澄清需求、收敛范围、切分开发 round。规划确认后用 `/fleet` 把每个 round 分发成独立 session；round 内按宿主分配 builder / reviewer：Web UI 内置工具可用时用 `subagent_spawn`，匹配角色模板优先 `delegate_task`；CLI 或无 Web UI 工具时用独立 `pi-subagents`。新增代码由 ponytail 做门禁。

`npm:pi-web-ui` 可选、默认不下发。治理同步会预览项目/全局 Dashboard 自动迁移；共享全局配置只有 `--apply` 才备份并写入，影响使用该配置的所有项目，详见 `Harness_manual.md`。

Owner 只在规划阶段介入。已有 baseline 后，清楚的 bounded task 直接执行并验证。
<!-- HARNESS:README:MANAGED:END -->

## ETF 前向机会台账

面向 A 股 ETF/LOF 及跨资产容器的前向机会台账：创建时冻结论点、证据与量化预期，持续追加观测，按预先锁定的规则评分，积累可验证的决策证据。

A prospective opportunity ledger for A-share ETFs/LOFs and cross-asset exposures. Freeze theses, evidence, and quantitative expectations at creation; append observations and score outcomes under precommitted rules to build a verifiable decision record.

当前提供三态台账及同页详情的隔离演示，独立评分、候选作废、出场信号及逐日推进复用现有领域代码。**完整产品尚未交付**：轮动页、证据到判断的工作流及部分评分复盘仍缺；`market` 是行情检查入口，不读取正式台账。正式台账仅有只读入口，研究与正式规则尚未放行。详见[产品完整性审计](operations/reviews/2026-10-06-product-completeness-audit.md)。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m src.web --port 8765
```

本机浏览器打开 `http://127.0.0.1:8765`。只查看正式台账可运行 `python -m src.web --mode readonly`（在已激活环境中）；正式库不存在时显示空态，不创建文件。启动、交互、隔离边界与复验详见 [可运行台账说明](docs/runnable-ledger.md)。

### 从这里接手

1. 读 `AGENTS.md` 和 [完整初始化文档](docs/project-intake/etf-opportunity-ledger.md)，尤其 §1 已证伪方向与 §3 研究纪律。
2. 读仓库权威 [卡片 schema](docs/etf-card-schema-v1.md)、[每日任务](docs/jobs-daily.md) 与 `docs/design/` 设计规范；初始化材料已导入，旧 Project 副本仅供参考。
3. 当前缺口与后续分工见[产品纠偏计划](operations/planning/2026-10-06-product-recovery-plan.md)；[首包计划](operations/planning/2026-10-06-parallel-data-and-product.md)保留为历史任务记录。正式数据应用、研究和规则启用仍需各自范围内的授权。

### 最小能力配置

| Package | 交付方式 |
| --- | --- |
| `npm:pi-web-access` | 项目声明，与 serenity_quant_research 一致 |
| `npm:pi-subagents@0.60.0` | 项目声明，与参考项目锁版一致 |
| `npm:pi-frontend-check@1.1.0` | 项目声明，与参考项目锁版一致 |
| `npm:@dietrichgebert/ponytail` | Harness 必需门禁，项目声明 |
| `npm:@narumitw/pi-fleet` | 当前服务器全局已声明，按 Harness 规则去重 |

项目不声明 `pi-web-ui`；服务器已有全局 Web UI 未改动，因此“不下发”不等于禁用全局 UI。只下发配置与模板，不安装或 vendor package，不复制参考项目的业务文件、认证信息或运行产物。换机器时需核对全局 Fleet；本次未验证 package 运行时。

初始化记录见 [bootstrap 记录](operations/work_logs/2026-09-25-bootstrap.md)。
