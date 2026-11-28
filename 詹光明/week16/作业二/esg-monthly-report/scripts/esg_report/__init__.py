"""ESG 月报脚本化流水线。

把作业一的 `esg-monthly-report` skill 拆成可执行步骤：
检索 → 去重/筛选 → 抓取 → LLM 抽取 → 组装 → 质量校验 → 落盘。
"""

__version__ = "0.1.0"
