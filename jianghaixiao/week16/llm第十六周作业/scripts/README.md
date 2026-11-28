# Scripts 说明

本目录用于演示从研究 Skill 中沉淀出的确定性脚本。按作业要求，未实际运行和验证。

- `collect_sources.py`：规范化 URL、生成 source_id、去除重复来源。
- `build_evidence_ledger.py`：把“主张—来源—引文”整理成 JSONL 证据账本。
- `validate_report.py`：检查引用编号、关键章节和报告长度。

建议的实际流水线：

```text
search results
→ collect_sources.py
→ 人工/模型筛选
→ fetch / extract（可另写脚本）
→ build_evidence_ledger.py
→ 模型综合写作
→ validate_report.py
```