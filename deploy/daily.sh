#!/bin/bash
# 每个交易日：先拉取 events 分支上的当日草稿，再跑维护作业。
# 拉取失败只记日志，维护作业照跑。D 与作业默认日期同一口径（最近一个已收盘的 A 股交易日）。
set -u
ROOT="${LEDGER_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"
PY="${LEDGER_PYTHON:-$ROOT/.venv/bin/python}"
if [ -n "${LEDGER_PYTHONPATH:-}" ]; then
  export PYTHONPATH="${LEDGER_PYTHONPATH}${PYTHONPATH:+:$PYTHONPATH}"
fi

DAY=""
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  if [ "${args[$i]}" = "--date" ] && [ $((i + 1)) -lt ${#args[@]} ]; then
    DAY="${args[$((i + 1))]}"
  fi
done
if [ -z "$DAY" ]; then
  DAY="$("$PY" -c 'from src.jobs.__main__ import default_day; print(default_day().isoformat())')"
fi

if git fetch origin events; then
  AUTHOR="$(git log -1 --format='%an' origin/events)"
  EMAIL="$(git log -1 --format='%ae' origin/events)"
  echo "origin/events 最新提交作者 ${AUTHOR} <${EMAIL}>"
  if [ "$AUTHOR" = "Grok bot" ]; then
    if git cat-file -e "origin/events:events/${DAY}.json" 2>/dev/null; then
      mkdir -p data/events
      git show "origin/events:events/${DAY}.json" > "data/events/${DAY}.json"
      COMMIT="$(git rev-parse "origin/events")"
      SHA="$(sha256sum "data/events/${DAY}.json" | awk '{print $1}')"
      printf '{"commit":"%s","sha256":"%s"}\n' "$COMMIT" "$SHA" > "data/events/${DAY}.meta.json"
      echo "events 分支 ${COMMIT} 文件 sha256 ${SHA} 已复制到 data/events/${DAY}.json"
    else
      echo "origin/events 没有 events/${DAY}.json（当天没有合格事件时这是正常的）"
    fi
  else
    echo "origin/events 最新提交作者不是 Grok bot（${AUTHOR} <${EMAIL}>），不复制 events/${DAY}.json"
  fi
else
  echo "拉取 origin/events 失败，维护作业继续" >&2
fi

"$PY" -m src.jobs daily --maintain-only --rules config/ledger-rules.json --events-dir data/events "$@"
