# Pi 上跑正式台账

路径按本机检出目录替换。下面用 `/opt/etf-ledger`。服务和 cron 都用这个目录里的 `.venv`。

## 1. 建正式库

只在这一步创建 `data/ledger.sqlite`。网页和每日作业发现库不存在会退出，不会自己建。

```bash
cd /opt/etf-ledger
.venv/bin/python -m src.ledger init --db data/ledger.sqlite
```

若这只库是用 R5 的 schema（v1.1-i）建的，拉到含 v1.1-j 的代码后补一次表。命令幂等，重复跑不重建、不丢已有行：

```bash
.venv/bin/python -m src.ledger migrate --db data/ledger.sqlite
```

新 `init` 直接就是 v1.1-j，不必再 migrate。这个文件留在服务器上，不提交。

## 2. 写口令

`/etc/etf-ledger.env` 只有一行，口令至少 16 个字符：

```bash
sudo install -m 600 /dev/null /etc/etf-ledger.env
echo 'LEDGER_WRITE_TOKEN=换成至少16个字符的口令' | sudo tee /etc/etf-ledger.env >/dev/null
sudo chmod 600 /etc/etf-ledger.env
```

## 3. 装网页服务

编辑 `deploy/ledger-web.service`：

- `WorkingDirectory` 和 `ExecStart` 里的 `/opt/etf-ledger` 改成检出目录。
- `--public-host <占位>` 改成这台机器对外的 IPv4。没有这一项时，服务拒绝监听 `0.0.0.0`。

```bash
sudo cp deploy/ledger-web.service /etc/systemd/system/ledger-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now ledger-web.service
sudo systemctl status ledger-web.service
```

浏览器打开 `http://<公网地址>:8765/`。右上角「登录记账」，口令就是 `LEDGER_WRITE_TOKEN`。登录后首页三栏下面有辅助入口「手填立卡」，地址是 `/new`。事件草稿的反馈在 `/events`，不登录也能看。

没加 `--write` 的 readonly 仍然完全只读。market 与 demo 的启动方式不变。

## 4. 装 cron

`deploy/ledger-daily.cron` 自带 `CRON_TZ=Asia/Shanghai`。周一到周五北京时间 21:30 跑一次，23:30 再跑一次兜底。中证 H00300 的当天收盘点位当晚才发布。两行都用 `/usr/bin/flock -n` 防止重叠。路径是 `/project/data_science/ETF_Opportunity_Ledger`。作业幂等，已处理的日子重跑不产生新行。每次运行后往当天的 `outputs/logs/daily-YYYYMMDD.log` 再追加一行 `exit=<退出码>` 和时间。

```bash
crontab deploy/ledger-daily.cron
crontab -l
```

作业是 `bash deploy/daily.sh`。它先 `git fetch origin events`：当天的 `events/<D>.json` 若在分支上，就复制到 `data/events/<D>.json`，并在日志记下 events 分支的 commit SHA 和文件 SHA256。D 与作业默认日期同一口径，是最近一个已收盘的 A 股交易日。拉取失败只写日志，接着仍跑 `python -m src.jobs daily --maintain-only --rules config/ledger-rules.json --events-dir data/events`。维护路径给在场卡写进场、每日行、出场和跟踪；事件驱动已按 D5 开启，合格草稿会在这一步锁卡。恐慌下轨保持关闭，不扫描研究池。

## 5. 看日志

每次运行追加到 `outputs/logs/daily-YYYYMMDD.log`（日期是服务器本地日期）。

```bash
tail -n 80 outputs/logs/daily-$(date +%Y%m%d).log
```

退出码 0 且 JSON 里有 `marked` 或当日报告，表示这一天记过了。没有在场卡时，交易日只更新行情并记 `processed_days`。

## 6. 手动补跑某一天

漏了一天就从缺口那天按顺序补，不要跳着跑。

```bash
cd /opt/etf-ledger
bash deploy/daily.sh --date 2026-09-30
```

行情已经在库里、只想重算台账时加上 `--no-update`。同一天再跑一遍结果不变。非交易日、或在场卡缺当天行情时，作业以非零退出，不把这一天标成已处理。
