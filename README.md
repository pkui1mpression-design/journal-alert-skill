# journal-alert-skill

给 AI Agent 用的技能：**输入关键词，抓取指定期刊最近 N 天的文献题录，按相关度分级生成 Markdown 日报**，附结构化 JSON 和一段可以直接发到聊天/微信的短摘要。

数据源是期刊 RSS + **OpenAlex** + **Crossref** 三路互备，只用 Python 标准库，**不需要 pip 安装任何东西**。

```
关键词 + 期刊 + 时间窗
        │
        ▼
期刊 RSS ┐
OpenAlex ├─► 合并去重 → 时间窗过滤 → 关键词打分（标题 ×3 / 摘要 ×1）
Crossref ┘
        │
        ▼
必读 / 值得一读 / 其他相关  ──►  Markdown 日报 + JSON + 聊天短摘要
```

- **不依赖邮箱**：直接抓期刊 RSS 与官方 API，不受邮件改版、RSS 邮件格式、邮件客户端类型影响。
- **不污染现有项目**：自带独立管线，不读也不写任何已有项目的 `config.json`、历史库或推送配置。
- **期刊目录 40 本**，ISSN 全部经 Crossref / OpenAlex 校验，RSS 全部实测可通。

---

## 目录

| | |
|---|---|
| [1. 安装](#1-安装) | [2. 快速开始](#2-快速开始) |
| [3. 三种用法](#3-三种用法) | [4. 关键词怎么写](#4-关键词怎么写) |
| [5. 期刊目录](#5-期刊目录) | [6. 参数](#6-参数) |
| [7. 输出与分级规则](#7-输出与分级规则) | [8. 数据源与已知限制](#8-数据源与已知限制) |
| [9. 加自己的期刊](#9-加自己的期刊) | [10. 常见问题](#10-常见问题) |

---

## 1. 安装

需要 **Python 3.10+**，没有第三方依赖。

作为技能安装（WorkBuddy / Claude 系的技能目录，认 `SKILL.md` + YAML frontmatter）：

```bash
git clone https://github.com/pkui1mpression-design/journal-alert-skill.git ~/.workbuddy/skills/journal-alert
```

装好后 Agent 会在你说「抓一下 XX 方向的文献」时自动启用它。

只想当普通脚本用也可以，不需要安装：

```bash
git clone https://github.com/pkui1mpression-design/journal-alert-skill.git
cd journal-alert-skill
python scripts/digest.py --keywords "ozone, aerosol" --journals "ACP,Nature" --days 7
```

---

## 2. 快速开始

先看看内置了什么：

```bash
python scripts/digest.py --list-journals    # 40 本期刊目录
python scripts/digest.py --list-profiles    # 4 套内置关键词方案
```

**零参数**跑一份（内置 `atmospheric` 方案 + 默认 19 本刊 + 近 7 天）：

```bash
python scripts/digest.py --digest
```

换个方向，自己给词：

```bash
python scripts/digest.py \
  --keywords "microplastic, nanoplastic, atmospheric transport" \
  --journals "Nature,ACP,1752-0908,Remote Sensing of Environment" \
  --days 14 \
  --topic "微塑料大气传输" \
  --digest
```

跑完会打印一段聊天短摘要，并写出完整报告：

```
报告：.../journal-digest/2026-10-05_微塑料大气传输.md
结构化：.../journal-digest/2026-10-05_微塑料大气传输.json
```

---

## 3. 三种用法

**A. 交给 Agent（推荐）**

装成技能后直接说人话，Agent 会负责把中文方向展开成英文术语表、挑刊、跑命令、把结果讲给你：

> 「抓一下微塑料大气传输的文献，Nature 和 ACP，近两周」
> 「这几本刊这周有什么关于臭氧的」
> 「换成碳循环方向再来一版」

**B. 零参数 / 内置方案**

```bash
python scripts/digest.py --digest                  # atmospheric（默认）
python scripts/digest.py --profile carbon --digest # 碳循环与碳中和
python scripts/digest.py --profile microplastic    # 微塑料与纳米塑料
python scripts/digest.py --profile ai-earth        # AI × 地球科学
```

内置方案：`atmospheric` ★ ｜ `microplastic` ｜ `carbon` ｜ `ai-earth`，定义在 `scripts/profiles.json`，想加自己的直接往里写。

**C. spec 文件（方向复杂时最干净）**

```json
{
  "topic": "微塑料大气传输",
  "keywords": [
    {"label": "微塑料", "weight": 3, "terms": ["microplastic", "nanoplastic", "plastic debris"]},
    {"label": "传输与归趋", "weight": 3, "terms": ["atmospheric transport", "long-range transport", "atmospheric deposition"]}
  ],
  "journals": ["Nature", "ACP", {"name": "自定义期刊", "issn": "1748-9326"}],
  "days": 14,
  "max_entries": 30,
  "tiers": {"must_read": 12, "worth_reading": 6, "min_score": 3}
}
```

```bash
python scripts/digest.py --spec examples/microplastic.json --out-dir ./journal-digest --digest
```

---

## 4. 关键词怎么写

**期刊题录都是英文的，直接拿中文词去搜必然 0 命中。** 关键词要写成「一个概念一组、组内列足英文同义词」：

```json
{"label": "空气污染", "weight": 3,
 "terms": ["air pollution", "air quality", "particulate matter", "pm2.5", "aerosol", "ozone", "haze"]}
```

规则：

- `terms` **全小写**。匹配按「非字母数字边界」做大小写不敏感匹配——所以 `no2` 不会误命中 `no20`，`pm2.5` 里的 `.` 按字面处理。
- `label` 只是报告里显示用的名字，中文没问题。
- 一个概念一组，**组内任一个词命中就算这组命中**。
- `weight` 默认 3。想让某个方向更靠前就调大（得分 = weight × 字段倍数）。
- 越具体越好，但别为了凑数塞无关词——每个词都会真的拉高命中量。

常见方向的对照表：

| 中文方向 | terms 该写什么 |
|---|---|
| 空气污染 | air pollution, air quality, particulate matter, pm2.5, pm10, aerosol, ozone, no2, so2, haze, smog |
| 卫星遥感 | remote sensing, satellite, modis, viirs, tropomi, sentinel-5p, landsat, aod, retrieval |
| 大气化学 | atmospheric chemistry, photochemistry, secondary organic aerosol, soa, nox, voc, chemical transport model |
| 碳循环 | carbon cycle, carbon flux, co2 flux, terrestrial carbon, soil carbon, net ecosystem exchange |
| 温室气体 | carbon dioxide, methane, ch4, n2o, nitrous oxide, greenhouse gas |
| 微塑料 | microplastic, microplastics, nanoplastic, plastic debris |
| 机器学习 | machine learning, deep learning, neural network, foundation model, emulator |

---

## 5. 期刊目录

★ = 不给 `--journals` 时的默认集合（19 本）。

| 期刊 | ISSN | RSS | 默认抓取 |
|---|---|---|---|
| Nature | `0028-0836` | 有 | ★ |
| Science | `0036-8075` | 有 | ★ |
| Science Advances | `2375-2548` | 有 | ★ |
| PNAS | `0027-8424` | 有 | ★ |
| Nature Communications | `2041-1723` | 有 | ★ |
| Nature Climate Change | `1758-6798` | 有 | ★ |
| Nature Geoscience | `1752-0908` | 有 | ★ |
| Nature Sustainability | `2398-9629` | 有 | ★ |
| Nature Cities | `2731-9997` | 有 | ★ |
| Nature Water | `2731-6084` | 有 |  |
| Nature Food | `2662-1355` | 有 |  |
| Nature Ecology & Evolution | `2397-334X` | 有 |  |
| npj Climate and Atmospheric Science | `2397-3722` | 有 | ★ |
| Earth's Future | `2328-4277` | 有 | ★ |
| Geophysical Research Letters | `1944-8007` | 有 | ★ |
| Journal of Geophysical Research: Atmospheres | `2169-8996` | 有 | ★ |
| Journal of Geophysical Research: Biogeosciences | `2169-8961` | 有 |  |
| Global Biogeochemical Cycles | `1944-9224` | 有 |  |
| Reviews of Geophysics | `1944-9208` | 有 |  |
| Atmospheric Chemistry and Physics | `1680-7324` | 有 | ★ |
| Atmospheric Measurement Techniques | `1867-8548` | 有 |  |
| Biogeosciences | `1726-4189` | 有 |  |
| Geoscientific Model Development | `1991-9603` | 有 |  |
| Environmental Research Letters | `1748-9326` | 有 | ★ |
| Environmental Science & Technology | `0013-936X` | — | ★ |
| Environmental Science & Technology Letters | `2328-8930` | — |  |
| Atmospheric Environment | `1352-2310` | 有 | ★ |
| Remote Sensing of Environment | `0034-4257` | 有 | ★ |
| Science of the Total Environment | `0048-9697` | 有 |  |
| Environmental Pollution | `0269-7491` | 有 |  |
| Environment International | `0160-4120` | 有 |  |
| Water Research | `0043-1354` | 有 |  |
| Global Environmental Change | `0959-3780` | 有 |  |
| Applied Energy | `0306-2619` | 有 |  |
| One Earth | `2590-3322` | 有 |  |
| Journal of Cleaner Production | `0959-6526` | 有 |  |
| Atmospheric Research | `0169-8095` | 有 |  |
| Global Change Biology | `1365-2486` | 有 | ★ |
| Bulletin of the American Meteorological Society | `1520-0477` | — |  |
| Journal of Climate | `1520-0442` | — |  |

「RSS —」的刊（ACS、AMS）没有可用的公开 feed，只走 OpenAlex + Crossref，完全不影响使用。

指定期刊时可以用 **刊名**、**别名**（`ACP`、`GRL`、`ES&T`、`rse`）、**ISSN**，或 `all` / `default`：

```bash
python scripts/digest.py --keywords "ozone" --journals "ACP,GRL,1748-9326"
python scripts/digest.py --keywords "ozone" --journals all
```

---

## 6. 参数

```bash
python scripts/digest.py [options]
```

| 参数 | 说明 |
|---|---|
| `--keywords "a, b, c"` | 逗号分隔关键词，每个词自成一组；也接受 JSON 数组／对象 |
| `--spec FILE` | JSON 任务描述文件（见第 3 节 C） |
| `--profile NAME` | 用内置关键词方案 |
| `--journals "..."` | 逗号分隔刊名/别名/ISSN，或 `default` / `all` |
| `--days N` | 时间窗天数，默认 7 |
| `--max-entries N` | 报告最多列多少条，默认 30，`0` = 不限 |
| `--topic 名称` | 报告标题（也是文件名的一部分） |
| `--out-dir DIR` | 输出目录，默认 `./journal-digest` |
| `--out FILE` | 直接指定 Markdown 输出路径 |
| `--sources rss,openalex,crossref` | 只用其中几个源，可提速 |
| `--mailto 邮箱` | 留给 OpenAlex / Crossref 的联系邮箱，走「礼貌池」更快更稳 |
| `--dedupe` | 启用跨天去重台账（默认关闭） |
| `--print` | 把完整报告打到 stdout |
| `--digest` | 额外输出适合聊天/IM 的短摘要 |
| `--dry-run` | 不写任何文件，只打印 |
| `--no-json` | 不写结构化 JSON |
| `--check` | 只测数据源连通性，不出报告 |
| `--list-journals` / `--list-profiles` | 打印目录 / 方案后退出 |
| `--log-level DEBUG` | 更啰嗦的日志 |

---

## 7. 输出与分级规则

每次运行写两个文件到 `--out-dir`：

- `<日期>_<主题>.md` —— 正文日报。表头是「期刊数 / 时间窗 / 抓取数 / 命中数 / 三级分级计数」，正文按 **必读 → 值得一读 → 其他相关** 分节，每条含标题链接、期刊、日期、DOI、命中的关键词与得分、作者、摘要节选，最后附**数据源状态表**。
- `<日期>_<主题>.json` —— 同内容的结构化版（标题 / 期刊 / 日期 / DOI / 得分 / 命中标签 / 摘要），可直接喂给后续处理。

分级规则（`tiers` 可改）：

| 级别 | 条件 | 含义 |
|---|---|---|
| 🔥 必读 | 得分 ≥ 12 | 至少一个关键词命中标题，且另有命中 |
| 值得一读 | 得分 ≥ 6 | 一个关键词命中标题 |
| 其他相关 | 得分 ≥ 3 | 仅摘要命中 |
| 丢弃 | 得分 < 3 | 不进报告 |

得分 = Σ(weight × 字段倍数)，默认 weight 3、标题 ×3、摘要 ×1 —— 所以「标题命中一个词」= 9 分。

默认还会自动排除撤稿、勘误、社论、目录页，以及 Nature 的新闻稿（`10.1038/d41586`）。

> **默认是「快照」语义**：每次都列时间窗内的全量命中，不做跨天去重。想「每天只看新增」，加 `--dedupe`，台账落在 `<out-dir>/state/seen.sqlite`。

---

## 8. 数据源与已知限制

| 源 | 用途 | 说明 |
|---|---|---|
| 期刊 RSS / Atom / RDF | 最新上线文献 | 出版社官方推送源，各刊格式不一，已统一解析 |
| [OpenAlex](https://api.openalex.org) | 按 ISSN + 日期检索 | 兜底 + 补摘要；填了 `--mailto` 会走「礼貌池」 |
| [Crossref](https://api.crossref.org) | 按 ISSN + 日期检索 | 第二路兜底 + 补 DOI / 元数据 |

三路结果按 DOI（缺 DOI 时按标题）合并去重，摘要取最长的那份。

- **海外 API 偶发超时是正常现象**（实测约 15% 的调用）。管线自带重试，且每本刊都有 2–3 个源互为兜底，单源失败不会漏文献；报告底部会如实标出每个源的状态，别把个别 ❌ 当成抓取失败。
- **联网由 Python 发起**。部分环境的 `curl` / PowerShell 被代理或安全软件拦住而 Python 能通，所以别用别的客户端去「复现」网络问题。
- 时间窗 **默认 7 天**；只想要当天的加 `--days 1`，补一批历史的加 `--days 30`。
- 一次全量（默认 19 本刊 × 3 源）大约 **30–90 秒**。想快速验证先指定一两本刊，或加 `--sources rss`。

---

## 9. 加自己的期刊

目录在 `scripts/journals.json`，加一条就行：

```json
{ "name": "Journal Name", "issn": "1234-5678", "rss": "", "aliases": ["短名"], "tags": ["大气"], "default": false }
```

**`issn` 是唯一必需字段**（OpenAlex 与 Crossref 都按它检索），`rss` 留空完全可用。`default: true` 表示「不给 `--journals` 时也抓它」，加多了会拖慢每次运行。

按 ISSN 查刊名和 RSS 规律、以及新增后必须做的验证步骤，见 **[`references/journal-catalog.md`](references/journal-catalog.md)**。验证一条：

```bash
python scripts/digest.py --check --journals "新刊名"
```

---

## 10. 常见问题

**跑出来 0 条命中？**
先看是不是关键词没写成英文。其次时间窗太窄：`--days 14` 再试。还是 0 就把 `terms` 放宽（比如从 `pm2.5` 放到 `particulate matter`）。

**`--dedupe` 之后第二次跑怎么空了？**
它的语义就是「只列没见过的」。看全量先去掉 `--dedupe`。

**报告里的日期是未来？**
Elsevier 系的 feed 打的是**期号日期**（在正式出版前就出现），报告里会标成「（在线预发表）」，属正常。

**想每天自动跑？**
用任何定时器（cron / Windows 计划任务 / CI）每天调同一条 `digest.py` 命令即可，加 `--dedupe` 就只推新增。

**技能和 `Journal-alert` 项目什么关系？**
`Journal-alert` 是一个「固定方向、每天定时、推微信」的完整应用；本仓库是把同一套抓取/打分管线抽出来、**参数化**后的 Agent 技能——关键词、期刊、时间窗都从命令行给，与本机任何已有配置隔离。`scripts/jalert/` 里的 `fetch` / `score` / `state` 源自该项目（MIT），报告渲染 `scripts/render.py` 是本技能自带的一份。

---

## 许可

MIT，见 [LICENSE](LICENSE)。管线部分源自 [pkui1mpression-design/Journal-alert](https://github.com/pkui1mpression-design/Journal-alert)（MIT）。
