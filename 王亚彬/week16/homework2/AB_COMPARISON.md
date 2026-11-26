# 确定性 Script 对 Skill 效果的影响：A/B 对比

## 实验设计

| 项 | 说明 |
|---|---|
| 控制变量 | 同一模型、同一组任务（两个案例）、同一份 SKILL.md 指令 |
| 唯一变量 | A 组仅 SKILL.md；B 组 SKILL.md + scripts |
| A 组产出 | `results-a/report-monthly.md`、`results-a/report-bid.md` |
| B 组产出 | `results/report-monthly.md`、`results/report-bid.md` |

## 实际差异对比

| 指标 | A 组（无 script） | B 组（有 script） |
|---|---|---|
| 时间窗口 | 未核验，8 月报道混入 11 月月报，仅标注"背景补充" | search.py 先算出 [2026-11-01, 30]，窗口外明确标注 |
| 信息条数 | 月报 6 条 / 投标 5 条 | 月报 8 条 / 投标 10 条 |
| 金额准确性 | "约480万""平均约200万"——估算 | 487.6万、163.4万——stats.py 从明细表确定性计算 |
| 引用完整性 | 月报 6 个链接、2 个日期；validate.py 判定不通过 | 月报 12 个链接、11 个日期；validate.py 判定通过 |
| 统计一致性 | "平均约200万"与明细 5 条数据无法对上 | 分档计数与明细一致，均值来自脚本计算 |
| 灵活性 | 可临场调整搜索方向 | 模板未覆盖的问法需改脚本 |

validate.py 的判定是可复现的硬证据：

```bash
cd homework2
python scripts/validate.py results/report-monthly.md              # 通过
python scripts/validate.py results-a/report-monthly.md # 不通过
```

## 结论

script 只做了三件机械的事——算日期窗口、固定搜索关键词、按明细算统计——就消除了 A 组"算不准 + 说不全"的问题。模型仍负责信息筛选、摘要和判断，未被取代。

分工：**script 保证下限（不出低级错误），skill 保证上限（理解意图、生成有价值的报告）**。

A 组的优势是灵活性：遇到模板未覆盖的问法能临场调整。代价是金额、日期这类确定性数据容易出错，且错误看起来合理、不易察觉。

## 复现方式

```bash
cd homework2
python scripts/search.py --query-only --month 2026-11
python scripts/validate.py results/report-monthly.md
python scripts/stats.py results/bids.json
```
