---
name: esg-monthly-scripted
description: 作业二ESG月报脚本实验版，程序检索、读取和去重网页，调用模型结构化总结并校验引用，用于与纯指令版对照。
---

# ESG月报脚本实验版

采用references/business-rules.md及references/research.md的esg-research-1.0业务规范。先确认company、month、cutoff，写入任务JSON。queries可指定共同检索词。

使用scripts/research.py分阶段或完整执行。`python scripts/research.py run <任务JSON> <输出目录>`按配置执行Codex原生搜索或Bing公开RSS检索、网页读取、规范化、去重、模型总结、校验与排版。公开检索结果可能稀疏，按返回结果披露覆盖。

固定材料实验执行 `python scripts/research.py summarize <任务JSON> <输出目录> --input <材料JSON>`。模型接口使用本机已登录的Codex CLI，首次使用检查codex login status。脚本按命令级配置选择传输方式与搜索状态，调用日志记录实际结果。

摘要生成后验证source_id、选择状态与材料覆盖。模型判断和搜索结果仍有波动，程序校验通过只证明对应结构约束。失败时保存实际阶段与日志，依照共同规范处理证据缺口。

报告链接和行动建议由Codex复核。用户要求的研究范围超出返回材料时继续定向补搜，保留过程。实验版的测试运行以登记的相同范围与输出要求为准。
