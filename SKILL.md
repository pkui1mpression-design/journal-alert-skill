---
name: journal-alert
description: 按用户给的关键词，抓取指定期刊最近 N 天的文献题录，关键词打分分级后生成 Markdown 日报 + 聊天短摘要。当用户说「抓一下 XX 方向的文献」「这几本刊最近有什么」「用关键词生成文献日报」「按期刊抓文献目录」「换个关键词再来一版」「journal alert / literature digest / 文献速递」时使用。中文关键词必须先展开成英文同义词表再跑。
agent_created: true
---

# journal-alert：按关键词抓指定期刊的文献日报

输入「关键词 + 期刊 + 时间窗」，输出一份按相关度分级的 Markdown 文献日报（附结构化 JSON 和聊天短摘要）。

数据源是期刊 RSS + OpenAlex + Crossref 三路互备，**只用 Python 标准库**，不需要装任何包。它自带一份独立的抓取/打分管线，与任何已有项目的 `config.json`、历史库、推送通道完全隔离——跑这个技能不会动它们。

## 工作流

### 1. 把需求变成英文关键词（最关键的一步）

期刊题录都是英文，**直接拿中文词去搜必然 0 命中**。任务是把用户的中文意图翻译并展开成英文术语表，每个概念一组、组内写足同义词和缩写：

| 用户说的 | terms 里该写什么 |
|---|---|
| 空气污染 | air pollution, air quality, particulate matter, pm2.5, aerosol, ozone, no2, haze |
| 卫星遥感 | remote sensing, satellite, modis, viirs, tropomi, sentinel-5p, retrieval |
| 微塑料 | microplastic, microplastics, nanoplastic |
| 碳循环 | carbon cycle, carbon flux, co2 flux, terrestrial carbon, soil carbon |

要点：
- 术语**全小写**，匹配时会按「非字母数字边界」做大小写不敏感匹配，所以 `no2` 不会误命中 `no20`。
- 一个概念一组（`label` 用中文方便阅读，`terms` 放英文），**组内任一词命中即算这组命中**。
- 越具体越好，但别为了凑数写无关词——每个词都会真的拉高命中量。
- 用户没指定方向时，先问一句要抓什么方向，别瞎猜。
- **例外**：用户只想「按平时的方向来一份」时，不用自己写关键词——脚本内置了几套现成方案，连参数都可以省：

```bash
python "<skill>/scripts/digest.py" --digest            # 零参数 = 内置 atmospheric 方案 + 默认期刊集
python "<skill>/scripts/digest.py" --profile carbon    # 换一套内置方案
python "<skill>/scripts/digest.py" --list-profiles     # 看有哪些方案
```

内置方案：`atmospheric`（大气环境，默认）、`microplastic`、`carbon`、`ai-earth`。用户给了具体方向时**优先现写关键词**，不要硬套方案。

### 2. 选期刊

默认（不给 `--journals`）用目录里标 ★ 的一组大气/环境/综合刊。用户点名了就用他说的。

先看目录有什么：

```bash
python "<skill>/scripts/digest.py" --list-journals
```

指定方式（`--journals` 逗号分隔，或写进 spec 的 `journals` 数组）：
- 刊名：`Nature`、`Atmospheric Chemistry and Physics`（大小写、标点不敏感）
- 别名：`ACP`、`GRL`、`ES&T`、`rse`
- ISSN：`1680-7324`
- `"all"` 全部 / `"default"` 默认集
- 目录里没有的刊 → 查它的 **ISSN**，在 spec 里写内联对象：`{"name": "XXX", "issn": "1234-5678"}`。**ISSN 是必需项，RSS 可以留空**（留空就走 OpenAlex + Crossref）。查 ISSN 和 RSS 的办法见 `references/journal-catalog.md`。

### 3. 写 spec 并运行

推荐把任务写成 spec 文件（中文、多组关键词、内联期刊都能干净表达）：

```json
{
  "topic": "大气环境文献日报",
  "keywords": [
    {"label": "空气污染", "weight": 3, "terms": ["air pollution", "pm2.5", "aerosol", "ozone"]},
    {"label": "卫星遥感", "weight": 3, "terms": ["remote sensing", "tropomi", "modis"]}
  ],
  "journals": ["Nature", "ACP", "ES&T", "Remote Sensing of Environment"],
  "days": 7,
  "max_entries": 30
}
```

然后：

```bash
python "<skill>/scripts/digest.py" --spec spec.json --out-dir ./journal-digest --digest
```

`--digest` 会在完整报告之外再打一份适合直接发微信的短摘要。

### 4. 交付

- 把 `--digest` 的短摘要直接输出给用户（想推到 IM / 微信就走这条）；
- 需要长内容时，读生成的 `<out-dir>/<日期>_<主题>.md` 再讲；
- 用户可能想持续跟踪 → 提醒他可以用 WorkBuddy 自动化每天定时跑同一条命令。

## 命令速查

```bash
S="<skill>/scripts/digest.py"   # 例如 ~/.workbuddy/skills/journal-alert/scripts/digest.py

python "$S" --digest                            # 零参数：内置 atmospheric 方案 + 默认期刊集
python "$S" --keywords "microplastic, nanoplastic" --journals "Nature,ACP" --days 14
python "$S" --profile carbon --days 14 --digest  # 用内置关键词方案
python "$S" --spec spec.json --print            # 写文件并把完整报告打到 stdout
python "$S" --spec spec.json --digest           # 另出聊天短摘要
python "$S" --journals "all" --keywords "ozone" # 全部 40 本刊
python "$S" --journals "ACP" --check            # 只测数据源连通性，不出报告
python "$S" --list-journals                     # 看期刊目录
python "$S" --list-profiles                     # 看内置关键词方案
python "$S" --spec spec.json --dry-run --print  # 不写任何文件
python "$S" --spec spec.json --dedupe           # 跨天去重（第二次只列新增）
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--days N` | 时间窗天数，默认 7 |
| `--max-entries N` | 报告最多列多少条，默认 30，`0` = 不限 |
| `--profile NAME` | 用内置关键词方案（atmospheric / microplastic / carbon / ai-earth） |
| `--topic 名称` | 报告标题（也是文件名的一部分） |
| `--out-dir DIR` | 输出目录，默认 `./journal-digest` |
| `--sources rss,openalex,crossref` | 只用其中几个源，可提速 |
| `--mailto 邮箱` | 留给 OpenAlex/Crossref 的联系邮箱，走「礼貌池」更快更稳 |
| `--dedupe` | 启用跨天去重台账（默认关闭） |
| `--dry-run` / `--no-json` | 不写文件 / 不写结构化 JSON |

## 输出

- `<out-dir>/<日期>_<主题>.md` — 正文日报。表头是「期刊数 / 时间窗 / 抓取数 / 命中数 / 三级分级计数」，正文按 **必读 → 值得一读 → 其他相关** 分节，每条含标题链接、期刊、日期、DOI、匹配到的关键词与得分、作者、摘要节选，最后附**数据源状态表**。
- `<out-dir>/<日期>_<主题>.json` — 同内容的结构化版（标题/期刊/日期/DOI/得分/摘要），可直接喂给后续处理。
- `<out-dir>/state/seen.sqlite` — 只在 `--dedupe` 时使用。

分级阈值（改 spec 的 `tiers` 可调）：标题命中 9 分、仅摘要命中 3 分 → ≥12 必读、≥6 值得一读、≥3 其他相关。

## 注意

- **默认是「快照」语义**：每次都列时间窗内的全量命中，不加 `--dedupe` 不做跨天去重。用户抱怨「怎么又是这些」时再加 `--dedupe`。
- **命中为 0** 先别急着说没文献：多半是关键词没展开成英文，或者时间窗太窄。改 `--days 14`、补同义词再跑。
- **海外站点偶发超时很正常**（实测约 15% 的调用）。管线有重试，且每本刊都有 2–3 个源互为兜底，单源失败不等于漏文献；报告底部的数据源状态表会如实标注。别把个别 ❌ 说成「抓取失败」。
- **网络只能由 Python 走**：这台机器上 `curl` / PowerShell 可能被拦住。所有联网都发生在脚本里，不要试图用别的客户端复现。
- **默认集 19 本刊**全抓大约 30–90 秒；只想快速验证时先指定一两本刊或加 `--sources rss`。
- 运行环境：Python 3.10+，`python` 或 `python3` 均可（只用标准库，无第三方依赖）。
- `scripts/jalert/` 是上游 journal-alert 项目的抓取/打分/台账管线（`fetch` / `score` / `state`）的拷贝；报告渲染用的是本技能自带的 `scripts/render.py`，与上游的 `report.py` 不是同一份。要同步上游改动，把对应 `.py` 覆盖进 `scripts/jalert/` 即可。
