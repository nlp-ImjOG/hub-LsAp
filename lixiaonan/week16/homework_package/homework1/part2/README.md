# ESG 投标信息汇总 SKILL（esg-bid-monitor）

第 16 周 homework1 / part2 · 案例二实现：**ESG/可持续发展/双碳领域招投标信息回溯分析 + 每日监控推送**。

- 实施依据：`ESG投标信息汇总SKILL实施文档.md`（需求分析 / 架构 / 验收标准）
- 技术形态：Claude Code Skill，零外部依赖（原生 WebSearch/WebFetch + Python 标准库）

## 目录导览

```
part2/
├── ESG投标信息汇总SKILL实施文档.md     # 实施蓝本（需求分析、设计、验收标准）
├── README.md                          # 本文件
├── .claude/skills/esg-bid-monitor/    # Skill 包
│   ├── SKILL.md                       # 主指令：双模式三阶段工作流
│   ├── references/
│   │   ├── search-playbook.md         # 数据源分级、10 条检索主线扇出策略
│   │   ├── keywords.md                # ESG 五大主题关键词库 + 相关性判定规则
│   │   ├── extraction-rules.md        # 18 字段模型、金额规范化表、去重指纹规则
│   │   ├── analysis-guide.md          # 统计口径、金额分桶、Mermaid 图表规范
│   │   └── report-template.md         # 回溯报告模板 + 每日速递模板 + 自查清单
│   └── scripts/
│       └── stats.py                   # 统计脚本（纯标准库）：bids.jsonl → 各维度统计 JSON
├── tests/
│   ├── README.md                      # 测试方法（四层测试体系 + 在线验收步骤）
│   ├── test_skill_demo.py             # 测试 demo（离线自动化，60 项检查）
│   └── demo_output/                   # demo 产物（mock 数据，不污染 data/）
└── data/                              # 工作区（跨运行累积）
    ├── bids.jsonl                     # 结构化标讯库（每行一条 18 字段 JSON 记录）
    ├── state.json                     # 运行状态（last_run / seen_count / daily_log / webhook）
    ├── notes/                         # 检索笔记（每批次关键词与命中数）
    ├── reports/                       # 回溯模式产出的市场回顾报告
    └── daily/                         # monitor 模式产出的每日标讯速递
```

## 使用方式

### 模式一：回溯汇总（report，默认）

在 part2 目录下的 Claude Code 会话中，用自然语言触发即可：

- 「汇总过去 2 年 ESG、双碳相关的中标情况，分析热点招标与中标金额分布」
- 「分析近两年双碳领域招投标市场」
- 「esg-bid-monitor report 2024-11 ~ 2026-11 只看广东」

产出：`data/reports/ESG招投标市场回顾_<起>_<止>.md`，含主题热点、金额分桶、地域分布、月度趋势、中标企业 Top10 与投标建议；结构化记录沉淀在 `data/bids.jsonl`。

### 模式二：每日监控（monitor）

- 「监控新的 ESG 相关招标，帮我推送今天的标讯」
- 「生成今天的 ESG 标讯速递」
- 「esg-bid-monitor monitor」

产出：`data/daily/ESG标讯速递_<日期>.md`（重点推荐 + 新招标一览 + 中标动态 + 截止提醒），并把要点摘要报告给用户。增量窗口自动取 `max(近24h, 自上次运行以来)`，按指纹去重，同日重跑不重复推送。

### 统计脚本手动运行（不进会话也可用）

```bash
# 全库统计
python .claude/skills/esg-bid-monitor/scripts/stats.py data/bids.jsonl

# 指定时间窗（闭区间）并落盘
python .claude/skills/esg-bid-monitor/scripts/stats.py data/bids.jsonl \
  --start-date 2024-11-24 --end-date 2026-11-24 --out data/reports/stats.json
```

## 定时部署（每日推送无人值守）

**生产环境**：crontab + Claude Code 无头模式（每天 08:43）：

```cron
43 8 * * * cd /path/to/part2 && claude -p "使用 esg-bid-monitor 技能执行每日监控模式" --allowedTools "WebSearch WebFetch Read Write Bash" >> data/daily/cron.log 2>&1
```

**会话内演示**：让 Claude 用 CronCreate 建一个每日定时任务（注意：会话级任务随会话结束失效、7 天自动过期，长期运行请用 crontab/launchd）。

**推送增强**（可选）：在 `data/state.json` 的 `webhook` 字段填入飞书/钉钉/企业微信机器人地址，monitor 模式落盘后会将速递推送到该渠道。

## 测试

```bash
python3 tests/test_skill_demo.py
```

四层测试体系详见 `tests/README.md`：L1 结构测试、L2 规则可实现性测试、L3 管线端到端测试（均离线自动化）；L4 触发分流测试与在线端到端验收（含新会话触发词表与"先小后大"实跑步骤）。

## 数据口径与诚实声明

公开互联网无法穷尽全部历史公告。本 Skill 的统计结论一律基于**公开可检索样本**：报告头部与附录强制声明总样本量、来源构成、金额可解析率与覆盖局限——宁要可核验的部分真实，不要看似全量的虚构。

## 验收对照

验收标准见实施文档第八章：Skill 结构规范、双模式触发分流、自主性闭环、报告完整性、数据可溯性、监控去重有效性、定时可行性。
