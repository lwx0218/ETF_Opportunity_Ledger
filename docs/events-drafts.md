# 事件草稿

## Metadata

- Project: ETF_Opportunity-Ledger
- Document type: reference
- Status: active
- Owner: Faye
- Last updated: 2026-10-19
- Source of truth: 本文件。字段与 `src/jobs/rules.py` 的 `event_candidates` 一致。

## 谁交、交到哪

事件卡起草暂由 Grok bot 负责（D6）。每个交易日它把当天的草稿推到本仓库的 `events` 分支，路径是 `events/YYYY-MM-DD.json`。服务器在每日作业前拉取这个分支。

草稿进入 `events-dir` 并通过校验，即视为确认（D5）。Owner 不逐张点确认。校验失败的整条退回，不锁卡。

## 截止与改动

- 截止时刻是交易日 D 的北京时间 15:25。过了这个时刻再推，赶不上当天的作业。
- D 日文件推送后不得再改。作业记下的第一次结果不覆盖。
- 当天没有合格事件就不推文件。没有文件是正常的，不是故障。

## 文件

一个 JSON 数组。每一项是一张事件卡的草稿：

| 字段 | 要求 |
|---|---|
| `container` | `data/universe.csv` 的 `theme` 列，原样照抄，不写代码、不写简称。例：`地产`（该行 `theme_id` 是 T30，执行 ETF 是 512200） |
| `thesis` | 1–80 字。超过不截断，整条退回 |
| `evidence_status` | `已检索无证据` 或 `有证据`，并且和 `evidence` 的条数一致 |
| `evidence` | 数组。`已检索无证据` 时必须是 `[]`；`有证据` 时至少一条。每条含 v1.1-d 的 8 个字段：`source_id`、`published_at`、`summary`、`url`、`first_seen_at`、`available_at`、`snapshot_path`、`snapshot_sha256` |
| `agent_score` | `{score, reason}`。`score` 是 0–5 的整数，`reason` 非空 |
| `expectation` | `{horizon_days, target_excess_pct, benchmark}`。`horizon_days` 是正整数，`target_excess_pct` 是数，`benchmark` 只能是 `等权组合` 或 `沪深300` |
| `thesis_invalidation` | `{source_id, deadline, statement}`。三项都要有。`source_id` 必须在 `docs/etf-fixed-sources-v1.csv` 里，而且是 A 或 B 级 |

`source_id` 不在固定源清单、或等级是 C，整条退回，不锁半张卡。

`snapshot_path` 填 `archive/grok-raw` 分支里的路径 `events-snapshots/<D>/<文件名>`。快照要在草稿推送前先推到这个分支。页面只给以 `events-snapshots/` 开头的路径做链接。

## 能通过校验的样例

```json
[
  {
    "container": "地产",
    "thesis": "房地产投资增速回升，统计局月报确认",
    "evidence_status": "有证据",
    "evidence": [
      {
        "source_id": "CN-NBS-MONTHLY",
        "published_at": "2026-09-30T10:00",
        "summary": "全国房地产投资月报显示开发投资降幅收窄",
        "url": "https://www.stats.gov.cn/sj/zxfb/",
        "first_seen_at": "2026-09-30T10:05",
        "available_at": "2026-09-30T10:00",
        "snapshot_path": "events-snapshots/2026-09-30/nbs-realestate.txt",
        "snapshot_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      }
    ],
    "agent_score": {"score": 4, "reason": "统计局房地产投资数据，方向与论点一致"},
    "expectation": {"horizon_days": 20, "target_excess_pct": 3.0, "benchmark": "沪深300"},
    "thesis_invalidation": {
      "source_id": "CN-NBS-MONTHLY",
      "deadline": "2026-10-30",
      "statement": "下一期房地产投资再度走弱即失效"
    }
  }
]
```

## 会被退回的样例

论点超过 80 字，整条不入账。下面这条论点是 88 字。文件里其他合格草稿不受影响。

```json
[
  {
    "container": "地产",
    "thesis": "这是一段故意写过八十个字的论点，用来说明超长论点会被整条退回而不是被截断后入账，后面这些字只是为了把长度撑过上限。再补上这些字，长度才会真正超过八十，整条退回而不是截断后入账。",
    "evidence_status": "已检索无证据",
    "evidence": [],
    "agent_score": {"score": 2, "reason": "只有标题"},
    "expectation": {"horizon_days": 20, "target_excess_pct": 3.0, "benchmark": "沪深300"},
    "thesis_invalidation": {
      "source_id": "CN-NBS-MONTHLY",
      "deadline": "2026-10-30",
      "statement": "到期未兑现即失效"
    }
  }
]
```

退回理由的原文会出现在 `/events`。常见的还有：缺 agent 评分或理由、`evidence_status` 和证据条数不一致、`source_id` 不在固定源清单。
