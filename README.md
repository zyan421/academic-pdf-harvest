# academic-pdf-harvest

学术期刊 / 法学院仓储的 **全量 PDF 采集与下载** 技能。

把「某本期刊有多少篇文章、PDF 在哪、怎么一次不漏地下完」这件事做成可复用的流水线，
而不是每次都重写爬虫。已在 19 家美国法学院 Digital Commons 仓储与 4 家独立期刊站上实测跑通，
累计下载约 **7.7 万篇 / 72 GB**。

## 覆盖两类站点

| 类型 | 枚举方式 | 关键点 |
|---|---|---|
| WordPress 期刊站（如 Harvard/NYU/Columbia Law Review） | 官方 `sitemap_index.xml` 分片 | PDF 直链在 `/wp-content/uploads/YYYY/MM/` |
| Digital Commons / bepress 法学院仓储（400+ 种期刊） | OAI-PMH `metadataPrefix=document-export` | 每条记录直接带 `fulltext-url`，每请求 100 条，比爬文章页省 99% 请求 |

## 内容

```
SKILL.md                       技能主文档（何时用、两类站点的流程、硬约束）
references/pitfalls.md         16 条实测踩坑记录（按踩坑顺序）
references/site-registry.md    站点登记表：A/B/C 分级 + 19 家仓储参数 + 量产实测数据
scripts/harvest.py             WordPress 站：sitemap 枚举
scripts/build_catalog.py       生成 Excel / Markdown 清单
scripts/download.py            通用 PDF 批量下载
scripts/retry.py               失效链接补救（Wayback CDX 等）
scripts/verify.py              四层交付核验
scripts/dc_catalog.py          Digital Commons：OAI-PMH 全量元数据（带 PDF 直链）
scripts/dc_build_catalog.py    Digital Commons：汇总成 Excel / CSV
scripts/dc_download.py         Digital Commons：分站点限速下载（含全局闸门、断点续传、防重入）
```

## 安装

WorkBuddy / 支持 skill 目录的 agent，把仓库放到用户级技能目录即可：

```bash
git clone https://github.com/zyan421/academic-pdf-harvest.git \
  ~/.workbuddy/skills/academic-pdf-harvest
```

Windows（PowerShell）：

```powershell
git clone https://github.com/zyan421/academic-pdf-harvest.git `
  "$env:USERPROFILE\.workbuddy\skills\academic-pdf-harvest"
```

> 本仓库是 **public**，克隆不需要任何认证。
> 若克隆时被要求输入用户名密码、或在非交互环境中长时间无输出挂起，几乎一定是
> 仓库不可见（私有或名字写错）——GitHub 对「不存在」和「无权限」都会回 401，
> 而 git 收到 401 就转交互式认证，非交互环境下就表现为卡住。
> 快速自检：`GIT_TERMINAL_PROMPT=0 git ls-remote <仓库地址>`，能立刻失败而不是挂起。

## 最小可用命令（Digital Commons）

```powershell
$PY = "C:\Users\<你>\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
& $PY dc_catalog.py --only Duke          # 1 拉全量元数据
& $PY dc_build_catalog.py                # 2 生成 Excel 目录
& $PY dc_download.py --journals Duke --preflight   # 3 下载前体检
& $PY dc_download.py --journals Duke --min-interval 8 --global-interval 1.3
```

## 三条最容易踩的坑

1. **本机代理会把这类站点掐断**，报错却是 `SSL: UNEXPECTED_EOF`，看起来像站点拒绝。先清 `HTTP(S)_PROXY`。
2. **PDF 请求不能带 `Referer`**——带了必 403，不带反而 200。
3. **限流是 IP 全局配额**（约 0.8 篇/秒），不是按站点——必须同时装每站间隔与全局限速两道闸门。

完整清单见 `references/pitfalls.md`。

## 使用边界

仅适用于**公开可访问**的 PDF。付费墙、需登录的数据库（HeinOnline、JSTOR、Oxford Academic）
不在范围内。批量下载请遵守站点 robots.txt 与服务条款，控制速率；采集结果供个人研究使用。
