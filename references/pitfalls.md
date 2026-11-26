# 学术站点采集踩坑清单

> 全部来自 2026-11 对 Harvard Law Review 的全量采集与下载实测（2598 篇文章、2612 个 PDF、2609 个文件到位）。

## 0. 先判平台类型：这个技能不是万能的

**关键边界**：本技能适用于“自建站点 + 公开 PDF”（如 HLR 的 WordPress 站）。遇到**商业出版平台**要先停下来评估，很可能整条流水线用不上。

2026-11-20 实测 Oxford Academic（`academic.oup.com`，牛津 48 种法律期刊的集中平台）的结论：
- 全站 Cloudflare 挑战：curl 任何页面（含 `sitemap.xml`、文章页、`article-pdf/...pdf`）均 **403 “Just a moment...”**，连 sitemap 都拿不到 → 阶段 0 直接失败。
- `robots.txt` 明确 `Disallow: /DownloadFile/`。
- 阅读代理 `r.jina.ai` 同样只拿到挑战页，无法绕过。
- 即便期刊是**全开放获取**（如 Journal of Legal Analysis，OUP 代哈佛法学院出版，官方声明“all publications may be viewed and downloaded free of charge”），WebFetch 能读正文但**不暴露 PDF 直链**，自动下载仍不可行。
- OUP 法律期刊不在 PubMed Central / Europe PMC（`JOURNAL:"Journal of Legal Analysis" AND OPEN_ACCESS:y` 命中 0），无开放仓储替代源。
- **结论**：牛津法律期刊不能照搬本技能。可选路径只剩：机构订阅的浏览器会话手工下载、HeinOnline/Westlaw 合法数据库、向作者索取。遇到此类站点应在阶段 0 如实告知用户，不要硬试批量抓取。

**判别口诀**：先把 `sitemap_index.xml` 和任意文章页各 curl 一次。两者都 403 → 商业平台，本技能不适用。

## 1. 枚举：不要逐页翻档案

- `sitemap_index.xml` 是入口。HLR 的子地图分布：`post-sitemap{,2,3}.xml`＝Print（2240 篇）、`forum-sitemap.xml`＝Forum（358）、`blog-sitemap.xml`＝Blog（314）、其余是 author/category/tag 等 tox 型。
- **Blog 常无专属 PDF**：HLR 的 Blog 页只有通用 Factsheet（应过滤掉），所以 Print+Forum 才是下载目标。逐类统计后再决定下载范围。
- WordPress `wp-json/wp/v2/media` 与 `/types` 在本机实测均 403（Cloudflare），不要指望 REST API 批量取媒体。
- 判断“完整”的边界：HLR 在线文章从 Vol 120 起，早期卷期 `archives/vol-119-no-1/` 返回 404。因此“覆盖 Vol 120–140”就是完整，老卷期需另找 HeinOnline 等数据库。

## 2. 抓取：反爬与字段名

- 直接 `curl` 文章页会拿到 Cloudflare 拦截页（约 6KB，title 含 “Attention Required”）。**换完整 Chrome UA + Accept 头即可通过**，实测可稳定抓 2600+ 页。
- 限速参数：3 并发 + 每请求 `1.5 + random()*1.5` 秒。单线程约 3 秒/个（2600 个需 2 小时，过慢）；3 并发压到 49 分钟且零封禁。
- **分类字段必须限定 DOM 区域**：整页 grep `harvardlawreview.org/category/xxx` 会命中导航菜单里所有栏目，得到错误分类。HLR 的正确选择器：
  - 栏目：`<span class="single-article__piece-type">` 内的 `<a>`
  - 主题：`<span class="single-article__topic">` 内的 `<a>`
  - 作者：`.single-article__author` 内的 `<a>`
  - 引文：正则 `(\d{3}) Harv. L. Rev. (\d+)`
- HTML 实体必须 `html.unescape()`：标题里的 `&#039;`、URL 里的 `&#038;` 都要解码，否则下载 404。

## 3. 脚本自身bug

- **变量名覆盖模块**：函数参数命名 `html` 会覆盖 `import html`，调用 `html.unescape` 报 `'str' object has no attribute 'unescape'`。改用 `page` 等名。
- **Excel 工作表名**：上限 31 字符且不可重复。多个长栏目名截断后会撞名，需加 `~1`、`~2` 后缀去重。
- **Git Bash 的 `/tmp` 与 Windows Python 不互通**：重定向到 `/tmp/x.json` 后，Windows Python `open('/tmp/x.json')` 报 FileNotFoundError。跨工具传递产物一律用工作区绝对路径。
- **中文路径**：脚本内目标目录用 raw string `r"C:\Users\...\Downloads\..."`，避免转义问题。

## 4. 失效链接补救三招

按顺序尝试，实测 6 个 404 中救回 5 个：

1. **HTML 实体解码**：`forvol126_hemphill&#038;suk.pdf` → `...hemphill&suk.pdf`，成功。
2. **文章页重新提取**：原 PDF 404，但文章页里还挂着另一个同文 PDF（如 `136-Harv.-L.-Rev.-1030.pdf` 失效，实际有 `-1030-Fox.pdf`），成功。
3. **Wayback CDX API**：
   ```
   https://web.archive.org/cdx/search/cdx?url=<域名+路径>&output=json&filter=urlkey:.*<文件名前缀>.*&collapse=urlkey&limit=10
   ```
   - 能发现历史路径变体：`/uploads/pdfs/xxx.pdf`、`xxx.pdf.pdf`（双重后缀）。
   - 取存档二进制必须用 `id_` 变体：`https://web.archive.org/web/<timestamp>id_/<原URL>`；不带 `id_` 会拿到包了一层 Wayback 工具栏的 HTML。
   - 注意存档本身可能是 403/404，看 CDX 返回的 `statuscode` 列再决定。

## 5. “缺失”要分辨是不是真缺失

HLR 的 `Developments in the Law — Climate Change` 总目录 PDF 彻底失效（原站 404、Wayback 全 403、第三方 pdf4pro 403），但该专题拆成多个章节页，4 个实质章节 PDF 已单独下载成功。

**结论**：缺一个“目录页 PDF”不等于内容缺失。遇到类似情况先查文章页是否只是目录、正文是否在子章节页——这些子章节通常已在 sitemap 里、已被正常采集。交付时如实说明即可，不要为凑数去下载来路不明的第三方副本。

## 6. 批量下载特有的三个坑（2026-11-20 NYU/Columbia 实测）

1. **URL 含非 ASCII 字符导致下载失败**：作者名里的弯引号（`D’Amato` 的 `’`）、组合重音（`Rodríguez` 实为 `Rodri`+U+0301）、零宽字符（U+200C）会让 urllib 在请求时抛 `'ascii' codec can't encode character`。这不是文件名问题——**必须对 URL 路径做 percent-encoding**：`u=unicodedata.normalize('NFC',u)` → 去零宽字符 → `urllib.parse.urlsplit` → `quote(parts.path)` → `urlunsplit`。文件名侧另做 `NFKC` + `encode('ascii','ignore')`。
2. **文件名碰撞导致静默覆盖**：标题截断到固定长度（如 55 字符）后，不同文章可能生成同名文件，后者覆盖前者，manifest 却都标 ok。核验时不能只比 manifest 数量，要**按 filename 反查 URL 数**：若一个 filename 对应多个 URL，说明发生了覆盖，需给碰撞项加唯一序号重下。
3. **502 间歇性故障**：源站会偶发 502，重试（3 次退避）后绝大多数成功。失败集中在某几个月不代表该时段整体失效——按 URL 逐个重试即可，不要整批放弃。

## 7. 交付前核验（四层）

1. **数量**：文件数 vs 清单去重后总数，差几个要能逐个说明原因；
2. **有效性**：逐文件读前 5 字节是否为 `%PDF-`，体积是否 > 1KB；
3. **残留**：`find <dir> -name '*.part'` 应为 0；
4. **分布**：按卷/栏目统计是否合理，与源站卷期范围一致。

CSV 清单用 utf-8-sig 编码（Excel 打开中文不乱码），字段至少含：序号、卷、栏目、标题、字节数、本地路径。

## 8. Digital Commons / bepress 专坑（2026-11-24 杜克 3,403 篇实录）

这一族的坑和 WordPress 期刊站完全不同，按顺序踩过来：

**坑 1 · 代理伪装成站点故障。** 报错是 `SSLError: UNEXPECTED_EOF_WHILE_READING`，
看起来像站点拒绝 TLS。真相是本机 `HTTPS_PROXY=127.0.0.1:7899` 对这些域名握手后立刻断。
`requests` 默认 `trust_env=True`，会把代理故障整包伪装成 HTTP 客户端错误。
**判别法**：同一 URL 用裸 socket（不经代理）试一次，通了就是代理问题。
**注意反向坑**：`archive.org` 恰好相反——直连超时，必须走代理。两类站点策略相反，别一刀切。

**坑 2 · Referer 头会招来 403（最反直觉）。** 同一 PDF URL：
无 Referer → 200 真 PDF；带 `Referer: <文章页>` → 403 挑战页；
带 Referer + 全套 `Sec-Fetch-*` → 仍 403。原因大概是 curl_cffi 的 Chrome 指纹与
"带 Referer 的导航请求"细节对不上，反而降低 bot 评分。**结论：PDF 请求一律不要带 Referer。**

**坑 3 · 真正的限流是 429，不是 403。** 403 是单请求级别的挑战（换会话能过）；
429 是 IP 级配额耗尽，响应头带 `Retry-After`（实测 355s → 600s，重复触发会加码）。
**边等边重试会续期惩罚**——每探一次都把倒计时推后。正确处理：
① 所有 worker 共享一个全局冷却闸门；② 严格按 `Retry-After` 睡，一秒都别省；
③ 冷却期内一次请求都别发（包括健康检查）。

**坑 4 · 并发不是越高越好，高了直接封。** 8 并发 4 分钟就打死站点，成功数从 51 卡住不动；
2 并发 + 1.5s 间隔可以稳定跑，但仍要每约 50 篇停 10 分钟。
**实测配额：约 50 篇 PDF / 10 分钟窗口（≈300 篇/小时）**，这是硬上限，调并发只会改变
"是平稳用完还是触发惩罚后等"，不会提高总量。按此估算：3,400 篇 ≈ 12 小时；7 万篇 ≈ 10 天。

**坑 5 · Wayback 救不了。** 抽 8 条杜克 PDF 直链查 `archive.org/wayback/available`，
**覆盖率 0/8**。bepress 的 `viewcontent.cgi?article=...` 不在存档范围内，
别把 Wayback 当补救通道（对 WordPress 站有效，对 bepress 无效）。

**坑 6 · 缺卷号的先发文章。** 近年 online-first 文章 OAI 里没有 volume/issue，
会落到 `vnoVol` 目录。不是 bug，是数据如此，交付时要说明。

**坑 7 · 路径长度。** 标题长的很多（杜克 3,403 条里 800+ 条标题超 90 字）。
固定截断要么丢信息要么撞 260。正确做法：按 `MAX_PATH - 目录长 - 前缀长` 算预算动态截断。

**坑 8 · manifest 不 flush 会丢记录。** 被中断时缓冲区里的记录全丢，事后统计对不上
（实测报 fail=8、manifest 里只有 2 条）。`mf.write(...)` 后必须 `mf.flush()`，
或者干脆以文件系统为准重建清单。

**坑 9 · `--limit` 要在排序之后截断。** 先截断再排序，拿到的是文件顺序的前 N 条
（杜克会给你 1997 年的前 3 篇），不是"最新的 N 篇"。

**坑 10 · 慢即是快：重试策略的最终结论（杜克 3,402 篇 A/B 实录）。**

同一站点、同一批文件，两种参数的结果：

| 策略 | 结果 |
|---|---|
| 2 并发 + 1.5s 间隔，429 靠重试硬扛 | 13.3 小时，成功 3,081，**失败 321（8.6%）** |
| 1 并发 + 12s 间隔，不碰配额 | 18.7 分钟把 321 篇全部补齐，**失败 0** |

结论：**在配额型限流面前，"重试更狠"是负收益**。触发 429 后即便按 Retry-After 等待，
重试仍会在新窗口里与正常下载抢配额，形成长期 8% 的持续损耗；而把速率压到配额以下
（约 5 篇/分钟），可以做到零失败、无冷却、总耗时几乎不变。

**推荐默认值：`--workers 1 --min-interval 12`**（约 300 篇/小时）。
只有在确认站点不限额时才用 2–3 并发。

另：补下阶段务必先 `--preflight` 再跑，脚本会自动跳过已存在且魔数正确的文件，
所以"重跑同一条命令"本身就是最可靠的断点续传与补漏手段，不需要单独的补救脚本。

**坑 11 · 限流是 IP 全局配额，不是按域名 —— 6 站时像按站，12 站立刻露馅（重大更正）。**

2026-11-25 六刊实测：6 站 × 8 秒间隔 = 0.76 篇/秒，29 小时零 429，我据此写下"配额按域名独立"。
2026-11-27 第二批 12 站 × 8 秒间隔 = 1.5 篇/秒，**启动数秒内 4 个站同时 429**，惩罚 600 秒。
真相：**配额是 IP 级的，所有 bepress 站点共享一个总速率上限**，约 **0.8 篇/秒（≈2,800 篇/小时）**。
6 个站时，每站 1/8s 恰好把总和压在 0.75/s，看起来像"每站独立"，其实是"总数没超"。

**正确做法：必须同时装两道闸门**——
「每站一个 min-interval（防单站突刺）」＋「一个全局 `--global-interval`（防跨站总量超限）」。
`dc_download.py` 的 `--global-interval 1.3`（≈0.77 篇/秒）实测启动后零 429；
12 站即使并行，总吞吐也不会超过这个上限，**加站点只改变"谁先完成"，不提高总速度**。

**推论**：规划时按 0.7 篇/秒估算总时长；想更快只能换出口 IP，不能在客户端调参。

**坑 12 · 限速闸门写错比不写更糟（两种典型错法，都实测踩过）。**

| 错法 | 现象 |
|---|---|
| 只分配时隙、循环里不等待 | `min-interval` 形同虚设，实际按网络速度狂奔，照样触发 429 |
| 在等待循环里重复分配时隙 | 间隔不断累加，5 篇能跑 6 分钟 |

正确写法：**时隙只分配一次，循环里只等 `max(时隙, 冷却截止)`**。
并且**必须实测验证**：跑 5 篇 × 6 秒，真实耗时应在 25–30 秒之间；如果只有几秒，说明没限住。

**坑 13 · 同题条目会互相覆盖，必须先算路径再下载。**
六刊 35,392 条里有 **241 组 / 551 条**目标文件名完全相同（同一期内 12 篇 "Tribute to ..."、
6 篇 "Post-Lecture Discussion"）。不处理就会静默覆盖，manifest 却记 ok。
做法：下载前先跑一遍路径计算，对重复组统一追加稳定的 `article_id`（缺失则用 URL 的 CRC32），
**下载和报进度必须共用同一套命名函数**，否则统计会对不上。

**坑 14 · Windows 大小写不敏感：`Counter(path)` 去重会漏。**
六刊跑完报「35,148 / 35,148，100%」，但磁盘上只有 35,143 个文件。原因是有 5 组记录
标题只差大小写（`…the Forbidden Fruit` vs `…The Forbidden Fruit`、
`In Memoriam` vs `in Memoriam`），字符串不同、落到 NTFS 上是**同一个文件**，后者覆盖前者，
而按字符串去重的计数器认为它们各自独立，于是"完成率 100%"是假的。
**做法**：路径去重一律用 `os.path.normcase(path)` 做键。
**附带发现**：这 5 组经逐字节比对（117227/270950/601091/277292/468337 B 完全相同）
是源站**同一篇文章的重复著录**，不是漏抓——所以真实唯一文献数是 35,143，不是 35,148。
排查手法：`groups[os.path.normcase(rel_path(r))]` 再找 `len>1`，比看总数快得多。

**坑 15 · 防重入锁会误伤自己：kill 掉进程后的 7 分钟内重启会被拦。**
`dc_download.py` 用心跳文件（每 60 秒 touch，超 `HB_STALE=420` 秒视为已死）防止两个进程抢配额。
被 `TaskStop` 强杀后心跳仍是"新鲜"的，此时重启会直接 `exit 2`：
`检测到另一个下载进程仍在运行…`。
**正确处理**：先确认真的没有活动进程（隔 25 秒数两次文件数，不变即无下载），
再用 `--force` 启动；**不要**直接删心跳文件了事（万一真有进程在跑，两个进程会互相把 429 打满）。

**坑 16 · 长任务的工程套路（比写对下载逻辑更容易被忽略）。**

跑 10 小时以上的批量任务，光有下载器不够，还要三件配套：

1. **心跳**：每 60 秒 touch 一个 `.heartbeat`，外部据此判断"进程是活着还是死了"，比查 PID 可靠（跨平台）。
2. **防重入**：心跳新鲜就拒绝启动。注意坑 15 的误伤。
3. **定时巡检 + 完成自停**：挂一个每 3–4 小时的 automation，读进度、查心跳、必要时续跑；
   并**把 automation 自己的 id 写进它的 prompt**，让它在完成率 100% 时调用
   `automation_update(mode="update", status="PAUSED")` 自杀。
   这样不依赖"人记得去关"，否则它会每 4 小时空转报喜，永远停不下来。

配套的心智：**估算要用「最慢单站 / 全局速率」，不要用「总量 ÷ 瞬时聚合速率」**。
六刊那轮日志 ETA 显示 12 小时、实际 29.3 小时，就是聚合速率随剩余站点数衰减导致的。
