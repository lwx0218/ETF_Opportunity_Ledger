# 项目状态（先读这个）

## 基线
- main：4b130fa7bbcbd9252fded11f0cdd3b8016271aac（只含到 R5 的文档；R7 未合入）
- dev 内容：de1618a0cac548a5098df395214801f45713f1cc（R7 收尾：B1 拥挤排名改到 37 个执行 ETF 横截面，B2 详情逐条列出冻结证据，B3 用创建日基准复权价避开除息误出场；D4–D6 仍在这条上。状态说明在其后的提交）
- events：9dff8292838f5d6f9f2b8b2f40bdd7535b4c7b1e（孤儿分支，只有 README 和空的 events/）
- 行情库：data/market.sqlite，87 序列 / 309,275 行，末日 2026-09-30；38 只执行 ETF 腾讯日线全量；CSI 全收益 18 个容器，仅价格指数 15 个，无研究序列 3 个（T16 / T36 / T38）；回填在 Cursor 沙箱完成（operations/work_logs/2026-10-11-csi-research-backfill.md），Pi 服务器 IP 对 csindex 仍 403
- 正式台账 data/ledger.sqlite：服务器上已建
- 启动：.venv/bin/python -m src.web --port 8765（demo）；--mode readonly；--mode readonly --write（须 LEDGER_WRITE_TOKEN，至少 16 字符）；--mode market
- 测试：mkdir -p outputs && .venv/bin/python -m unittest discover -s tests -t .

## 现在能看到什么
- /：六问首页。demo 有合成卡时 h1 为「1 笔正在验证，2 笔等待进场。」，三栏是黄金（过去）、半导体（当下）、红利与国债（候选）。无正式卡时（market，以及正式库不存在的 readonly）2026-09-30 执行 ETF：h1「37 个容器里 3 个处于可进态，没有在跑的判断。」下一个栏是地产 512200 / 回踩 / 名次 3 / +12.1% / +0.9 ATR；其余可进态为银行 512800、创新药 159992。今天不碰是 0 个不利，并写明 25 个形态可用、12 个不可用。规则段写前向样本不足。readonly 的页脚和模式标签是「正式台账 · 只读」；market 是「真实观察 · 只读」。规则标签现在是「事件驱动」（D5 已打开；形态观察仍不入账）。首页不再放 37 容器平铺、L1–L4 和行情登记长表
- /market：与 market 模式首页相同，页脚上方保留「辅助检查 · 行情登记」。顶栏仍是机会 / 轮动；面包屑为 ETF 前向机会台账 › 机会 › 行情检查。`?mode=market` 的旧链接仍打开同一首页，但不渲染登记表
- /rotation：37 容器 × 12 周热力格。颜色是近 1 月相对沪深300全收益的超额，格内是当周名次，小字是形态。格子颜色是 CSS 类（heat-up / heat-down），不写内联 style。2026-09-30 执行序列：8 个分组，h1「纳指科技最强，原油和地产跟着。」，超额 +18.9%。点一格后，焦点段在格子下方。研究序列横截面不完整（10/37），不排名次。L1–L4 仍只写在本文件，不占轮动页
- 卡片详情在价格图之前直接写出「当时为何触发」和「现在按什么条件退出」（创建失效位、当前止损、论点失效、待成交信号分开）。「判断从何而来」逐条列出冻结证据：固定源名称和等级、published_at、available_at、first_seen_at、summary、可点的 url、可截短的 snapshot_sha256。snapshot_path 以 events-snapshots/ 开头时，链到 archive/grok-raw 上的同一路径。Agent 分和理由在这段旁边，抽查在这段下方
- 正式立卡：`python -m src.ledger init --db data/ledger.sqlite` 显式建库（新库已是 v1.1-j）。已有的 v1.1-i 库用 `python -m src.ledger migrate --db data/ledger.sqlite` 补上 `spot_checks` 和 `event_drafts`，不重建、不丢行。网页和每日作业都不自动建库。readonly 加 `--write` 且设置 `LEDGER_WRITE_TOKEN` 后，右上角「登录记账」（HttpOnly、SameSite=Strict，12 小时）。手填表单仍在 `/new`，只接受事件驱动卡；它从首页「下一个」栏的主按钮撤到三栏下面的辅助入口「手填立卡」。未登录不出现。论点、证据、量化预期、失效位提交即冻结。详情直接显示 agent 分和理由，没有 owner 评分表单，也没有「待独立评分 / 已过期」。登录后可抽查：结论只有「无误 / 有误」加一句说明，写入 `spot_checks`，不改卡、不自动作废。首页显示「未抽查 N 张」。详情页仍可作废、作废并重建、手动出场信号。手动卡不生成 agent 分。不加 `--write` 的 readonly 仍完全只读
- `/events`：不登录也能看。按日期列出当天草稿是锁卡还是整条退回、退回理由原文、对应的 events commit SHA 和文件 sha256
- 每日维护：`bash deploy/daily.sh`（cron 为北京时间周一到周五 21:30，23:30 兜底。中证 H00300 的当天收盘当晚才发布）。先 `git fetch origin events`（只拉这个分支）。日志记下最新提交的作者名和邮箱。作者名正好是「Grok bot」且当天有 `events/<D>.json` 才复制到 `data/events/<D>.json`，并记下分支 commit 和文件 sha256；作者不对就不复制、写日志，维护作业照跑。拉取失败同样只写日志。作业是 `python -m src.jobs daily --maintain-only --rules config/ledger-rules.json --events-dir data/events`。事件驱动已开启，合格草稿在这一步锁卡；恐慌下轨保持关闭，不扫描研究池。拥挤排名和每日 `rs_1m_rank` 都在 37 个执行 ETF 上算，与首页观察同一口径；断档行的 `rs_1m` 先置空、不占名次。台账只给在场卡和合格草稿写行。在场卡和当天草稿涉及的执行 ETF 会多取一次腾讯 qfq，推出现金分红，卡片价格按创建日基准复权（口径在 `docs/jobs-daily.md` 末尾）；锁死的失效位、1R、参考价不回改。开盘相对前收跳空超过 5% 又推不出分红的，当天按 data_hole，不做出场决定。在场卡仍写进场、每日行、失效位与移动止盈、待成交出场、跟踪与到期评分。没有在场卡、也没有当天草稿时，只更新行情并 mark_processed。默认增量范围是 37 个执行 ETF 与 H00300；中证请求至少间隔 1.5 秒，403 等 90 秒重试一次，再失败则非零退出且不覆盖已有数据。同一交易日重跑不改变已记下的草稿结果。Pi 步骤在 `deploy/README.md`
- 无正式卡时，首页观察栏的规则标签是「事件驱动」，不再写「规则未启用」。形态观察仍不入账，不开形态突破，A7 不变
- 研究序列切换：37 个容器中 34 个有合格相对强弱（缺 T16/T36/T38）；research_ready 仍为 false

## 当前 round
- R7 已收尾，待评审。未合入 main。内容是 de1618a0cac548a5098df395214801f45713f1cc。评审通过前不合入 main。R6 已于 4b130fa 部署在服务器

## 待办（按顺序）
1. R6 已于 4b130fa 部署在服务器。连续 5 个交易日计数仍待完成。代码已对中证请求间隔 1.5 秒，403 等 90 秒重试一次；若服务器 IP 仍被拒绝，作业非零退出且不覆盖已有行情。Grok bot 本身不在本仓库，它要按 `docs/events-drafts.md` 把草稿推到 `events` 分支，快照先推到 `archive/grok-raw` 的 `events-snapshots/<D>/<文件名>`
2. 份额折算：开盘跳空超过 5% 又推不出分红时，只把当天标成 data_hole、不做出场决定。下一交易日仍用新的价格水平去比锁死止损，可能写出场信号。本次不把冻结延伸到之后的交易日
3. backlog：四触发器里只开了事件驱动（恐慌下轨关，形态突破未接）；反事实；NAV/份额/成交额；V1 放行；A7。校准只剩 agent 一条曲线，还没有足够的已结卡。不拆分行情库，不换 T12 的基金，不增加新的草稿校验规则

## 对照原型，这轮没做完的
- `prototypes/home/` 的三栏和详情方向已在产品里；原型数字停在 2026-09-14，不是现网。Direction A/B/C 只是留档
- `prototypes/rotation-panel/` 是 17 个容器的静态快照。产品轮动页是 37 个容器；研究序列横截面仍不完整（10/37），`research_ready` 仍为 false
- 服务器上的正式台账 `data/ledger.sqlite` 已建
- V1 未运行（prereg §13 待填）。NAV、份额、成交额未做

## 原型与设计
- docs/design/teardown-design-rules-v3.md、docs/design/teardown-tokens.css
- prototypes/home/*.dc.html、prototypes/rotation-panel/
