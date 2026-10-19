# archive prep: grok-nav-shares-20261019

准备写入孤儿分支 `archive/grok-raw` 的批次包（本目录尚未 git push）。

## 源目录
`/workspace/grok-nav-shares-20261019`（本机 /workspace）

## 内容
- `raw.zip`（或分卷 `raw.zip.NNN`）：源批次目录全量文件（含 README、manifest、raw/、samples/ 等，原样不改）
- `SHA256SUMS`：zip 本体 + 解压后每个文件的 SHA256 与字节数

- 源 manifest: `grok-nav-shares-20261019/manifest.csv`（已打入 zip）

## 规模
- 源合计：28428430 bytes (27.11 MB)
- zip：3194351 bytes (3.05 MB)
- 文件数：469
- 生成时刻（Asia/Taipei）：2026-10-19 21:53:59

## 规则遵守
- 不修改原件内容；不 force；单批未超 1GB。
