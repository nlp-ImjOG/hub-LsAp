---
name: esg-bid-monitor
description: 监控国内 ESG、可持续发展、双碳相关招投标与中标信息：支持近 2 年半年度分片汇总、金额统一为万元并生成分桶图表，以及每日新增标讯推送。当用户提到“ESG 招投标”“中标监控”“双碳招标”“ESG 标讯日报”“近两年招投标汇总”“招标信息监控”，或要求汇总/监控 ESG 相关招标、中标公告时使用；即使用户没有明确说“监控”，只要任务是招投标信息的汇总或增量追踪，也应使用。
---

# ESG 招投标信息监控（中国神华版）

本 Skill 有两个入口：`history` 做近 2 年历史汇总与分析，`daily` 做每日新增标讯推送。两者共用同一套检索、抽取和去重规则，保证历史数据和每日数据能沉淀到同一个缓冲区。

## 何时使用

- “汇总近两年 ESG/双碳相关的招标和中标信息”
- “每天推送 ESG 招投标新增标讯”
- “看看最近哪些双碳项目在招标，金额分布如何”
- “监控 ESG 相关中标结果，按季度给我一份报告”

不适用于：单条标讯的投标决策、供应商资质审查、非 ESG 主题的招投标。

## 输入

- `mode`（必填）：`history` 或 `daily`。
- `years`（`history` 可选，默认 `2`）：历史汇总的年数。
- `window`（`daily` 可选）：默认 `[昨天 00:00, 今天 00:00]`，时区 `Asia/Shanghai`。
- `output_dir`（可选）：报告与图表输出目录，默认当前目录。

## 统一 Schema

所有抽取结果必须落成同一结构：

```json
{
  "project_name": "项目名称全称",
  "buyer": "买方全称",
  "winner": "中标方全称或 null",
  "amount_wan": 120.5,
  "publish_date": "YYYY-MM-DD",
  "category": "ESG/可持续/双碳",
  "source_url": "https://..."
}
```

- `amount_wan` 只接受万元正数或 `null`；不明确就填 `null`，不要估。`0` 视为无效金额。
- `winner`、`amount_wan` 在“招标公告”阶段可以为 `null`，但记录仍计入热点招标。
- `category` 只取 `ESG`、`可持续`、`双碳` 三者之一，不细分。
- 日期统一 `YYYY-MM-DD`，时区 `Asia/Shanghai`。
- 可选派生字段 `announcement_type`：`tender`（招标公告）或 `award`（中标结果）。它不替代上面 7 个字段，只用于图表区分“招标预算”和“中标金额”。

## 工作流 A：近 2 年历史汇总

1. `agents/slice_search.md`：按半年度切片，组合关键词检索。
2. `agents/extract.md`：把结果转成统一 Schema，金额归一为万元，并尽量标注 `announcement_type`。
3. `agents/dedupe.md`：按 URL 与项目去重，合并历史记录；只返回结果，**不写** `buffer/daily_buffer.json`。历史汇总不污染每日增量缓冲区。
4. 校验记录：

```bash
conda run -n py312 python scripts/validate_records.py --input records.json
```

退出码 1 时回到 `extract` / `dedupe` 修正，不要带违规记录继续画图。

5. 生成图表（默认只统计中标金额）：

```bash
conda run -n py312 python scripts/chart.py \
  --input records.json --output-prefix esg_bid_dist \
  --title "ESG 招投标金额分布"
```

需要把招标预算也画进去时显式加 `--scope all`。

6. `agents/writer.md`：按 `templates/monthly-report.md` 输出分析报告。
7. 需要 PDF 时：

```bash
conda run -n py312 python scripts/md_to_pdf.py --input report.md --output report.pdf
```

### 图表规则

- 分桶：`≤50万`、`50-100万`、`100-200万`、`200-500万`、`>500万`。
- 默认 `--scope award`：`announcement_type=tender` 的记录不进入金额图，避免把招标预算混入中标金额；报告需注明“仅统计中标金额”。
- 有效金额条数 ≥5：柱状图 + 饼图。
- 有效金额条数 1–4：只出柱状图，并标注“样本量较小，分布仅供参考”。
- 有效金额条数 0：不出图（同时删除同前缀的旧 PNG），报告写 `暂无数据`。
- 金额为 `null`、`0`、负数、带“亿/万”单位或非数字时，先由 `extract` 归一；无法归一的不进入图表。

## 工作流 B：每日新增推送

1. 用 `scripts/daily_window.py` 计算窗口 `[昨天 00:00, 今天 00:00]`（`Asia/Shanghai`），不要依赖宿主机时区：

```bash
conda run -n py312 python scripts/daily_window.py
```

2. `agents/slice_search.md` 按该窗口检索；时间跨度小，不需要切片。
3. `agents/extract.md` 抽取，`agents/dedupe.md` 与 `buffer/daily_buffer.json` 比对去重（只比对，不落盘）。
4. 运行 `scripts/validate_records.py --input records.json`，有违规先修正。
5. `agents/daily_push.md` 输出当日列表；没有新增时输出 `暂无数据`，缓冲区不变。
6. 有新记录时，由 `daily_push` **一次性**追加写入 `buffer/daily_buffer.json`，写入前备份为 `.bak`；不要在其他阶段重复写。

## 脚本

- `scripts/search_deepseek.py`：DeepSeek Search API 适配器，密钥 `DEEPSEEK_API_KEY`；缺失时退出 2。
- `scripts/validate_records.py`：校验 Schema、字段类型、日期、金额、URL 和重复项。
- `scripts/chart.py`：金额分桶图；默认只统计中标金额，0/1–4/≥5 条有效金额的行为见上。
- `scripts/daily_window.py`：输出 Asia/Shanghai 时区的每日窗口。
- `scripts/md_to_pdf.py`：可选 PDF 输出。

## 硬约束

- 金额统一为万元；不明确填 `null`，禁止估算。
- 区分“招标公告”和“中标结果”；招标公告缺中标方和金额是正常的，图表默认不把预算当中标金额。
- 日期必须可验证；无法确认发布日期的记录不进入报告。
- 每条记录保留 `source_url`；每条事实陈述带 `[来源: URL]`，派生统计注明“基于上述已引用记录计算”。
- 只检索、只输出简体中文。
- 缓冲区损坏时先备份，再按 `[]` 重建；不要直接覆盖。

## 定时触发

OpenCode 没有内置调度器。每日推送用系统 cron 包装 CLI，并固定时区：

```cron
# 每天 08:00（Asia/Shanghai），把 <作业目录> 替换成绝对路径
0 8 * * * cd <作业目录> && TZ=Asia/Shanghai opencode run "使用 @esg-bid-monitor 执行每日新增推送；窗口用 scripts/daily_window.py 计算" >> /tmp/esg-bid-daily.log 2>&1
```

历史汇总建议按季度手动触发，或：

```cron
# 每季度首日 09:00（Asia/Shanghai）
0 9 1 1,4,7,10 * cd <作业目录> && TZ=Asia/Shanghai opencode run "使用 @esg-bid-monitor 汇总近两年 ESG 招投标" >> /tmp/esg-bid-history.log 2>&1
```

macOS 可用 launchd 的 `StartCalendarInterval` 实现同样的时间表。

## 失败处理

- 缺少 `DEEPSEEK_API_KEY`：停止检索并提示配置；不要编造标讯。
- 当日无新增：输出 `暂无数据`，缓冲区不变。
- 图表脚本失败：保留 JSON 数据和文字报告，明确说明图表未生成。
- 缓冲区损坏：备份为 `daily_buffer.json.bak`，再重建为空数组。

## 依赖

- Python 3.12，`requests`、`pandas`、`matplotlib`、`reportlab`。
- `DEEPSEEK_API_KEY`。
- 建议模型：Qwen3.8-flash；不可用时使用当前会话模型。
