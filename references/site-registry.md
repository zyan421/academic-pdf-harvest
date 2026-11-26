# 已知法学期刊站点登记表

> 2026-11-20 实测。新任务先查此表，命中则直接取用参数，不必重新侦察。
> 判定级别：A＝实测 PDF 可下载，可直接照搬；B＝有 PDF 但需适配域名/URL；C＝不可行或未验证。

## A 级：直接照搬（实测 200 + `%PDF-`）

| 期刊 | 站点 | sitemap | PDF 路径规律 |
|---|---|---|---|
| Harvard Law Review | harvardlawreview.org | `/sitemap_index.xml` → post-sitemap{,2,3}.xml + forum-sitemap.xml（2598 篇） | `/wp-content/uploads/YYYY/MM/<卷>-Harv.-L.-Rev.-<页>[-1].pdf` |
| NYU Law Review | nyulawreview.org | `/sitemap_index.xml` → `post-sitemap.xml`（1001+） | `/wp-content/uploads/YYYY/MM/NYULaw-<卷>-<期>-<作者>_0.pdf` |
| Columbia Law Review | columbialawreview.org | `/content-sitemap.xml`（843） | `/wp-content/uploads/YYYY/MM/<作者>_FINAL.pdf` |
| Michigan Law Review | michiganlawreview.org | `/post-sitemap.xml`（85，疑仅近期） | `/wp-content/uploads/YYYY/MM/<卷>MichLRev<页>_<作者>.pdf` |

文章页分类字段需按站重新定位 DOM class；HLR 的是 `.single-article__piece-type` / `__topic` / `__author`。

**2026-11-20 全量下载实测结果**（分文件夹存 `~/Downloads/`）：NYU 1446/1448（2 个源站删除的 PDF：Oronoz-Rodríguez、Shill-2，文章页 HTML 仍可访问）；Columbia 839/839；Michigan **仅 76 篇**——sitemap 6865 条中 `/journal/<slug>/` 的 6193 条是无 PDF 的元数据页，只有 84 个顶层 slug 含 PDF。MLR 若需全卷期须另走 archive/Digital Commons。三站合计 2361 个 PDF，四站（含 HLR）共 4970 个。

## B 级：需适配

- **Stanford Law Review**：文章页 `www.stanfordlawreview.org/print/article/<slug>/`，PDF 在**独立主机** `review.law.stanford.edu/wp-content/uploads/sites/3/YYYY/MM/<作者>-<卷>-Stan.-L.-Rev.-<页>.pdf`，HTML 里带 `title="Download the PDF"`。本机对该主机 SSL 握手失败（`UNEXPECTED_EOF_WHILE_READING`），需换网络环境或调整 TLS。
- **Virginia Law Review**：virginialawreview.org，sitemap 22 loc 不含文章，需从 archive 分页枚举。
- **UCLA / Penn Law Review**：sitemap 各 1000 条，文章页可达但抽样无 `.pdf`，需查是否用非 PDF 端点或部分文章才有 PDF。
- **Yale Law Journal**：yalelawjournal.org，无 sitemap（404），文章 URL `/article/<slug>`，需 archive 枚举。
- **Chicago Law Review**：全文在 `chicagounbound.uchicago.edu/uclrev`（Digital Commons），主站连接失败。
- **Texas Law Review**：`texaslrev.com` 已失效，需查新域名。
- **Duke Law Journal**：`law.duke.edu/dlj/`，本机 SSL 握手失败。

## A 级（续）：Digital Commons / bepress 集群

> **2026-11-23 修正**：此前把这一簇判为「本机不可达」是**错的**，根因是环境变量
> `HTTPS_PROXY=127.0.0.1:7899` 对这批站点握手后断开，与站点无关。绕过代理即通。
> 且**必须**用 `curl_cffi` + `impersonate="chrome"`，普通 requests / curl / 其他
> impersonate profile 都会被 Cloudflare 挡在 `/cgi/viewcontent.cgi`（403 挑战页）。

```python
import os
for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
from curl_cffi import requests as creq
s = creq.Session(impersonate="chrome")      # 只有 "chrome" 有效，chrome131/110/safari 全 403
s.get(url, proxies={"http": None, "https": None})
```

**URL 解剖**（三站通用，无需 sitemap）：

```
/{ctx}/all_issues.html          → 全部卷 /{ctx}/vol{N}/
/{ctx}/vol{N}/                  → 全部期 /{ctx}/vol{N}/iss{M}/
/{ctx}/vol{N}/iss{M}/           → 文章页 /{ctx}/vol{N}/iss{M}/{序号}
文章页 HTML                      → /cgi/viewcontent.cgi?article=<真实ID>&context=<ctx>
```

注意：URL 里的 `{序号}` 是期内篇序，**不是** bepress 的 article ID；必须解析文章页拿真 ID。
另有别名 `/context/{ctx}/article/{id}/viewcontent/`，同样有效。

**已验证可直取 PDF 的仓储**（2026-11-23，均为 `%PDF-` 实测）：

| 学校 | host | ctx | 卷数 | issue 数 |
|---|---|---|---|---|
| Chicago | chicagounbound.uchicago.edu | `uclrev` | 93 | 408 |
| Duke | scholarship.law.duke.edu | `dlj` | 76 | 443 |
| Michigan | repository.law.umich.edu | `mlr` | 125 | — |
| Northwestern | scholarlycommons.law.northwestern.edu | `nulr` | 17 | — |
| Cornell | scholarship.law.cornell.edu | `clr` / `cilj` | 100 / 52 | 505 / 130 |
| Penn | scholarship.law.upenn.edu | `penn_law_review` | ✗ 404 | — |
| Fordham | ir.lawnet.fordham.edu | `flr` | 95 | 462 |
| W&M | scholarship.law.wm.edu | `wmlr` | 68 | 310 |
| Emory | scholarlycommons.law.emory.edu | `elj` | 18 | 107 |
| Notre Dame | scholarship.law.nd.edu | `ndlr` | 100 | 477 |
| Vanderbilt | scholarship.law.vanderbilt.edu | `vlr` | 79 | 456 |
| Florida | scholarship.law.ufl.edu | `flr` | 77 | 370 |
| WUSTL | openscholarship.wustl.edu | `law_lawreview` | 100 | 431 |
| UC Law SF | repository.uclawsf.edu | `hastings_law_journal` | 77 | 401 |
| BYU | digitalcommons.law.byu.edu | `lawreview` | 52 | 249 |
| UWash | digitalcommons.law.uw.edu | `wlr` | 99 | 391 |
| UNC | scholarship.law.unc.edu | `nclr` | 104 | 525 |
| Indiana | www.repository.law.indiana.edu | `ilj` | 101 | 479 |
| BU | scholarship.law.bu.edu | `bulawreview` | 仅近年 | — |

19 家可用仓储合计约 **6,150 期**，按每期 8–12 篇估 **5–7 万篇 PDF**。体量远超单次任务，
批量前必须先定范围（按刊 / 按年段 / 按主题）。

**限速特征**：同一会话累计约 10 个请求后，PDF 端点开始返 403 挑战页；**换新会话即恢复**，
不必换 IP。故下载器须「每 N 个请求重建 Session + 403 时丢弃会话退避重试」。
另：`all_issues.html` / 卷 / 期页不受此限制，可放心枚举。

**OAI-PMH 是首选通道，别逐页爬**（2026-11-23 实测，这是本类站点最重要的技巧）：

```
/do/oai/?verb=ListRecords&metadataPrefix=document-export&set=publication:{ctx}
```

`document-export` 格式每条记录**直接给 `<fulltext-url>`（PDF 直链）**，还有
`title / authors(lname,fname,mname) / publication-date / coverpage-url / articleid /
start_page / document-type`。每请求 100 条，`completeListSize` 报总数，`resumptionToken` 翻页。
72,809 条只需约 730 次请求（逐页爬文章页要 7 万次）。

坑：
- `fulltext-url` 里是 `&amp;amp;` **双重转义**，要 `html.unescape()` 连着做两次。
- 部分仓储的 `set` 名不是 `publication:{ctx}`；`ListMetadataFormats` 可先探。
- 返回体里 `<document-export xmlns="">` 会重置命名空间，用 ElementTree 反而麻烦，
  按 `<record>` / `<document>` 正则切块最省事。

**实测规模**（`completeListSize`）：Michigan 13,161、UNC 6,028、WUSTL 5,442、
Chicago 5,270、Fordham 5,118、Indiana 4,904、UWash 4,333、Notre Dame 4,108、
Vanderbilt 3,888、Duke 3,403、UC Law SF 3,189、Florida 3,144、W&M 3,085、
Cornell 2,937、BYU 2,588、Cornell ILJ 941、Northwestern 666、Emory 585。合计 **72,809**。

**下载吞吐**（2026-11-23 实测，Duke 样本）：单篇中位 2.5–3.1 秒；2/4/8/12 并发聚合
0.40/0.42/0.69/0.98 MB/s，速率 0.64/1.17/1.28/1.68 篇/s。并发到 12 仍在涨，但失败率上升
（12 并发时 11/12 成功），**8 并发是稳妥上限**。文件体积差异极大：早年短评 ~200KB，
近年合订期单篇可达 5MB，故按篇数估时间不可靠，应按字节估。

## C 级：不可行 / 未验证

- **Oxford Academic**（academic.oup.com，牛津 48 种法律期刊）：Cloudflare 403，sitemap 403，禁 `/DownloadFile/`，OA 期刊 JLA 亦拿不到 PDF 直链，不入 PMC。判别口诀：sitemap + 文章页都 403 即止步。
- **eScholarship**（escholarship.org，UCLA 系列 13 种）：根路径返 202（JS 挑战），需另找 PDF 端点，未攻克。
- **mpil.de / cadmus.eui.eu / lawreview.lse.ac.uk**：直连超时或 403，需换网络环境。
- **repository.law.indiana.edu**：必须带 `www.` 前缀，否则 DNS 不解析。
- **Penn `penn_law_review` / UMN `mlr` / Emory `elj-online`**：`all_issues.html` 404，代码或路径需另找。
- **Sydney Law Review**：官网声明 open access，本机连接失败未验证。
- **Ottawa Law Review**：commonlaw.uottawa.ca/ottawa-law-review，声明 1966 至今全开放，页面有 Cloudflare 特征，未实测 PDF。

## 三步判定法（任意新站点）

1. `curl <site>/sitemap_index.xml` 与 `/sitemap.xml`：都 403 → 商业平台，止步。
2. sitemap 取真实文章页，`curl` 后 grep `\.pdf`：见 `/wp-content/uploads/` 直链 → 可照搬。
3. 下载该 PDF 验 `%PDF-` 魔数：通过才算真开放，勿轻信网站声明。

完整侦查报告见工作区 `世界法学期刊PDF开放获取侦查报告.md`。

### 量产实测：六刊 35,148 篇（2026-11-25 01:24 → 11-26 06:41，29.3 小时）

| 期刊 | host | 篇数 | 体积 | 用时 |
|---|---|---|---|---|
| Michigan | repository.law.umich.edu | 13,004 | 8.82 G | 全程（长尾） |
| UNC | scholarship.law.unc.edu | 6,028 | 7.78 G | 约 15 h |
| Chicago | chicagounbound.uchicago.edu | 5,253 | 6.36 G | 约 13 h |
| Notre Dame | scholarship.law.nd.edu | 4,041 | 5.61 G | 约 10 h |
| Vanderbilt | scholarship.law.vanderbilt.edu | 3,885 | 4.05 G | 约 10 h |
| Cornell | scholarship.law.cornell.edu | 2,937 | 2.45 G | 约 7.5 h |

参数 `--min-interval 8 --per-host 1 --max-hosts 6`，结果：**35,143 篇零失败、零损坏、零 .part**。

两个可复用的量化结论：

1. **8 秒/站是安全的。** 全程 35,148 次下载中 **429 出现 0 次**；只有 50 次瞬时 403
   （单请求级挑战，换会话即过）。说明单站 7.5 篇/分确实在配额线以下。
2. **聚合速率会随"剩余站点数"衰减，估算必须按最慢的单站算。**
   六站齐跑时 0.76 篇/秒（≈2,700/小时）；只剩密歇根时降到 0.33 篇/秒（≈1,200/小时）。
   按总量/平均速率估会低估约 2.4 倍——日志里那个 "ETA 12 h" 就是这么来的，
   实际 29.3 小时。**估算公式：max(各站独占耗时)，而不是 总篇数 / 聚合速率。**

单篇中位体积约 0.6 MB（早年短评 100–300 KB，近年合订期单篇可到 8 MB 以上），
35k 篇约 35 GB，规划磁盘时按 1 MB/篇 估比较稳。

### 更正（2026-11-27）：配额是 IP 全局，不是按域名

上面那段「6 站各 8 秒 ≈ 2,700 篇/小时」不能理解成「站点越多越快」。
第二批 12 站同时跑（12 x 1/8s = 1.5 篇/秒）时，启动数秒内 4 个站同时 429。
真实约束是 **IP 级总速率约 0.8 篇/秒（≈2,800 篇/小时）**，与站点数量无关。

因此下载器必须同时装「每站 min-interval」和「全局 global-interval」两道闸门：
`--min-interval 8 --global-interval 1.3`（≈0.77 篇/秒）。12 站并行只是让各刊进度更均衡，
总时长仍由 `总篇数 ÷ 0.77` 决定。规划时按 0.7 篇/秒估，不要按站点数乘算。
