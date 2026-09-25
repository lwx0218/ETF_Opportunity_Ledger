# prototypes

只做导航。这里是 2026-09-15 定稿的两个界面原型的**静态快照**，由 `src/` 里的生成脚本加上数据快照重新生成（2026-09-25），用浏览器直接打开即可查看。它们是方向稿，不是产品 UI；产品 UI 按 intake §7 在任务 5 实现，规则见 `docs/design/teardown-design-rules-v3.md` 与 intake §8。

| 路径 | 是什么 | 由谁生成 |
|---|---|---|
| `rotation-panel/rotation-panel-2026.html` | 2026 轮动面板：17 个容器的周截面热力格、五个已核事件、规则成绩单。数据内嵌，单文件 | `src/rotation/analyze.py` → `analyze2.py` → `gen_panel.py` |
| `home/Main.dc.html` · `HomeLight.dc.html` | 机会首页首屏：上一次 / 当下 / 下一个三卡（深 / 浅） | `src/home/gen_home2.py` |
| `home/Detail.dc.html` · `DetailLight.dc.html` | 点开中卡后的展开态 | `src/home/gen_home.py`（被 `gen_home2.py` 调用） |
| `home/Scroll.dc.html` · `ScrollLight.dc.html` | 往下滚：今天不碰 / 规则今年值多少 | 同上 |
| `home/Direction{A,B,C}{,Dark}.dc.html` | 09-15 上午的三个平铺旧方向稿，留档对比 | `src/home/gen_directions.py` |
| `home/canvas.json` | 上述画板在 Claude Design 画布里的排布与批注 | `src/home/gen_home2.py` |

说明：`.dc.html` 引用的 `./support.js` 是 Claude Design 画布运行时，仓库里没有，浏览器里该请求会 404，不影响渲染；字体从 Google Fonts 加载。面板与首页里的数字截止 2026-09-14 收盘，此后没有更新。

重新生成（需先把数据快照解压到 `data/`）：

```bash
python src/rotation/analyze.py && python src/rotation/analyze2.py && python src/rotation/signals.py && python src/rotation/gen_panel.py
python src/home/gen_directions.py && python src/home/gen_home2.py
```

产物写到 `outputs/`（不入 Git），确认后再复制到这里。
