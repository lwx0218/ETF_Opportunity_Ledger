# Pi R7 上线尝试：自检失败，已回滚

## Metadata

- Project: ETF_Opportunity-Ledger
- Task: R7 纯执行上线与失败回滚
- Date: 2026-10-20
- Owner: Faye
- Route: direct-execute
- Source of truth: Owner 本次 R7 上线指令，尤其第 6 步失败即恢复备份

## 结论

**R7 未上线；已恢复 R6。** 21:09:06 重启服务后立即进行首次 HTTP 检查，首页 curl 返回 000、进程退出码 7，不符合 HTTP 200 要求。按第 6 步停止后续上线并回滚，未重试 R7、未手动跑 daily.sh，未等待或运行 R7 两次晚间 cron。

systemctl status 当时为 active，采样仅在启动后约 90ms；后续 journal 中有正常启动地址输出，没有捕获到应用异常。因此此次可能是请求早于监听就绪，**不能据此断言 R7 产品故障**。本执行没有先等待 HTTP 服务就绪，这是执行检查的时序限制。未即兴修复或绕过失败。

## 版本与执行边界

- 部署目录：`/project/data_science/ETF_Opportunity_Ledger`。
- 拉取仅使用 `git fetch origin main events` 和 `git pull --ff-only origin main`；未获取 archive 分支。
- 拉取并检出目标 HEAD：`6628bf520099ca716ceaaf1ad9a9ed4b45b06816`；正常快进，无 market.sqlite 冲突，未还原行情改动。
- 回滚运行 HEAD：`4b130fa7bbcbd9252fded11f0cdd3b8016271aac`（detached HEAD），避免旧 schema 搭配新代码继续运行。main 引用仍保留已快进的目标提交。
- 未手工修改产品代码或规则开关，未运行 backfill、probe、V1，未读取或记录口令。
- 公网地址：`http://111.19.137.226:8765/`；本次未做 R7 公网浏览器检查。

## 备份、原始数据与恢复核对

备份：

- `data/ledger.sqlite.bak-2026-10-20`
- `data/market.sqlite.bak-2026-10-20`
- `outputs/crontab.bak-2026-10-20`

备份前两库 journal_mode 都为 delete，integrity_check 都为 ok。按要求 cp；原库与备份 SHA256 一致。以下为备份前基线：

```json
{
  "ledger": {
    "sha256": "89eac8c0439204575a11fa2ca92c95e48815487300ada21c33aa701af20e7833",
    "integrity_check": "ok",
    "tables": {
      "cards": 0,
      "daily": 0,
      "entries": 0,
      "evidence": 0,
      "ew_daily": 0,
      "exit_signals": 0,
      "exits": 0,
      "finals": 0,
      "fixed_sources": 60,
      "job_days": 2,
      "ledger_meta": 2,
      "source_loads": 1,
      "strength_scores": 0,
      "voids": 0
    }
  },
  "market": {
    "sha256": "51303b5f8b2053282e265e5c17e7d3bb29fbef1f399598b527d32c30506e2016",
    "integrity_check": "ok",
    "bars": [
      "2026-10-20",
      309618
    ]
  }
}
```

恢复时先停网页服务，恢复原 crontab，再用备份覆盖两库，检出 R6 后启动服务。回滚后两库 SHA256 与上述基线逐字相同；ledger 所有表逐一 count 与上述基线相同，无减少。market bars 仍为最大日期 2026-10-20、总行数 309618。原 cron 与恢复后 cron 用 cmp 核对一致。

迁移后的数据库 SHA256 与各表行数未在失败前采集，不补造该中间状态；已验证恢复后的完整基线。备份留在服务器，不提交。

## 迁移输出

第一次，退出码 0：

```text
data/ledger.sqlite：schema v1.1-j（原先 v1.1-i）

```

第二次，退出码 0：

```text
data/ledger.sqlite：schema v1.1-j（原先 v1.1-j）

```

第二次显示原先已是 v1.1-j；没有重复建库。回滚恢复的是原 v1.1-i 库。

## 服务状态与自检

R7 重启后的 status（仅去掉输出中的时区缩写）：

```text
● ledger-web.service - ETF 前向机会台账
     Loaded: loaded (/etc/systemd/system/ledger-web.service; enabled; preset: disabled)
     Active: active (running) since Tue 2026-10-20 21:09:06; 90ms ago
   Main PID: 673295 (python)
      Tasks: 1 (limit: 153717)
     Memory: 11.3M (peak: 11.3M)
        CPU: 83ms
     CGroup: /system.slice/ledger-web.service
             └─673295 /project/data_science/ETF_Opportunity_Ledger/.venv/bin/python -m src.web --mode readonly --write --host 0.0.0.0 --public-host 111.19.137.226 --port 8765

Oct 20 21:09:06 anolis systemd[1]: Started ledger-web.service - ETF 前向机会台账.

```

- 首次 `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/`：000，退出码 7。批命令随即停止。
- /rotation、/events、公网浏览器、手动 daily.sh：未执行，因前项失败停止。
- 拉取后只读核对 config/ledger-rules.json：事件驱动 enabled=true，恐慌下轨 enabled=false，符合目标；未修改。回滚代码后配置随 R6 恢复，不能声称 R7 开关仍生效。
- 恢复 R6 后 systemctl is-active：active；21:09:44 本地首页复核 HTTP 200。这是回滚验证，不是 R7 重试。

## cron 前后全文

通过 `crontab -e` 配合一次性非交互编辑器，只替换原台账 15:40 行。已有 CRON_TZ=Asia/Shanghai，不重复添加。新增两条逐字取自 deploy/ledger-daily.cron；其他行保留原样。失败后安装原备份恢复。

### 修改前（也是恢复后）

```cron
# BEGIN teardown-ingest (physical-first)
CRON_TZ=Asia/Shanghai
35 15 * * 1-5 cd /project/data_science/serenity_quant_research/api && (set -a; . /home/levi_luo/.config/teardown/runtime.env; set +a; /usr/bin/flock -n /project/data_science/serenity_quant_research/artifacts/runtime/ingest.lock /project/data_science/serenity_quant_research/api/.venv/bin/python -u -m app.ingest daily) >> /project/data_science/serenity_quant_research/artifacts/runtime/teardown-ingest.log 2>&1
15 */3 * * * cd /project/data_science/serenity_quant_research/api && (set -a; . /home/levi_luo/.config/teardown/runtime.env; set +a; /usr/bin/flock -n /project/data_science/serenity_quant_research/artifacts/runtime/ingest.lock /project/data_science/serenity_quant_research/api/.venv/bin/python -u -m app.ingest news) >> /project/data_science/serenity_quant_research/artifacts/runtime/teardown-ingest.log 2>&1
# END teardown-ingest

# 交易日、A 股收盘 15:30 之后跑一次。下面的 40 15 是服务器本地时区的分和时。
# 先核对时区再改：timedatectl | grep Time.zone    或    date +%Z
# 服务器本地时区若不是 Asia/Shanghai，把 15 改成「本地时钟走到北京时间 15:30 之后」的那个小时。
40 15 * * 1-5 cd /project/data_science/ETF_Opportunity_Ledger && mkdir -p outputs/logs && .venv/bin/python -m src.jobs daily --maintain-only --rules config/ledger-rules.json >> outputs/logs/daily-$(date +\%Y\%m\%d).log 2>&1

```

### 临时安装的 R7 cron（现已撤销）

```cron
# BEGIN teardown-ingest (physical-first)
CRON_TZ=Asia/Shanghai
35 15 * * 1-5 cd /project/data_science/serenity_quant_research/api && (set -a; . /home/levi_luo/.config/teardown/runtime.env; set +a; /usr/bin/flock -n /project/data_science/serenity_quant_research/artifacts/runtime/ingest.lock /project/data_science/serenity_quant_research/api/.venv/bin/python -u -m app.ingest daily) >> /project/data_science/serenity_quant_research/artifacts/runtime/teardown-ingest.log 2>&1
15 */3 * * * cd /project/data_science/serenity_quant_research/api && (set -a; . /home/levi_luo/.config/teardown/runtime.env; set +a; /usr/bin/flock -n /project/data_science/serenity_quant_research/artifacts/runtime/ingest.lock /project/data_science/serenity_quant_research/api/.venv/bin/python -u -m app.ingest news) >> /project/data_science/serenity_quant_research/artifacts/runtime/teardown-ingest.log 2>&1
# END teardown-ingest

# 交易日、A 股收盘 15:30 之后跑一次。下面的 40 15 是服务器本地时区的分和时。
# 先核对时区再改：timedatectl | grep Time.zone    或    date +%Z
# 服务器本地时区若不是 Asia/Shanghai，把 15 改成「本地时钟走到北京时间 15:30 之后」的那个小时。
30 21 * * 1-5 cd /project/data_science/ETF_Opportunity_Ledger && mkdir -p outputs/logs && /usr/bin/flock -n /project/data_science/ETF_Opportunity_Ledger/outputs/logs/daily.lock bash -c 'bash deploy/daily.sh >> outputs/logs/daily-$(date +\%Y\%m\%d).log 2>&1; ec=$?; echo "exit=$ec $(date +\%Y-\%m-\%dT\%H:\%M:\%S)" >> outputs/logs/daily-$(date +\%Y\%m\%d).log; exit $ec'
30 23 * * 1-5 cd /project/data_science/ETF_Opportunity_Ledger && mkdir -p outputs/logs && /usr/bin/flock -n /project/data_science/ETF_Opportunity_Ledger/outputs/logs/daily.lock bash -c 'bash deploy/daily.sh >> outputs/logs/daily-$(date +\%Y\%m\%d).log 2>&1; ec=$?; echo "exit=$ec $(date +\%Y-\%m-\%dT\%H:\%M:\%S)" >> outputs/logs/daily-$(date +\%Y\%m\%d).log; exit $ec'

```

## 当晚 21:30 / 23:30

两条新 cron 均在 21:30 前撤销并恢复原 cron，**不会运行**；退出码不适用，没有对应 exit= 行。未手动补跑或伪造两条退出码。当晚最终 daily 日志末 40 行与 H00300 查询未采集：任务已按第 6 步提前终止，不能以 R6 下午日志冒充 R7 晚间结果。

## 交付

只提交本文至 `ops/pi-r7-2026-10-20`，报告基于目标 6628bf5，只有一个文档增量；部署运行目录保持 R6。未推 main/dev。请 Owner 决定是否授权重新上线；本次不报告「R7 已上线」。
