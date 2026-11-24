# ESG 月报 Skill（homework1 · part1 · 案例一）

汇总过去一个月的时政信息，为客户生成 ESG 月报的 Claude Code Skill。以中国神华为默认示例客户。

## 目录结构

```
part1/
├── .claude/skills/esg-monthly-report/   # ESG 月报 Skill（项目级，Claude Code 自动发现）
│   ├── SKILL.md                         # 主指令：frontmatter + 三阶段工作流
│   └── references/
│       ├── search-playbook.md           # 检索词库、来源分级、直访站点、筛选规则
│       ├── report-template.md           # 报告固定模板、写作要求、质量自查清单
│       └── benchmark-companies.md       # 煤炭行业对标企业清单与检索靶点
├── reports/                             # 产出目录（月报正文与检索笔记）
├── tests/test_skill_demo.py             # 测试 demo（结构校验 + 产物质检）
├── README.md                            # 本文件
├── ESG月报SKILL实施报告.md               # 需求分析、设计、实施步骤与验收标准
└── require.txt                          # 作业原始需求
```

## 使用方法

在 `part1` 目录下启动 Claude Code，然后：

```
/esg-monthly-report                       # 默认：中国神华，近一个月
/esg-monthly-report 比亚迪                 # 指定客户
/esg-monthly-report 中国神华 2026年10月     # 指定客户与报告期
```

或直接用自然语言触发：「帮我生成中国神华的 ESG 月报」「把这个月的 ESG 相关动态整理成月报」。

## Skill 工作流程

```
Phase 0 输入解析（客户/行业/报告期，默认中国神华·近一个月）
   ↓
Phase 1 自主信息采集（A 政策线 / B 行业线 / C 公司线，三线并行联网检索）
   ↓
Phase 2 自主筛选（时间窗 → 来源分级 → 去重 → 相关性，每线保留 ≥5 条）
   ↓
Phase 3 报告生成（按固定模板成文 + 质量自查清单 → 落盘 reports/）
```

设计细节、验收标准与风险应对见《ESG月报SKILL实施报告.md》。

## 输出

| 产物 | 路径 | 说明 |
|---|---|---|
| 月报正文 | `reports/<客户>_ESG月报_<YYYY-MM>.md` | 含摘要、要点速览、三大必需部分、对标对比表、来源清单与免责声明 |
| 检索笔记 | `reports/notes-<客户>_<YYYY-MM>.md` | 全部检索发现与筛选标记，过程可追溯 |

## 测试

```bash
# 自动化校验：Skill 结构 + 报告产物质检（26 项检查）
python3 tests/test_skill_demo.py
```

触发测试：在 `part1` 目录新开 Claude Code 会话，输入 `/esg-monthly-report` 或自然语言「帮我生成中国神华的 ESG 月报」，观察 skill 被唤起并按三阶段流程执行。

> 说明：本 Skill 产出的报告由 AI 基于公开网络信息编制，供参考，不构成投资或合规建议。
