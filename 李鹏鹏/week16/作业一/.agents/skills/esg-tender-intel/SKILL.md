---
name: esg-tender-intel
description: ESG/可持续发展/双碳招投标情报：汇总历史中标情况并分析热点赛道与金额分布，支持每日增量监控与推送。用于「ESG 招标」「双碳中标数据」「碳中和项目招采分析」「每天推送招标信息」「招投标监测」等请求。
allowed-tools: WebSearch, WebFetch, Bash, Read, Write
---

# ESG 招投标情报技能

一份可复用的招采情报流水线：**采集 → 清洗入库 → 统计出图 → 出报告 → 每日推送**。
两个交付物共用一套数据底座：历史市场分析（过去 2 年）与增量监控（每日新公告）。

## 何时使用

- 需要汇总某段时间内 ESG / 可持续发展 / 双碳相关的中标情况，分析热点赛道与金额分布
- 需要监控新发布的 ESG 相关招标，每天/每周推送新增信息
- 需要为投标决策提供"钱在哪个细分、什么时间发、由谁发"的判断依据

不适用：需要实时竞价数据、需要供应商报价明细（公开渠道拿不到）。

## 硬性质量线

1. **金额口径单一**：金额只从**标题**解析（标题里的才是合同额），绝不从正文抓——正文的亿元级数字多为市场统计，会造成数量级错误。
2. **必须声明覆盖率**：所有金额类结论都要标注"可定价样本占比"。覆盖率低于 50% 时，禁止用金额合计反推市场规模。
3. **区分招标与中标**：分析"中标情况"只能用 `kind='中标/成交'` 的记录，混入招标阶段的预算价会高估。
4. **中标人不可推测**：公告打码的一律写"未公开"，不得通过常识补全。
5. **每条可溯源**：保留原文链接，报告明细表逐条可回查。

## 数据结构

SQLite 单表 `tenders`（默认 `data/tenders.db`，可用 `--db` 指定）：

| 字段 | 说明 |
|---|---|
| `uid` | 标题+链接 的 sha256 前 16 位，主键，天然去重 |
| `title` | 公告标题（含金额与项目名） |
| `buyer` / `winner` | 采购人 / 中标人；未公开留空，不推测 |
| `amount_wan` | 金额，统一折算为**万元**；无则空串 |
| `publish_date` | `YYYY-MM-DD`；越界（晚于今天或早于 2015）自动丢弃 |
| `category` | 赛道，按 `CATEGORY_RULES` 优先级匹配，10 类 |
| `kind` | `招标/采购` / `中标/成交` / `其他` |
| `region` / `buyer_type` | 省级地域（含地级市映射）/ 采购人类型 |
| `source` / `url` / `evidence` | 来源站 / 原文链接 / 抽取原文片段 |
| `pushed` | 0 未推送、1 已推送（保证推送不重复打扰） |

## 流程 A：历史基线分析（过去 2 年）

### A1 确定口径

先锁定三个参数并写在报告首页：统计期（如 2024-11-24 ~ 2026-11-24）、关键词范围、地域范围。

关键词矩阵见 `references/keyword-matrix.md`，**至少覆盖 4 个簇**：披露类（ESG报告/可持续发展报告）、核算类（碳核查/碳核算/碳足迹）、资产类（碳资产/CCER/碳交易）、战略类（双碳/碳中和/CBAM/绿色金融）。只搜"ESG"会漏掉 80% 的碳类项目。

### A2 采集

```bash
# 聚合站批量抓（标题自带金额，最省事；--detail 补日期）
python scripts/tender_intel.py collect --source 203060 --pages 2 --detail \
    --kw ESG ESG报告 碳核查 碳足迹 双碳 可持续发展报告

# 也可把 agent 检索到的结构化结果入库（推荐用于补中标人字段）
python scripts/tender_intel.py ingest data/seeds/*.json
```

JSON 记录格式（字段可缺省，`ingest` 会自动补 category/kind/region/amount/uid）：

```json
{"title":"…ESG报告编制服务结果公告","buyer":"某公司","winner":"某咨询公司",
 "amount_wan":53.4,"publish_date":"2026-11-18","url":"https://…","source":"电力能源招标网",
 "evidence":"成交价 534000.00 元"}
```

### A3 清洗校验（不要跳过）

```bash
python scripts/tender_intel.py analyze --since 2024-11-24 --json-out stats.json
```

看三个数：`n_total`（有效公告数）、`n_with_amount`/`amount_coverage`（可定价率）、`amount_max`（是否异常）。
若 `amount_max` 超过 10 万万元，说明抽到了市场统计数据，需回查该条记录的 `title`/`evidence`。

### A4 出报告

```bash
python scripts/tender_intel.py report --since 2024-11-24 --until 2026-11-24 \
    --assets reports/assets --meta meta.json \
    --out reports/ESG招投标分析.md --html reports/ESG招投标分析.html
```

`--meta` 是人工解读层（JSON），决定报告质量，**这是本技能的关键**：脚本负责数字，人负责判断。必填字段：

| 字段 | 作用 |
|---|---|
| `tldr` | 5 条核心结论，每条含数字 |
| `market_reading` / `category_reading` / `price_reading` | 对应章节的解读 |
| `buyer_reading` / `winner_reading` / `region_reading` | 对应章节的解读 |
| `actions` | 对乙方（怎么打）与甲方（怎么买）的具体建议 |
| `caveat` | 数据口径与局限，必须写 |

报告自动产出 6 张图：月度节奏（柱+线双轴）、赛道分布、金额区间、区域分布，以及 10 个章节的完整结构（含可溯源明细表）。

## 流程 B：每日增量监控推送

```bash
# 1) 增量采集（幂等，重复跑只会更新 last_seen）
python scripts/tender_intel.py collect --source 203060 --pages 1 --detail --kw ESG 碳核查 碳足迹 双碳

# 2) 生成当日推送摘要（只推未推送过的，推完打 pushed=1）
python scripts/tender_intel.py push --days 1 --out reports/日报_$(date +%F).md
```

推送策略（`build_push` 已内置）：

- **优先关注区**：金额 ≥ 50 万元的项目单列，附赛道/地域/日期
- **全部新增区**：表格化，含原文链接
- **去重保障**：`pushed` 标记，第二次运行返回 0 条，不会重复打扰

### 定时执行

Windows（任务计划程序，每个工作日 08:30）：

```bat
schtasks /create /tn "ESG招标日报" /tr "E:\...\py312\python.exe E:\...\tender_intel.py collect --source 203060 --pages 1 --kw ESG 碳核查 碳足迹 双碳 && E:\...\python.exe E:\...\tender_intel.py push --days 1 --out reports\日报.md" /sc weekly /d MON,TUE,WED,THU,FRI /st 08:30
```

Linux/macOS（cron）：

```cron
30 8 * * 1-5 cd /path/to/skill && python scripts/tender_intel.py collect --source 203060 --pages 1 --kw ESG 碳核查 双碳 && python scripts/tender_intel.py push --days 1 --out reports/日报.md
```

投递环节（邮件 / 企业微信 / 飞书）不在本技能内实现：`push` 只产出 Markdown，交给现有通知脚本或 CI 转发即可，避免把渠道密钥写进技能。

## 分析口径（写报告前必须对齐）

| 问题 | 正确做法 | 错误做法 |
|---|---|---|
| 市场规模怎么算 | 报"可核验下限"+覆盖率，说明未披露部分 | 用金额合计当市场规模 |
| 中标情况 | 只统计 `kind='中标/成交'` | 把招标预算价当成交价 |
| 单价怎么比 | 同赛道内比，且区分是否多年期框架 | 跨赛道平均价对比 |
| 供应商格局 | 只在"可识别中标人"子集上下结论，注明样本量 | 用 20 条样本推断市场份额 |
| 区域结论 | 说明"未标注"占比 | 忽略 60% 未标注直接排名 |

## 常见坑

- **金额被正文污染**：曾经因从正文取金额，把"绿色债券发行 2177 亿元"写成单笔中标 2.1 万亿元。金额只认标题。
- **图标字体混进标题**：聚合站用私有区字符（U+E000–U+F8FF）做图标，入库前必须剥离，否则标题首字符是乱码方块。
- **研究报告当成招标**：文库站混有白皮书、分析报告、职位报告。`is_tender()` 只对 `kind='其他'` 生效，过滤词表见 `DOC_NOISE`。
- **详情页日期错位**：详情页常出现"截止日""下一年度"等年份，`parse_date` 已限定 ≤ 今天且 ≥ 2015。
- **重复公告**：同一项目在招标/中标阶段各有一条公告，属正常现象，不要按标题相似度硬合并（会丢失阶段信息）。
- **政务网站不可达**：`search.ccgp.gov.cn` 常超时、`deal.ggzy.gov.cn` 解析失败，详见 `references/sources.md` 的实测结论，不要把任务建立在不可达源上。

## 目录约定

```text
esg-tender-intel/
├── SKILL.md
├── scripts/tender_intel.py     # 采集/入库/统计/报告/推送 单文件 CLI
├── references/
│   ├── keyword-matrix.md       # 关键词矩阵与检索式
│   └── sources.md             # 数据源清单与可达性实测
└── data/tenders.db             # SQLite（首次运行自动创建）
```