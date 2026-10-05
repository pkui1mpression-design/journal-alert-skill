# 给技能加期刊 / 查 ISSN 与 RSS

期刊目录是 `scripts/journals.json`。加一本刊 = 追加一个对象：

```json
{ "name": "Journal Name", "issn": "1234-5678", "rss": "", "aliases": ["短名", "缩写"], "tags": ["大气"], "default": false }
```

**`issn` 是唯一必需字段**（OpenAlex 与 Crossref 都按它检索）；`rss` 留空完全没问题，那本刊就走两个 API。`default: true` 表示「不给 `--journals` 时也抓它」，别随便加，默认集变大会明显拖慢每次运行。

## 一、先查 ISSN

按优先级试：

```bash
# 1) OpenAlex（最全，返回 ISSN、出版社、年发文量）
python -c "import json,urllib.request;r=urllib.request.Request('https://api.openalex.org/sources?search=Atmospheric%20Chemistry%20and%20Physics',headers={'User-Agent':'Mozilla/5.0'});d=json.load(urllib.request.urlopen(r,timeout=30));[print(x['display_name'],x.get('issn_l'),x.get('issn'),x['host_organization_name']) for x in d['results'][:5]]"

# 2) Crossref（按刊名模糊查）
python -c "import json,urllib.request;r=urllib.request.Request('https://api.crossref.org/journals?query=atmospheric+chemistry+and+physics&rows=5',headers={'User-Agent':'Mozilla/5.0'});d=json.load(urllib.request.urlopen(r,timeout=30));[print(x['title'],x['ISSN']) for x in d['message']['items']]"
```

也可以直接翻期刊官网的「About / Journal information」页。**注意别把 E-ISSN 和 P-ISSN 弄混**——两个通常都能用，但填错会检索不到。

## 二、再找 RSS（可选但值得）

各大出版社的 feed 有明显规律，`<8位数字>` 指 ISSN 去掉横线：

| 出版社 | 规律 | 例子 |
|---|---|---|
| Nature 系 | `https://www.nature.com/<slug>.rss` | nature、ngeo、nclimate、ncomms、npjclimatsci |
| Science 系 | `https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=<code>` | `jc=science`、`jc=sciadv` |
| AGU（Wiley） | `https://agupubs.onlinelibrary.wiley.com/feed/<8位>/most-recent` | `19448007` = GRL |
| Wiley 通用 | `https://onlinelibrary.wiley.com/feed/<8位>/most-recent` | `13652486` = GCB |
| Copernicus | `https://<刊名小写>.copernicus.org/xml/rss2_0.xml` | acp、amt、bg、gmd |
| Elsevier / ScienceDirect | `https://rss.sciencedirect.com/publication/science/<8位>` | `13522310` = Atmospheric Environment |
| IOP | `https://iopscience.iop.org/journal/rss/<带横线 ISSN>` | `1748-9326` = ERL |
| ACS | 无可用的公开 RSS → **留空字符串** | ES&T、ES&T Letters |

## 三、必须验证

新增或改过目录后，用这一条把该刊的三个源都打一遍（会真的联网）：

```bash
python "<skill>/scripts/digest.py" --check --journals "新刊名"
```

看输出表：`openalex` / `crossref` 应该 OK 且条数 > 0；`rss` 若是 `FAIL` 或 `HTTP 4xx`，说明 feed 地址不对——直接把 `rss` 改成 `""`，别留一个坏地址（坏源每次都会留下一行 ❌ 噪声）。

只想验证 RSS 地址本身通不通：

```bash
python -c "import urllib.request as u;r=u.Request('https://rss.sciencedirect.com/publication/science/13522310',headers={'User-Agent':'Mozilla/5.0'});resp=u.urlopen(r,timeout=30);print(resp.status,len(resp.read()))"
```

## 四、本目录的现状

40 本刊，ISSN 全部经 Crossref/OpenAlex 校验过，RSS 全部实测返回 HTTP 200（跨天会失效，所以上面第三节的复验别省）。`default: true` 的是 19 本：Nature、Science、Science Advances、PNAS、Nature Communications、Nature Climate Change、Nature Geoscience、Nature Sustainability、Nature Cities、npj Climate and Atmospheric Science、Earth's Future、GRL、JGR: Atmospheres、ACP、ERL、ES&T、Atmospheric Environment、Remote Sensing of Environment、Global Change Biology。
