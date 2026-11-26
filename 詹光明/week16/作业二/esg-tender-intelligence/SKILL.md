---
name: esg-tender-intelligence
description: 当需要用一个可复现、可审计的脚本流水线汇总 ESG/可持续发展/双碳相关中标信息、分析招标热点与中标金额分布，或每天监控新招标并更新 Markdown 台账时使用。适用于投标团队、ESG 采购部门和招投标情报岗位；支持无 API Key 的离线样例与真实检索两种模式。
version: "1.0.0"
license: MIT
metadata:
  hermes:
    tags: [esg, tender, monitoring, script]
---

# ESG 投标情报（脚本版）

## 概述

本技能是作业一 `esg-tender-intelligence` 的**带脚本实现**。核心原则：**脚本负责检索、去重、金额解析、分类、统计、台账和 Markdown 生成；Claude 负责运行、检查、处理失败；不编造金额/日期/中标方。**

两种模式：

- **复盘模式**：`review`，汇总近 N 年 ESG/双碳中标样本，输出金额分布、类别结构、热点与竞争分析。
- **日报模式**：`daily`，监控最近 N 天新招标/采购/候选人，按 P0/P1/P2 分级，更新 Markdown 台账。
- **离线模式**：加 `--offline`，使用 `scripts/fixtures/` 固定数据，不需要 API Key。
- **真实模式**：博查 Web Search + OpenAI 兼容 LLM，需要 `BOCHA_API_KEY` 和 `LLM_API_KEY`。

## 快速开始

在 skill 根目录执行：

```bash
pip install -r scripts/requirements.txt

# 1. 近两年复盘（离线）
python scripts/run.py review --offline --start 2024-12 --end 2026-11

# 2. 每日监控（离线，首次回看 14 天）
python scripts/run.py daily --offline --date 2026-11-26 --days 14

# 3. 只看检索词
python scripts/run.py review --dry-run --start 2024-12 --end 2026-11
python scripts/run.py daily --dry-run --date 2026-11-26 --days 14

# 4. 真实模式：先把 scripts/.env.example 复制为 scripts/.env，填好 Key
python scripts/run.py review --start 2024-12 --end 2026-11
python scripts/run.py daily --date 2026-11-26 --days 7
```

常用参数：

- `--out reports`：输出目录
- `--ledger reports/ESG招标跟踪台账.md`：日报台账路径
- `--max-sources 15`：限制分析来源数
- `--no-fetch`：不抓正文，直接用搜索摘要
- `--env-file path/to/.env`：指定配置

## 输出

**复盘：**
- `reports/ESG投标市场复盘_{start}至{end}.md`
- `..._sources.json`
- `..._run.json`

**日报：**
- `reports/ESG招标日报_{YYYY-MM-DD}.md`
- `reports/ESG招标跟踪台账.md`（增量更新，不删除历史）
- `..._run.json`

## 脚本结构

- `scripts/run.py`：CLI（review / daily）
- `scripts/tender/`：检索、金额解析、分类、去重、统计、LLM 抽取、模板、台账、质量门禁
- `scripts/fixtures/`：离线样例（51 条复盘项目、9 条日报项目、台账种子）
- `references/examples/`：一份复盘、一份日报和一份台账样例，用于快速了解输出结构

## Claude 执行规则

1. **确认模式与窗口**：复盘问清 `--start/--end`；日报问清 `--date/--days`。用户没说就用默认值，并在回复中写明。
2. **先 dry-run**：真实模式前先看检索词是否覆盖 ESG 报告/咨询、碳核算/碳足迹、零碳园区、碳管理平台四类。
3. **无 Key 用 offline**：不要伪造 `BOCHA_API_KEY` 或 `LLM_API_KEY`。
4. **运行后必须检查**：
   - `run.json` 的 `warnings`
   - 日报的“信息缺口”和台账
   - 金额类型：预算 / 最高限价 / 中标 / 候选人不能混用
   - 候选人不能写成中标人
   - 截止日期不能早于公告日期
   - 多平台重复公告是否已按“项目名称 + 采购人”去重
5. **不要把离线样例当真实检索**：离线报告会标注“离线样例（固定 fixture）”；汇报时必须说明。
6. **失败处理**：
   - `ConfigError`：提示配置 `.env`，不要继续假装生成。
   - 没有项目：放宽日期窗口、调整关键词，或先 `--offline` 验证结构。
   - 抓取失败：脚本自动降级搜索摘要，附录会标注。
   - LLM 抽取失败：查看 `--verbose` 日志；可 `--no-fetch`、减少来源，或 `--offline`。
   - 台账重复：先看 `reports/ESG招标跟踪台账.md`，按“项目名称 + 采购人”核对。
7. **不要提交** `scripts/.env`；`reports/` 是运行时输出，按需清理。
8. **改逻辑**：检索词改 `scripts/tender/queries.py`；分类/金额/优先级改 `scripts/tender/filter.py`；LLM prompt 改 `scripts/tender/llm.py`；报告模板改 `scripts/tender/writer.py`。

## 质量门禁

脚本自动检查：

**复盘**
- 没有项目、统计样本为空
- 项目缺少名称或来源
- 缺少必需章节（速览、样本方法、市场总览、热点、策略、样本明细）

**日报**
- 项目缺少名称或来源
- 候选人的金额类型写成“中标/成交”
- 截止日早于公告日
- 未披露截止日期
- 缺少必需章节（推送摘要、今日必看、新增招标、中标/候选人、截止提醒、台账更新）

Claude 还要人工核对：金额单位是否为万元、预算/中标是否分列、中标方是否为联合体、项目是否重复、台账是否已更新。

## 示例

用户：“跑一份 2024-12 到 2026-11 的 ESG 投标复盘，先看离线样例。”

```bash
python scripts/run.py review --offline --start 2024-12 --end 2026-11
```

然后读取 `reports/ESG投标市场复盘_2024-12至2026-11.md`（或直接看 `references/examples/` 下的样例），汇报：

- 样本量、金额中位数/均值
- 数量与金额倒挂的类别
- 前 3 个热点赛道
- 需要客户人工确认的缺口
