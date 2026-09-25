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
2. **pi-fleet 分发** — `/fleet` 为每个 round `session_spawn` 一个独立开发 session；round 间通过 `session_bus` 通信。
3. **Subagents 执行** — round 内分配 builder / reviewer：Web UI 内置工具可用时用 `subagent_spawn`，有匹配角色模板时优先 `delegate_task`；CLI 或无 Web UI 工具时用独立 `pi-subagents`（角色定义在 `.pi/agents/`）。不要求 Web UI 经 pi-subagents，不为兼容升级或 patch 包。builder 实现，reviewer 只读复核并给出 `approve` / `approve_with_follow_up` / `return_to_planning`；只读是角色约束，不是运行时沙箱承诺。
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

`pi-subagents` 仍默认下发供 CLI 使用；`npm:pi-web-ui` 可选、默认不下发。`harness.sh` 自动检测项目及执行环境全局的已知 Dashboard 声明并迁移为 Web UI；共享全局配置仅在 `--apply` 且项目检查通过后备份、原子替换。只清理准确关联的 Dashboard bridge，不卸载包、不停止服务、不删除会话。`--no-global-dedup` 不关闭迁移检测。

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

### 目标与必读资料

- Owner：Faye；中文名：ETF 前向机会台账。产出可验证的决策流程和前向证据，不以历史曲线优化为目标。
- 接手前完整阅读 `docs/project-intake/etf-opportunity-ledger.md`，尤其 §1、§3；其研究纪律、数据陷阱、设计约束和禁令是本项目合同的一部分。
- 八份权威文档来自 claude.ai Project「QTradeResearch」，按 intake §4.1 同名导入 `docs/`；先读 `docs/etf-card-schema-v1.md`。初始化时尚未导入，不得根据摘要补造 schema、状态机、固定源清单或研究规则。
- 初始化仅授权治理骨架、文档与一次推送，不代表批准业务实施规划。任务 0–7 尚未开始；§10 五项均未决，建议不得当作已批准默认值。缺失材料或决策影响当前任务时停止该任务，不猜测。

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
- UI 必须遵守 Teardown design-rules v3 / tokens.css 和 intake §8；设计资产待导入，不以粗糙原型替代。过去 / 当下 / 未来三态、深色优先、无阴影卡片容器，不做「如何使用」说明页。
- 本次不下发项目级 `pi-web-ui`，不修改共享全局配置；package 声明不是已安装或运行验证的证明。
- 密钥、认证信息、依赖缓存、数据库、批量行情和重型输出不入 Git；保留轻量文档、清单及必要小样例。业务源码与运行数据只落本项目，不放进 Harness_Workspace。
<!-- PROJECT:OWNED:END -->
