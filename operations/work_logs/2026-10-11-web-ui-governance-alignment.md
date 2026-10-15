# Web UI 治理合同定向对齐

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: 按 Owner 授权对齐当前 Web UI 原生规划、执行与 review 路由
- Date: 2026-10-11
- Owner: Faye
- Route: direct-execute
- Source of truth: AGENTS.md；Owner 本次授权；Harness 上游提交 `a0555942fca73027d0e46f975db1382ad3e54163`

## Summary / Changes

- 上游已更新：完整核对 Harness_Workspace 的 starter `AGENTS.md`、`operations/work_logs/2026-09-27-web-ui-task-routing.md` 与 `GOVERNANCE_CHANGELOG.md`；当前 starter 文本与上述提交完全一致。
- 本地修改前仍是无条件 fleet 分发及缺 Web UI 工具可回落的旧版合同。虽有 `.pi/.harness-manifest.json` 交付清单，但它没有最新同步版本证据，不能据此声称本地此前已更新到 `a055594`。
- 此次仅将 `AGENTS.md` 的 managed 块定向同步到指定上游，**不是 `harness.sh` 全量 apply**。owned 新增当前执行宿主：主会话规划切任务，Web UI 内置 implement/review 分工、独立只读 reviewer；缺工具报告阻塞，不经 fleet / 独立 pi-subagents，不强制另开 CLI 规划会话。Owner 规划确认与 ponytail 保持。
- 初始化不下发项目级 Web UI 仅为包声明边界，不禁用当前 Web UI；包存在不等于执行路径。其余 manual / `.pi/` 等旧提示本次未同步，冲突时以 `AGENTS.md` 为准，不激活旧流程。
- 仅改 `AGENTS.md` 与本记录；未触碰业务、数据库、研究规则、包配置、共享配置或 Harness 上游，未安装、停止服务、处理网络/证书、运行 apply、commit 或 push。

## Validation

- `git diff --check`：通过。
- Python 提取 managed marker 块，与 `git show a0555942fca73027d0e46f975db1382ad3e54163:assets/templates/harness-pi-starter/AGENTS.md` 精确比较：PASS。
- 以本地修改前 `HEAD:AGENTS.md` 为基线，移除新增宿主短节并逆向还原唯一包声明澄清后，owned 块全文精确比较：PASS；研究纪律、数据约束与其它产品条款未变。

## Next Steps

交回主会话独立只读复核；本记录不代替 review 结论。提交与推送由主会话按 Owner 授权处理。
