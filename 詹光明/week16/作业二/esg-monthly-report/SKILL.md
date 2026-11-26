---
name: esg-monthly-report
description: 当需要用一个可复现、可审计的脚本流水线生成 ESG 月报，或需要在无 API Key 时输出离线样例、在有 Key 时跑真实检索时使用。适用于批量生成客户月报、把手工检索升级为脚本流程、以及需要来源 JSON 与运行记录的场景。
version: "1.0.0"
license: MIT
metadata:
  hermes:
    tags: [esg, report, script]
---

# ESG 月报（脚本版）

## 概述

本技能是作业一 `esg-monthly-report` 的**带脚本实现**。核心原则：**脚本负责检索、筛选、抽取、组装和校验；Claude 负责运行、检查结果、处理失败；不编造数据。**

两种模式：

- **离线模式**：`--offline`，使用 `scripts/fixtures/` 固定数据，不需要 API Key，用于演示结构和无网环境。
- **真实模式**：博查 Web Search + OpenAI 兼容 LLM，需要 `BOCHA_API_KEY` 和 `LLM_API_KEY`。

## 何时使用

**使用：**
- 客户要求每月一份 ESG 月报，且需要可复现、可追溯的生成过程
- 需要批量生成不同客户/月份的报告
- 需要来源 JSON、运行记录、质量警告，便于复核
- 没有 API Key，但想先看报告结构和样例

**不适用：**
- 正式 ESG/可持续报告编制、审计级数据核验
- 需要付费数据库才能保证全量的统计
- 需要自动发邮件/企微/钉钉（本技能只生成文件）

## 快速开始

在 skill 根目录执行：

```bash
# 1. 安装依赖
pip install -r scripts/requirements.txt

# 2. 离线样例（不需要 Key）
python scripts/run.py --offline --client 中国神华 --industry 煤炭 --month 2026-10

# 3. 只看检索词
python scripts/run.py --dry-run --client 中国神华 --industry 煤炭 --month 2026-10

# 4. 真实模式：先把 scripts/.env.example 复制为 scripts/.env，填好 Key
python scripts/run.py --client 中国神华 --industry 煤炭 --month 2026-10
```

`--month` 省略时默认上一个自然月。其他参数：

- `--no-fetch`：不抓正文，直接用搜索摘要
- `--max-sources 12`：限制分析来源数
- `--env-file path/to/.env`：指定配置文件
- `--verbose`：打印调试日志

## 输出

- `reports/ESG月报_{客户}_{YYYY-MM}.md`
- `reports/ESG月报_{客户}_{YYYY-MM}_sources.json`（来源明细）
- `reports/ESG月报_{客户}_{YYYY-MM}_run.json`（查询、计数、警告）

## 脚本结构

- `scripts/run.py`：CLI 入口
- `scripts/esg_report/`：检索、去重、抓取、LLM 抽取、模板、质量门禁
- `scripts/fixtures/`：离线样例数据（18 条来源 / 18 条条目）
- `references/examples/`：一份离线样例报告，用于快速了解输出结构

## Claude 执行规则

1. **先确认输入**：客户、行业、报告期；用户没说就用默认值（中国神华 / 煤炭 / 上一个自然月），并在回复中写明。
2. **先 dry-run**：真实模式前先跑 `--dry-run`，检查检索词是否覆盖政策、行业、公司、对标四类。
3. **无 Key 用 offline**：不要伪造 `BOCHA_API_KEY` 或 `LLM_API_KEY`；没有 Key 时直接跑 `--offline`。
4. **运行后必须检查**：
   - `run.json` 的 `warnings`
   - 报告附录 B 的“信息缺口 / 质量提示”
   - 来源链接、日期、金额/评级是否可追溯
   - 一页纸速览是否 ≤300 字
5. **不要把离线样例当真实检索**：离线报告会标注“离线样例（固定 fixture）”；向用户汇报时必须说明。
6. **失败处理**：
   - `ConfigError`：提示配置 `.env`，不要继续假装生成。
   - 没有来源：放宽 `--max-sources`、调整 `--month`，或先 `--offline` 验证结构。
   - LLM 抽取失败：查看 `--verbose` 日志；可 `--no-fetch` 或减少来源；不要改 prompt 去绕过“不得编造”。
   - 抓取失败：脚本会自动降级到搜索摘要，并在附录 B 标注。
7. **不要提交** `scripts/.env`；`reports/` 是运行时输出，按需清理。
8. **改报告结构**：编辑 `scripts/esg_report/writer.py` 的模板；改抽取规则：编辑 `scripts/esg_report/llm.py` 的 prompt；改检索词：编辑 `scripts/esg_report/queries.py`。

## 质量门禁

脚本自动检查：

**硬错误**
- 报告没有条目
- 条目没有来源，或引用了不存在的来源编号
- 缺少必需章节（一页纸速览、三大板块、来源清单）

**警告**
- 速览超过 300 字
- 来源日期不在报告期内或未核实
- 来源未抓到正文、仅用搜索摘要
- 政策/行业/公司/对标某一板块没有条目
- 条目的“事实/影响/建议”不完整

Claude 还要人工核对：来源链接可打开、日期在窗口内、评级带机构/日期/是否本月变动、集团与上市公司未混淆。

## 示例

用户：“用脚本给中国神华做 2026 年 10 月 ESG 月报，先看结构。”

```bash
python scripts/run.py --offline --client 中国神华 --industry 煤炭 --month 2026-10
```

然后读取 `reports/ESG月报_中国神华_2026-10.md`（或直接看 `references/examples/ESG月报_中国神华_2026-10.md`），汇报：

- 来源数 / 条目数 / 警告数
- 三大板块的核心结论
- 哪些来源是窗口外或报告期后数据
- 需要客户人工确认的缺口
