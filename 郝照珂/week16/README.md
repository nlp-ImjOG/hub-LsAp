# Week 16 作业｜用两个 Skill 分析同一份年报

[阅读作业报告（PDF）](Week16作业报告.pdf) · [查看有脚本与无脚本的实测对照](实验/对比报告.md)

课程讲义 `week16/week16.pdf` 第 4 页在作业前列出销售数据分析和财务报表分析，第 5 页要求比较确定性脚本的作用。本作业选用 Apple Inc. FY2025 与 FY2024 两个完整财年。用同一套公开披露分别回答两个经营问题，便于检查两份报告中的收入总额能否对上。

| 案例 | 正式技能 | 完整报告 | 无脚本对照 |
| --- | --- | --- | --- |
| 销售增长来自哪些产品和地区？ | [销售技能](.agents/skills/sales-evidence-report/SKILL.md) | [销售分析](报告/销售分析.md) | [无脚本成品](实验/无脚本输出/销售分析.md) |
| 利润增长有没有变成现金？ | [财务技能](.agents/skills/financial-evidence-report/SKILL.md) | [财务分析](报告/财务分析.md) | [无脚本成品](实验/无脚本输出/财务分析.md) |

## 运行技能

以本作业目录为工作目录，使用具备联网检索能力的技能客户端。正式版放在项目级 `.agents/skills/` 中。支持显式技能调用的客户端可以直接使用以下提示。也可以向客户端提供相应 SKILL.md 的路径。

- `$sales-evidence-report 分析 Apple FY2025 相比 FY2024 的销售增长，解释产品和地区的贡献，列出证据。`
- `$financial-evidence-report 分析 Apple FY2025 相比 FY2024 的盈利质量、流动性与资本分配，用年报和三表核实。`

仅测试无脚本流程时，在独立会话中加载[无脚本销售技能](实验/无脚本技能/sales-evidence-report/SKILL.md)或[无脚本财务技能](实验/无脚本技能/financial-evidence-report/SKILL.md)，使用[共同题面](实验/题面.md)。这两个目录各自只有一个 SKILL.md。

## 从终端复现数字

以下命令在本作业目录中执行。使用 Python 3.9+；销售脚本还需 Poppler 或兼容版本的 `pdftotext` 在 PATH 中。在线检索不需要 API 密钥；访问 SEC 时可通过 `SEC_USER_AGENT` 指定自己的应用名称和联系方式。

```powershell
python .agents/skills/sales-evidence-report/scripts/sales.py --year 2025 --out 复算/sales-live.json
python .agents/skills/financial-evidence-report/scripts/financial.py --cik 320193 --year 2025 --out 复算/financial-live.json
```

离线复核使用已提交的证据快照。这两条命令只需要 Python。程序重新计算指标和恒等式，遇到不相符的合计会返回错误。

```powershell
python .agents/skills/sales-evidence-report/scripts/sales.py --replay 证据/sales.json --out 复算/sales.json --markdown 复算/销售底表.md
python .agents/skills/financial-evidence-report/scripts/financial.py --replay 证据/financial.json --out 复算/financial.json
```

销售脚本适配 Apple 年末新闻稿所附、含四栏金额的销售表。财务脚本适配 EDGAR 近期 10-K 中以美元报告、具有所需 US GAAP 标签和可比年度的公司；`--year` 指财年结束日所在公历年。更换企业时，技能会重新检索相应的年报和表格。报表格式不同或脚本遇到缺项时，技能保留网页核查路径。

## 证据与实验材料

- [销售取数与贡献分解](证据/sales.json)记录检索入口、公告和 PDF 链接、文件指纹、年度底数与计算值。[财务取数与复算](证据/financial.json)记录申报编号、标签、期间、美元原值与指标。
- [有脚本组检索记录](证据/检索记录.md)和[无脚本组检索记录](实验/无脚本输出/检索记录.md)记录实际查阅的资料及取舍。
- [核对口径](实验/核对口径.md)列出预先确定的 90 个数值和八项定性检查。[对比报告](实验/对比报告.md)给出观测结果及适用范围。
