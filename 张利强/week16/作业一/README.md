基于前文的架构设计和技术约束，以下是分别为两个Skill编写的 `README.md` 文件。你可以直接将它们分别放入 OpenCode 的 `skills/esg-monthly-report/` 和 `skills/esg-bid-monitor/` 目录下。

---

### 文件一：`skills/esg-monthly-report/README.md`

```markdown
# ESG 月报生成 Skill (中国神华版)

## 1. 简介
本 Skill 基于 OpenCode 框架，专为**中国神华**定制开发。它利用 Qwen3.8-flash 模型与 DeepSeek Search API，自动检索、筛选并汇总过去一个自然月内的国内 ESG 政策、行业动态及中国神华自身动态，最终生成包含影响建议的简短摘要报告。

## 2. 核心特性
*   **多 Agent 协作**：拆分搜索、筛选、撰写、校验四个独立阶段，避免模型幻觉交叉污染。
*   **硬时间约束**：自然月的起止时间由系统调度器注入，严禁模型自行猜测“最近一个月”。
*   **AI 自主对标**：根据中国神华的业务属性，AI 自动圈定不超过 4 家同行业对标企业（首次运行后固化，保证月报可比性）。
*   **句句有源**：报告中每一条事实陈述必须携带 `[来源: URL]`。
*   **零幻觉兜底**：严格遵循“未检索到即写‘暂无数据’”的原则，禁止使用模型参数化知识补全。

## 3. 目录结构
```text
esg-monthly-report/
├── SKILL.md                   # OpenCode 技能入口定义
├── agents/
│   ├── policy_search.md       # 政策与标准搜索 Agent
│   ├── industry_peer_search.md# 行业与对标搜索 Agent
│   ├── shenhua_search.md      # 神华动态搜索 Agent
│   ├── filter.md              # 数据清洗与去重 Agent
│   ├── writer.md              # 报告撰写 Agent
│   └── validator.md           # 校验 Agent
├── templates/
│   └── report.md              # 简报 Markdown 模板
└── peer_set.json              # 对标企业固化名单 (运行时生成)
```

## 4. 工作流说明
1.  **调度触发**：每月第 1 个工作日运行，自动注入参数 `target_month` (格式: `YYYY-MM`)。
2.  **并行搜索**：`policy_search`、`industry_peer_search`、`shenhua_search` 同时调用 DeepSeek Search API (`https://api.deepseek.com/v1/tools/search`)，限定 `site:gov.cn`, `site:sse.com.cn` 等国内权威域名。
3.  **过滤与清洗**：`filter` 节点剔除不在目标自然月内的数据，并根据 URL 去重。
4.  **撰写与校验**：`writer` 按模板生成约 800-1200 字的摘要。`validator` 进行最后审查，删除无来源的陈述，修正日期越界的引用。
5.  **输出**：在 OpenCode 对话框输出 Markdown 全文，并自动转换为 PDF 附件提供下载。无需人工预览确认。

## 5. 依赖配置
*   **LLM**: Qwen3.8-flash
*   **Search API**: `https://api.deepseek.com/v1/tools/search` (需配置 API Key)
*   **语言**: 仅限简体中文检索与输出
*   **Python 组件**: 无特殊需求，纯文本与 Markdown 渲染

## 6. 运行参数说明
*   `target_month` (必填): 格式 `YYYY-MM`。
*   `include_peers` (可选): 是否强制更新对标企业（默认 `false`，复用 `peer_set.json`）。
```

---

### 文件二：`skills/esg-bid-monitor/README.md`

```markdown
# ESG 招投标信息监控 Skill (中国神华版)

## 1. 简介
本 Skill 用于监控国内 ESG、可持续发展、双碳相关的中标/招标信息。包含两大核心工作流：**近 2 年历史数据汇总与分析（含可视化图表）**，以及**每日新增招标信息推送**。

## 2. 核心特性
*   **分片切片搜索**：针对 2 年历史跨度，采用“半年度”+“关键词组合”的切片策略，突破 DeepSeek Search 的召回限制。
*   **统一数据结构**：所有搜索结果强制落盘为 JSON Schema，字段包含：项目名称、买方、中标方、金额、发布日期等。
*   **Python 可视化**：自动调用 Python (Matplotlib/Pandas) 对中标金额进行分桶统计，生成柱状图和饼图并插入报告。
*   **双轨制运行**：历史汇总按月/季度跑，每日新增按日跑，每日数据自动沉淀至 `daily_buffer.json`，实现样本累积。
*   **严格数据处理**：金额单位自动统一为“万元”，不明确则留空（`暂无数据`）；区分“招标公告”与“中标结果”。

## 3. 目录结构
```text
esg-bid-monitor/
├── SKILL.md                   # OpenCode 技能入口定义
├── agents/
│   ├── slice_search.md        # 历史分片搜索 Agent
│   ├── extract.md             # 统一 Schema 抽取 Agent
│   ├── dedupe.md              # 去重与合并 Agent
│   ├── daily_push.md          # 每日简报生成 Agent
│   └── writer.md              # 综合报告生成 Agent
├── scripts/
│   └── chart.py               # 金额分布可视化脚本
└── buffer/
    └── daily_buffer.json      # 每日增量数据存储池
```

## 4. 工作流说明

### 工作流 A：过去 2 年历史汇总
1.  **触发**：首次部署或按季度手动触发。
2.  **分片搜索**：`slice_search` 遍历半年度时间切片，组合关键词检索。
3.  **抽取与合并**：`extract` 读取搜索结果并结构化，`dedupe` 清洗合并，并追加读取 `daily_buffer.json` 中的历史积累数据。
4.  **图表生成**：调用 `scripts/chart.py` 传入数据集，生成 `esg_bid_dist.png`（金额分桶柱状图 + 饼图）。
5.  **报告输出**：归纳买方类型与高频项目词，生成带图表的 Markdown 分析报告，并在对话框展示、生成 PDF。

### 工作流 B：每日新增推送
1.  **触发**：每日 08:00 定时运行。时间窗口固定为 `[昨天 00:00, 今天 00:00]`。
2.  **检索与抽取**：搜索当日新标讯，使用 `extract` 抽取。
3.  **推送与沉淀**：在平台对话框输出每日列表，同时将记录追加写入 `daily_buffer.json`。若当日无记录，输出“暂无数据”。

## 5. 可视化约束
*   **分桶规则**：`≤50万`、`50-100万`、`100-200万`、`200-500万`、`>500万`。
*   **样本量限制**：若有效记录少于 5 条，仅生成柱状图并在报告中标注“样本量较小，分布仅供参考”；若无有效记录，则不生成图片。

## 6. 依赖配置
*   **LLM**: Qwen3.8-flash
*   **Search API**: `https://api.deepseek.com/v1/tools/search` (需配置 API Key)
*   **Python 环境**: 需安装 `pandas`, `matplotlib` 库以支持代码解释器或外部脚本运行。
*   **时区**: 默认使用 Asia/Shanghai (UTC+8)。

## 7. 核心字段 Schema 说明 (JSON)
```json
{
  "project_name": "项目名称全称",
  "buyer": "买方全称(禁止简写)",
  "winner": "中标方全称(禁止简写,若无则留空)",
  "amount_wan": "金额数值(单位:万元,仅接受数字,无明确金额则设为null)",
  "publish_date": "YYYY-MM-DD",
  "category": "ESG/可持续/双碳(不细分)",
  "source_url": "来源链接"
}
```
*注意：若原文是“招标公告”且无中标结果，`winner` 和 `amount_wan` 均填入 `null`，但仍计入“热点招标情况”。*
```