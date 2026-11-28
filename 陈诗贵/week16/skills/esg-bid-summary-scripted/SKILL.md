---
name: esg-bid-summary-scripted
description: 带确定性脚本的 ESG 投标信息汇总技能。当用户需要汇总过去两年 ESG、可持续发展、双碳相关的中标情况，分析热点招标方向与中标金额分布，或每天监控推送新的 ESG 招标信息时报此技能。脚本负责联网搜索、金额单位换算、去重、窗口过滤与统计，DeepSeek 负责从招标公告素材中抽取字段；与纯提示词版 esg-bid-summary 配合用于效果对比。
---

# ESG 投标信息汇总技能（确定性脚本版）

将招投标情报工作拆成两层：

- **确定性层（Python 脚本）**：联网搜索、正文抓取、金额"万/亿→元"换算、日期解析、去重、24 个月窗口过滤、方向/区间/地区/采购人统计、日报渲染。
- **智能层（DeepSeek LLM）**：从公告素材中抽取 `title/buyer/winner/amount_raw/industry/region` 等字段，并给出证据句。禁止编造项目、金额与中标单位。

## 一、环境准备

```powershell
pip install -r .claude/skills/esg-bid-summary-scripted/requirements.txt
```

变量：`DS_API_KEY`（必需）、`LLM_BASE_URL`、`LLM_MODEL`。脚本自动向上查找仓库根目录 `.env`。

## 二、执行流程（在项目根目录 `week16` 下运行）

```powershell
# 1) 搜索 + 抽取（过去 24 个月 + 当日新增都用这一份原始数据）
python .claude/skills/esg-bid-summary-scripted/scripts/collect_bids.py --months 24

# 2) 历史汇总分析（确定性统计 + 报告）
python .claude/skills/esg-bid-summary-scripted/scripts/analyze_bids.py

# 3) 当日招标推送（不传 --date 时取数据中的最新日期）
python .claude/skills/esg-bid-summary-scripted/scripts/render_daily.py
```

常用参数：

- `--as-of YYYY-MM-DD`：统计截止日（复现实验时固定）
- `--months 24`：历史窗口长度
- `--date YYYY-MM-DD`：日报日期
- `--out-dir`：默认 `output/`

产物：

- `output/bids_raw.json`：抽取 + 证据校验后的原始记录（含 `rejected` 与告警）
- `output/bids_analysis.json`：确定性统计结果
- `output/ESG投标汇总_<as_of>.md`：历史汇总报告
- `output/ESG招标日报_<date>.md`：每日推送

## 三、脚本与职责边界

| 脚本 | 确定性职责 | DeepSeek 职责 |
|---|---|---|
| `scripts/collect_bids.py` | 生成检索词、搜索、抓正文、调用抽取、**校验金额/日期是否真实出现在原文**、URL/标题去重 | 抽取结构化字段 + `evidence` 证据句 |
| `scripts/analyze_bids.py` | 金额换算（亿元/万元/元/逗号/全角）、24 个月窗口、去重、方向与金额区间统计、中位数、Top 采购人、季度趋势 | 无 |
| `scripts/render_daily.py` | 按日期过滤、关注度规则（金额阈值 + 关键词）、排序、无新增时的明确提示 | 无 |

## 四、证据校验规则（脚本强制执行）

1. **金额**：`amount_raw` 必须逐字出现在标题/摘要/正文中（忽略全半角与空格差异），否则置 `null` 并记入 `warnings`。
2. **日期**：`publish_date` 的常见中文写法（`YYYY年M月D日` 等）必须能在素材中找到，否则标记 `date_unverified=true`。
3. **金额换算**：由脚本完成，不交给 LLM。`1.2亿元→120000000`，`3500万元→35000000`，`980万→9800000`，`2,460,000元→2460000`；无单位数字按元处理并标记 `unit_missing`。
4. **去重**：(公告日期, 项目名称, 采购人) 相同视为重复；同项目多次公告保留最终结果。
5. **窗口**：`as_of` 往前 24 个月（按自然月计算），窗口外记录单独存放，不参与统计。
6. **未披露金额**：计入项目数，不参与总额/均值/中位数计算，报告附录注明。

## 五、输出结构

历史汇总报告固定章节：

1. 总体概览（项目总数、披露金额数、累计/平均/中位数）
2. 热点招标方向（排名 + 季度趋势，季度趋势为确定性分组）
3. 中标金额分布（五个区间 + 大额 Top 5）
4. 地区与采购人分布（Top 5）
5. 结论与建议（脚本生成数据事实，LLM 可选补充解读）
6. 附录：数据口径与校验告警

日报固定格式：表格 + "重点关注"；当日无新增时输出"当日无新增相关招标"。

## 六、失败与降级

| 情况 | 处理 |
|---|---|
| 搜索/网络失败 | 双引擎降级后仍失败则报错退出，不生成假数据 |
| 抽取字段缺失 | 保留记录，字段置 null，记入告警 |
| 金额/日期未通过校验 | 置空或标记 `unverified`，在报告附录列出 |
| 有金额记录为 0 | 统计输出"无可比金额数据"，不用估算值填充 |

## 七、与纯提示词版的对比实验

同一问题分别调用 `esg-bid-summary`（纯提示词）与 `esg-bid-summary-scripted`，固定 `--as-of`，对比：金额换算正确率、区间统计一致性、重复记录数、窗口错误数、可复现性（重复运行结果是否一致）、耗时、Token 消耗。结论记录到 `week16/对比.md`。
