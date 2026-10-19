# AGENTS.md

<!-- HARNESS:MANAGED:START -->
## Harness Managed Execution Contract

本分区由 Harness 管理（`harness.sh` 会整体替换）。项目产品、领域、安全和运行时规则请写在 `PROJECT:OWNED` 分区。

### Authority

- 本文件是模型执行合同；冲突时优先于 README、human manual、`.pi/` 和历史 evidence。
- `.pi/` 只是 capability layer，不是 policy authority。

### Owner-Facing Language

面向 Owner 的聊天总结、交付说明、状态报告和控制门提示默认使用中文。文件名、命令、代码标识、协议字段和必要原文引用可保留英文。

### 交付主线

1. **Orchestration session** — `pi --name "00-orchestration"`，澄清需求、收敛范围、切分开发 round。此阶段不写业务代码。
2. **按启用路径分发** — 项目启用 `pi-web-ui` 时，round/任务分发直接使用 Web UI 内置 `subagent_spawn`，匹配角色模板优先 `delegate_task`；不经过 `pi-fleet` 或独立 `pi-subagents`，不先 `session_spawn`。已启用但内置工具不可用时，明确报告能力阻塞，不静默回落。仅未启用 Web UI 的 CLI 路径用 `/fleet` 为每个 round `session_spawn` 一个独立开发 session，round 间通过 `session_bus` 通信。
3. **Subagents 执行** — builder / reviewer 沿用第 2 步的路径：Web UI 使用内置工具，CLI 使用独立 `pi-subagents`（角色定义在 `.pi/agents/`）。不为兼容升级或 patch 包。builder 实现，reviewer 只读复核并给出 `approve` / `approve_with_follow_up` / `return_to_planning`；只读是角色约束，不是运行时沙箱承诺。
4. **ponytail 门禁** — 新增代码由 ponytail 做准入判定。

**Owner 只在第 1 步介入**，确认规划与 round 划分。round 内的内容复核由 reviewer subagent 出结论，代码准入由 ponytail 判定。**不得把逐轮 review 结论推回 Owner**；只有 reviewer 与 ponytail 都无法结论、或结论与 round 目标冲突时，才升回 Orchestration session。

不存在需要 Owner 逐条批准的 formal mode、fixed Round ledger、independent review gate 或 session handoff 合同。历史 evidence 不激活任何旧流程。

### Round 的定义

round 是 Orchestration 阶段切出的**任务切分单位，不是验收单位**。不需要 ledger、固定编号规则或跨 round 状态机。

一个 round 说清楚四件事即可：目标、改动面、验证方式、完成判据。

### 默认模式

理解请求、必要时少量澄清、执行 bounded change、运行相称验证、用中文总结。复杂、跨文件或已有历史 evidence 不会自动加重流程。

Plan 用于澄清目标、范围、风险、验证和 round 切分，不产生额外审核义务。

### First Session

Greenfield 或无 baseline 的项目，首次从项目根运行：

```bash
pi --name "00-orchestration"
```

Owner 批准规划前只允许 read/infer/discuss 和 chat Plan Preview；不得修改业务 code/config、创建 durable evidence、安装依赖或执行破坏性操作。接受 recommended defaults 不等于批准规划。

### Routing

- `direct-execute`：清楚 bounded task。
- `plan`：目标、范围、风险、验证或 round 切分需要澄清。
- `review-only`：只要 findings。
- `needs-package`：确有能力缺口。

skills 和 domain modeling 是按需能力，不是默认关卡。

### 治理层边界

产品 round 不修改治理层（`.pi/`、`AGENTS.md`、Harness 下发的文件）。发现治理层问题时单独提出，不在产品 round 里顺手改。

`.pi/extensions/` 下不放 vendored extension 源码。能力通过 `.pi/settings.json` 的 `packages` 声明获得；按 npm 包名做全局去重，但保留项目显式锁版、对象资源过滤及自定义字段。

`pi-fleet` / `pi-subagents` 仍默认下发供 CLI 使用；`npm:pi-web-ui` 可选、默认不下发。包已安装或声明不等于当前启用的执行路径；启用 Web UI 不卸载 CLI 包，也不改变安装或同步行为。`harness.sh` 自动检测项目及执行环境全局的已知 Dashboard 声明并迁移为 Web UI；共享全局配置仅在 `--apply` 且项目检查通过后备份、原子替换。只清理准确关联的 Dashboard bridge，不卸载包、不停止服务、不删除会话。`--no-global-dedup` 不关闭迁移检测。

### Document And Evidence Governance

新增或实质更新 Markdown 时先判定承载位置：

- `docs/**`：长期说明、manual、reference、project intake 与导航；kebab-case 文件名和最小 Metadata。
- `operations/**`：事件型 durable evidence；`YYYY-MM-DD-<slug>.md` 日期前缀与任务型 Metadata。

只有进入 Plan、round 切分、合同/bootstrap 变更或需要保留 review trail 时，才写 durable evidence。详细格式见 `docs/manual/document-governance.md`。

### Evidence And Safety

高风险、破坏性、外部授权、scope 改变或验证失败时 fail closed 并询问 Owner。不自动 push。
<!-- HARNESS:MANAGED:END -->

<!-- PROJECT:OWNED:START -->
## 项目合同 · ETF_Opportunity-Ledger

### 执行者与交接（2026-10-11 起，Owner 批准 D1–D6）

- Claude（规划 session）：规划、切 round、出 UI 方向稿（单文件 HTML）、评审每次推送（用真实渲染截图对照原型，不以测试数代替）。不改代码。
- Cloud Agent（主力开发）：在 dev 分支开发并推送；每轮 python -m unittest discover -s tests -t . 通过再推；UI 改动附深浅两套真实渲染截图；每轮推送后更新 docs/status.md 的基线与待办。合并到 main 要 Owner 点头。
- Pi（服务器）：部署 Owner 指定的提交、跑作业、补数据、核原件；执行记录写 operations/work_logs/。Pi 不改产品代码。
- 任务只写四件事：目标、改动面、验证、完成判据。不再为 round 写 operations/planning/、operations/reviews/ 文档；历史文档只作参考，不激活旧流程。docs/status.md 是唯一的现状与待办入口，先读它。
- 页面观察口径（D1）：轮动页、首页观察、横截面排名默认使用 37 个容器的执行 ETF（universe.csv 的 execution_fund_code，腾讯 raw 日线），基准 H00300；CSI 全收益研究序列只用于正式研究/回测，页面上作为可选切换。页面注明「ETF 价格，与指数差异按年 1% 打折」。
- 无正式卡时（D3）：首页「未来」栏显示观察候选（已有形态状态/指标处于可进态的容器），明确标注「观察 · 未入账 · 规则未启用」，不创建卡、不开规则，A7 不变。
- 每轮交付由开发与编排方对照原始产品目标（docs/status.md 与 prototypes/ 原型）验收，给出可复现证据（真实渲染、端到端运行、对照数字），主动指出未完成项；不以「子任务完成」或「测试通过」代替对目标的核对。简单任务直接执行并验证，不因此加重流程。
- D4：取消 owner 盲分。`evidence_strength` 只保留 agent 一栏，校准只画 agent 一条曲线。历史 owner 字段和表保留，不再写入。
- D5：事件卡由起草 agent 检索、校验后自动入账。Owner 不逐张确认，只抽查。抽查只追加记录，不改卡、不自动作废。
- D6：事件卡起草暂由 Grok bot 负责。它每个交易日把草稿推到仓库的 `events` 分支；服务器在每日作业前拉取。

### 目标与必读资料

- Owner：Faye；中文名：ETF 前向机会台账。产出可验证的决策流程和前向证据，不以历史曲线优化为目标。
- 接手前完整阅读 `docs/project-intake/etf-opportunity-ledger.md`，尤其 §1、§3；其研究纪律、数据陷阱、设计约束和禁令是本项目合同的一部分。
- 八份权威文档来自 claude.ai Project「QTradeResearch」，已于 2026-09-25 按 intake §4.1 同名导入 `docs/`；先读 `docs/etf-card-schema-v1.md`。自 A6 起仓库 `docs/` 为唯一权威版本，Project 同名文档只是只读快照；不得根据摘要补造 schema、状态机、固定源清单或研究规则。
- 初始化仅授权治理骨架、文档与一次推送；业务实施以 Owner 2026-09-27 批准的 A1–A7 / C（`operations/planning/2026-09-27-orchestration-input.md` 决定栏）与 `operations/planning/2026-09-29-replan-three-lanes.md` 为准。任务 0 已收口为 `data/universe.csv` v1（2026-09-29）；任务 1–6 按 replan 的三条线分包推进；可选任务 7 仍延后。intake §10 五项已由 A1–A5 决定。缺失材料或决策影响当前任务时停止该任务，不猜测。

### 不可协商的研究纪律

- 不重做 intake §1 已关闭方向，不换参数重跑；历史结论为 Owner 提供，本次 bootstrap 未复验。
- 结果盲机械选样；证据仅来自预先声明的固定源且有硬发布日期；无未来视角，诚实登记已看过的数据（含零模型和描述性统计）。
- 回测前完成预注册（假设、信息、参数、验收、失效场景）；冻结样本外只跑一次。失败如实记录并关闭；新尝试须另起版本、注明尝试次数及证据折扣，不得静默调参。
- 回测用含分红再投的后复权；知识可以跨样本，数据不可以。新自由度上限约 4 个，优先相对量；禁机器学习、因子合成、超参数或网格搜索、看到结果后加变量。
- 按 R 倍数分布评估，必须报告去掉最好 1/2/3 笔后的期望；不以胜率或夏普作为评价指标。双基准为等权组合与沪深300，不用标的自身买入持有。
- 单标的与横截面结论不得互相冒充。不做空、不加杠杆、不做日内。

### 数据与台账约束

- 指数逐个核实代码、起始日期、价格/全收益口径；核不到的主题剔除，不用近似指数替代。黄金、原油、海外、国债、现金是一等容器。
- 结论必须声明 intake §4.2 的四项数据陷阱：主题指数回填（宽基行业对照优先）、指数与 ETF 差异（按每年 1% 打折）、腾讯减法 qfq（不得直接算收益率）、价格/全收益指数混用。新增数据获取方式必须补记；服务器接口尚未验证。
- 卡片创建时冻结论点、证据、量化预期与失效位；冻结字段在存储层强制不可修改，后续仅追加观测。修正只能作废重建并用 `supersedes` 引用；作废卡保留并计入分母，不事后增改证据。
- 评分只选固定菜单；允许校准的是 `evidence_strength` 换算表，不是打分方式。预定审查触发器只能得出「继续 / 停止 / 重开新版本」，没有「微调」。
- z 仅使用过去 20 个已完成月末收盘；1R = 入场价 − 失效位。细节以完整 schema 和预注册为准，不自行补参数。

### 交付边界

- 任务顺序遵循 intake §7：先核对 universe，再数据、存储、指标、每日任务、面板、评分。可选任务 7 延后，先预注册，只做描述；无区分度就停止，不进入回测。
- UI 必须遵守 Teardown design-rules v3 / tokens.css 和 intake §8；设计资产已导入 `docs/design/`，不以粗糙原型替代。过去 / 当下 / 未来三态、深色优先、无阴影卡片容器，不做「如何使用」说明页。
- 初始化时不下发项目级 `pi-web-ui` 是包声明边界，不等于禁用当前 Pi Web UI；不修改共享全局配置；package 声明不是已安装或运行验证的证明。
- 密钥、认证信息、依赖缓存、`outputs/` 重型产物与回放库不入 Git；行情库 `data/market.sqlite` 与台账库 `data/ledger.sqlite` 按 `operations/planning/2026-09-29-replan-three-lanes.md` §11 入 Git（白名单见 `.gitignore`；提交前无热日志、`integrity_check = ok`，只在检查点 `VACUUM`）；保留轻量文档、清单及必要小样例。业务源码与运行数据只落本项目，不放进 Harness_Workspace。
<!-- PROJECT:OWNED:END -->

## Cursor Cloud specific instructions

- 默认镜像要先安装 `python3.12-venv`，否则 `python3 -m venv` 因缺少 ensurepip 失败。随后在仓库根执行 `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt`。
- 跑测试前执行 `mkdir -p outputs`。`outputs/` 被 gitignore；目录不存在时 `tests/web/test_api.py` 里指向 `ROOT / "outputs"` 的临时库会失败。测试：`.venv/bin/python -m unittest discover -s tests -t .`。前端语法：`node --check src/web/static/app.js`。
- 演示服务：`.venv/bin/python -m src.web --port 8765`，监听 `127.0.0.1:8765`。非本机地址要同时给出明确的 `--public-host`，以及 `--demo-only` 或 `--mode market`。演示目录放在 `outputs/`。启动与操作路径见 `docs/runnable-ledger.md`。
