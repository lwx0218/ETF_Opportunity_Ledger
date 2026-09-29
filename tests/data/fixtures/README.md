# 数据层 fixtures

这些响应是**按接口格式构造的**，不是真实录制：写 P1 时 Claude Code 云端环境对行情域名出网被拒（HTTP 403）。
格式依据：中证 `perf/index-perf` 字段名取自 akshare `stock_zh_index_hist_csindex` 源码；东财 K 线、Yahoo chart、
stooq CSV 取自 serenity_quant_research（physical-first）`api/app/ingest/quotes.py` 的解析；腾讯 `fqkline` 行格式见 intake §5；
EIA 为 API v2 `seriesid` 入口的文档格式。

首次在能出网的机器上运行 `python -m src.data probe --record outputs/data/recorded/` 后，应挑每个源一份真实响应替换这里的文件，
并重跑 `python -m unittest discover -s tests -t .`；解析若与真实格式不符，以真实响应为准修改 `src/data/sources.py`。
