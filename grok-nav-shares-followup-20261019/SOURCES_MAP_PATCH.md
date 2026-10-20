# sources_map 补丁说明（501018 / 511880）

## 501018
- 日频份额：**可用** — SSE LOF `COMMON_SSE_SJ_JJSJ_JJGM_LOFGMTJ_L`，`INTERNAL_VOL`=场内万份（≠总份额）。
- 全份额仍用东财 gmbd 季报对照。
- 建议 sources_map 将该码 `shares_source` 升为 SSE LOF daily，`status=ok`（注明场内），原 partial 取消。

## 511880
- 日频份额：**仍暂无**。继续 gmbd 季报；`status=partial` 不变。
