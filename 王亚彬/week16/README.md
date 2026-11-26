# 第16周作业：构建 ESG Skill + Script 效果对比

## 作业1（`homework1/`）：两个 Skill

| Skill | 目录 | 说明 |
|---|---|---|
| ESG 月报生成器 | `homework1/esg-monthly-report/` | 输入公司+月份，三路搜索生成月报，以中国神华为案例 |
| ESG 投标信息汇总 | `homework1/esg-bid-monitor/` | 模式A：近2年中标汇总分析；模式B：每日新招标监控 |

每个 Skill 的 `SKILL.md` 包含：触发条件、搜索关键词模板、筛选规则、输出格式、硬性约束、自检清单。

`homework1/reports/` 是两个案例的最终报告（效果好）。A 组对比样本在 `homework2/results-a/`。

## 作业2（`homework2/`）：Script 沉淀与 A/B 对比

### 沉淀的 script

| 文件 | 作用 |
|---|---|
| `homework2/scripts/search.py` | 确定性生成时间窗口 + 8 组固定搜索词 |
| `homework2/scripts/validate.py` | 校验报告三块齐全、每条有链接和日期 |
| `homework2/scripts/stats.py` | 确定性计算金额分档、类型分布、均值 |

### A/B 分组

- **A 组**（`homework2/results-a/`）：仅 SKILL.md，模型自主搜索、判断、统计
- **B 组**（`homework2/results/`）：SKILL.md + scripts，机械步骤走代码

对比结论见 `homework2/AB_COMPARISON.md`。

## 快速复现

```bash
cd homework2
python scripts/search.py --query-only --month 2026-11
python scripts/validate.py results/report-monthly.md
python scripts/stats.py results/bids.json
```

## 数据来源

所有报告内容来自 2026-11-26 的真实互联网搜索，来源包括：中国证监会相关报道（21世纪经济报道、中国证券报）、财政部（中新网）、安永白皮书（中新经纬）、人民日报/中国能源报、中国神华官网、中国证券网、中国政府采购网、各级公共资源交易中心、企业采购平台。每条结论附原文链接。

## 目录结构

```
week16/
├── README.md
├── homework1/
│   ├── esg-monthly-report/SKILL.md
│   ├── esg-bid-monitor/SKILL.md
│   └── reports/{report-monthly.md, report-bid.md}     ← 最终报告
└── homework2/
    ├── AB_COMPARISON.md
    ├── scripts/{search.py, validate.py, stats.py}
    ├── results-a/{report-monthly.md, report-bid.md}   ← A 组（无 script）
    └── results/{report-monthly.md, report-bid.md, bids.json}  ← B 组（有 script）
```
