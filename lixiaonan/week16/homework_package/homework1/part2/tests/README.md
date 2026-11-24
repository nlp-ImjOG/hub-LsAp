# esg-bid-monitor Skill 测试方法

四层测试体系。L1~L3 与 L4 的分流/模板部分由 `tests/test_skill_demo.py` 自动执行（离线，不联网）；真正的在线触发与端到端验收为人工步骤。

| 层 | 名称 | 方式 | 覆盖内容 | 对应验收项（实施文档第八章） |
|---|---|---|---|---|
| L1 | 结构测试 | 自动（demo A 部分） | frontmatter、行数上限、5 个 references 齐全且被声明读取时机、stats.py 可编译、data 工作区就位 | Skill 结构规范 |
| L2 | 规则可实现性测试 | 自动（demo B 部分） | 把 extraction-rules.md 的项目名归一化/去重指纹/金额规范化/口径优先级实现为代码，验证规则**可实现**且与文档表格**逐条一致** | 数据可溯性、抽取一致性 |
| L3 | 管线端到端测试 | 自动（demo C 部分） | mock 标讯数据跑 stats.py，断言分桶/缺失率/集中趋势/TopN/月度趋势/时间窗过滤/坏行处理；模拟 monitor 增量窗口与 state 更新 | 监控有效性（去重与窗口） |
| L4 | 触发分流与产出测试 | 自动（demo D/E 部分）+ 人工在线 | 按 SKILL.md Phase 0 规则模拟 report/monitor 分流；按 report-template 生成 demo 报告骨架并校验结构；在线实测见下 | 触发正确性、自主性闭环、报告完整性 |

运行：

```bash
python3 tests/test_skill_demo.py
```

demo 产物写入 `tests/demo_output/`（mock 数据全部带 TEST 标注与 demo.example.com 域名），**不污染 `data/` 真实工作区**。

## L4 在线触发测试（新会话人工执行）

在 part2 目录开新会话，逐条输入并观察是否触发 esg-bid-monitor 及模式分流：

| 输入 | 预期 |
|---|---|
| 汇总过去2年ESG、双碳相关的中标情况，分析热点招标情况及中标金额分布 | 触发，report 模式 |
| 分析近两年光伏与储能领域的招投标市场 | 触发，report 模式 |
| 监控新的跟ESG相关的招标情况，每天推送新的招标信息 | 触发，monitor 模式 |
| 生成今天的ESG标讯速递 | 触发，monitor 模式 |
| 看看最近有什么值得跟的投标商机 | 触发，monitor 模式 |
| 帮我写一份ESG月报大纲 | **不应**触发本 skill（属 part1 esg-monthly-report 场景） |

## L4 在线端到端小范围实跑建议

全量 2 年回溯检索耗时较长，验收建议**先小后大**：

1. **report 小范围**：时间窗缩到近 1 个月跑一遍，验证 Phase 0→3 全流程、检索笔记落盘 `data/notes/`、质量自查清单逐项通过、报告统计数字与 stats.py 输出一致；
2. **monitor 去重验证**：同日连续跑两次，第二次速递不应出现已推送条目（指纹去重生效），`state.json` 的 `last_run`/`daily_log` 正确更新；
3. **跨日窗口验证**：手工把 `state.json` 的 `last_run` 改为 3 天前再跑 monitor，监测窗口应自动回补到 3 天前（该窗口逻辑已在 demo C10~C12 用模拟验证）；
4. 最后按实施文档第八章验收表逐项勾选，再发起全量 2 年回溯正式运行。
