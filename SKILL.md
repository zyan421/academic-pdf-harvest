---
name: academic-pdf-harvest
description: 把学术期刊或网站上的文献，做成全量 PDF 链接清单并批量下载到本地。覆盖两类站点：WordPress 期刊站（走 sitemap 枚举）与 Digital Commons / bepress 法学院仓储（走 OAI-PMH 的 document-export，每条记录直带 PDF 直链）。适用场景：抓取某期刊全部 PDF 目录、整理某网站文献清单、按 URL 清单批量下载 PDF、Digital Commons 站点采集、确保一个不漏。含 8 个已验证脚本、19 家仓储参数表与 16 条踩坑记录。
---

# 学术站点 PDF 全量采集与下载

## 什么时候用

- 需要把某个学术期刊/学会网站的**全部**文献 PDF 整理成清单（Excel / Markdown / CSV）。
- 需要按 URL 清单**批量下载 PDF 到本地**，且要求完整、限速、可断点续传。
- 需要核验“是否遗漏”，并补救失效链接。

**不适用**：单篇文献下载（直接 curl 即可）；付费墙/需登录数据库（本技能只处理公开可访问页面）；把文献导入知识库（那是 `ima-skills` / `wechat-mp-to-ima` 的事，且注意 PDF 直链在 ima 里是空壳）。

## 核心认知（先读，否则必踩坑）

1. **全量枚举的唯一可靠入口是官方 sitemap**。WordPress 站点的 `/wp-json/wp/v2/*` 常被 Cloudflare 403；逐页翻档案既慢又易漏。先取 `https://<站点>/sitemap_index.xml`，再挑出内容型子地图。
2. **“导入成功”不等于“内容可用”**。任何批量操作后都要做内容级核验，不能只看返回码。
3. **限速是硬要求**。3 并发 + 每请求 1.5–3 秒随机间隔是实测安全值；单线程过慢（约 3 秒/个），高并发会触发反爬。
4. **断点续传 + 魔数校验**。长任务必须能中断恢复；验收必须查 `%PDF-` 文件头和最小体积，不能只看文件存在。

## 分支 A：Digital Commons / bepress 仓储（400+ 法学院期刊，优先走这条）

如果目标站点长这样——`chicagounbound.uchicago.edu`、`scholarship.law.duke.edu`、
`repository.law.umich.edu`、`scholarship.law.cornell.edu` 等，且页脚有 bepress/Digital Commons
字样——**不要走 sitemap，也不要逐页爬文章页**。走 OAI-PMH，一条记录就连着 PDF 直链。

完整流程是三个脚本，`scripts/dc_*.py`：

| 步骤 | 脚本 | 做什么 |
|---|---|---|
| 1 建目录 | `dc_catalog.py` | 走 `document-export`，每请求 100 条，落 `dc_data/jsonl/<短名>.jsonl` |
| 2 出清单 | `dc_build_catalog.py` | 汇总成 Excel（总览 + 全部文献 + 每刊一表）与 CSV |
| 3 下载 | `dc_download.py` | 分站点限速、断点续传、防重入、`%PDF-` 校验，按刊/卷分文件夹 |

标准调用（**先 `--preflight`，再正式跑**）；下面按 PowerShell 写，bash 里把 `& $PY` 换成 `$PY`：

```powershell
$PY = "$env:USERPROFILE\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
# 体检：缺链、同题冲突、路径超长、涉及几个站点
& $PY dc_download.py --journals Chicago,Duke --preflight
# 下载：每站 1 线程、每请求 8 秒
& $PY dc_download.py --journals Chicago,Duke --min-interval 8 --per-host 1 --max-hosts 6
# 只报进度（定时任务用这个）
& $PY dc_download.py --journals Chicago,Duke --report
# 只核验文件
& $PY dc_download.py --journals Chicago,Duke --verify
```

四条**硬约束**，缺任何一条都会失败：

```python
# 1) 必须清空代理（本机 127.0.0.1:7899 会把这些站点掐在 TLS 之后，报 UNEXPECTED_EOF）
for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
# 2) 必须 curl_cffi + impersonate="chrome"（普通 requests/curl 会被 Cloudflare 挡在 PDF 端点）
from curl_cffi import requests as creq
s = creq.Session(impersonate="chrome")
s.get(url, proxies={"http": None, "https": None})
# 3) PDF 请求绝不能带 Referer —— 带了必 403，不带反而 200
# 4) 每 8 个请求重建会话；429 按 Retry-After 全局冷却，403 换会话退避
```

**并发模型（重要，2026-11-27 更正）**：bepress 的配额是 **IP 全局**的，所有站点共享一个
约 **0.8 篇/秒** 的总上限——6 站时看起来像"每站独立"，12 站同时跑就会集体 429。
所以必须装**两道**闸门：每站一个 `--min-interval`（防单站突刺）＋ 一个
`--global-interval`（防跨站总量超限，默认 1.3 ≈ 0.77 篇/秒）。
加站点只改变"谁先完成"，**不提高总速度**；想更快只能换出口 IP。

参数规律与 19 家已实测仓储见 `references/site-registry.md` 的「A 级（续）」，
踩过的 13 个坑见 `references/pitfalls.md` §8。

## 四阶段流水线

### 阶段 0 · 侦察（手工，5 分钟）

**先查 `references/site-registry.md`**：若目标站点已登记（A/B/C 级），直接取用参数或按级别判断可行性，不必重新侦察。

依次确认三件事，决定后续能否"零遗漏"：

```bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
curl -s -L -A "$UA" "https://<站点>/sitemap_index.xml" -o sitemap_index.xml
cat sitemap_index.xml
```

- 列出所有子 sitemap，识别内容型（post / article / forum / blog）与 tox 型（author / category / tag）。
- **确认站点的内容起点**：很多期刊网站只有近若干卷在线（如 HLR 只到 Vol 120 起），早期卷期档案页是 404。查明后才能定义“完整”的边界，并在交付时说明。
- 抽 1–2 篇文章页，确认 PDF 直链的 DOM 位置与正则，以及栏目/主题/作者字段的 class 名。**注意：整页 grep `/category/xxx` 会混入全站导航菜单，必须限定文章 header 区域的 class 前缀。**

### 阶段 1 · 采集（脚本 `scripts/harvest.py`）

从 sitemap 提取文章页 URL，限速抓取，提取 PDF 直链与元数据，输出 jsonl。

需按站点修改脚本顶部常量：`SITEMAP_FILES`、`URL_PATTERNS`（文章页正则）、`PDF_PATTERN`、`TARGET_CLASSES`（栏目/主题/作者）。

```bash
python scripts/harvest.py > harvest.log 2>&1
```

产物：`pdf_catalog.jsonl`（每行一篇：标题、栏目、主题、作者、引文、PDF URL 列表）。脚本自带断点续传与失败重试；跑完必须核对 `missing = 0`。

### 阶段 2 · 生成清单（脚本 `scripts/build_catalog.py`）

把 jsonl 转成多工作表 Excel（总表 + 按出版物 + 按栏目 + 统计）和 Markdown。

需改：`XLSX` / `MD` 输出名、`cols` 字段顺序。注意 Excel 工作表名上限 31 字符且不可重复，脚本已内置去重写名逻辑。

### 阶段 3 · 下载（脚本 `scripts/download.py`）

按清单批量下载，输出到本机文件夹。

需改：`TARGET_DIR`、`WORKERS`（默认 3）、`MIN_DELAY` / `MAX_DELAY`、`UA`。

```bash
python scripts/download.py > download.log 2>&1
```

脚本保证：序号前缀文件名（唯一且可排序）、`.part` 临时文件 + `os.replace` 原子落盘、`%PDF-` 魔数与 1KB 最小体积校验、jsonl manifest 断点续传、失败退避重试 3 次。

### 阶段 4 · 补救与核验（脚本 `scripts/retry.py` + 手工）

失败项按以下顺序补救（详见 `references/pitfalls.md`）：

1. HTML 实体解码（`&#038;` → `&`）后重试；
2. 回到文章页重新提取全部 PDF，常有同文的替代文件；
3. Wayback CDX API 查存档副本，用 `web/<timestamp>id_/<原URL>` 取原始二进制；
4. 检查该文是否拆成多个章节页，章节 PDF 可能已单独存在——此时“目录 PDF 缺失”不等于内容缺失。

最终核验四项：文件总数 vs 清单总数、逐一 `%PDF-` 校验、`.part` 残留数、按卷/栏目分布是否合理。

用 `scripts/verify.py` 一键完成，它会额外查出两类隐蔽错误——**文件名碰撞静默覆盖**（一个 filename 被多个 URL 映射）与 **manifest 标 ok 但文件未落盘**：

```bash
python scripts/verify.py "<下载文件夹>" "<manifest.jsonl>"
```

这两类错误在本次 NYU/Columbia 任务中实际发生过，仅比对数量无法发现，务必运行。

## 铁律清单

- [ ] 先找 sitemap，不逐页猜
- [ ] 确认站点在线范围，明确定义“完整”
- [ ] 抽验 PDF 正则与分类字段 DOM，不用全页 grep
- [ ] 限速 3 并发 + 1.5–3s jitter
- [ ] jsonl 断点续传，长任务可中断
- [ ] 内容级核验（`fetch_media_content` 之类），不只看返回码
- [ ] PDF 魔数 + 最小体积校验
- [ ] 失效链接至少试三招补救
- [ ] 交付时说明遗漏项及为何不构成内容缺失

## 与其他工具的关系

- **ima 知识库**：本技能下载的是本地 PDF。若要导入 ima，注意 **PDF 直链是空壳，必须传文章页 HTML URL**，且 ima 无删除接口——详见用户级记忆的 ima 铁律。
- **夸克网盘**：无“任意 URL 直拉”，只能把本技能的本地产物再 `upload`。
- **中文标点**：本技能生成的 Markdown 属中文文本交付物，收尾跑 `cjk-typography` 的 `cjk_lint.py --fix` + 复检。
