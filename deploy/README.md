# Pi 上跑正式台账

路径按本机检出目录替换。下面用 `/opt/etf-ledger`。服务和 cron 都用这个目录里的 `.venv`。

## 1. 建正式库

只在这一步创建 `data/ledger.sqlite`。网页和每日作业发现库不存在会退出，不会自己建。

```bash
cd /opt/etf-ledger
.venv/bin/python -m src.ledger init --db data/ledger.sqlite
```

这个文件留在服务器上，不提交。

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

浏览器打开 `http://<公网地址>:8765/`。右上角「登录记账」，口令就是 `LEDGER_WRITE_TOKEN`。登录后首页「下一个」栏出现「立卡」，地址是 `/new`。

没加 `--write` 的 readonly 仍然完全只读。market 与 demo 的启动方式不变。

## 4. 核对时区，再装 cron

cron 的时刻按**服务器本地时钟**填写，不按网页里的台账时钟。

```bash
timedatectl | grep 'Time zone'
date '+%Y-%m-%d %H:%M %Z'
```

`deploy/ledger-daily.cron` 里的 `40 15` 表示本地 15:40，且只在周一到周五。本地时区是 `Asia/Shanghai` 时，这就是收盘 15:30 之后。本地时区不是上海时，把小时改成「本地时间已经过了上海 15:30」的那个钟点，再安装：

```bash
crontab deploy/ledger-daily.cron
crontab -l
```

作业是 `python -m src.jobs daily --maintain-only`。它不扫描、不生成候选，只给已经在场的卡写进场、每日行、出场和跟踪。规则文件保持全部关闭。

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
.venv/bin/python -m src.jobs daily --maintain-only --rules config/ledger-rules.json --date 2026-09-30
```

行情已经在库里、只想重算台账时加上 `--no-update`。同一天再跑一遍结果不变。非交易日、或在场卡缺当天行情时，作业以非零退出，不把这一天标成已处理。
