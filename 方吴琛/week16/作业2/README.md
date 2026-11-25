# 作业2:把 Skill 沉淀为高代码 Script

> 把作业 1 两个 ESG Skill 中"搜索互联网 + 内容总结"的确定性部分沉淀为 Python 脚本,
> 并对比"带确定性 script" vs "无 script 纯指令"的效果。详见 `comparison/report.md`。

## 目录结构
```
作业2/
├── README.md
├── requirements.txt                  # 依赖:ddgs / trafilatura / openai(可选)
├── .venv/                            # 虚拟环境(已建)
├── scripts/
│   ├── common/                       # 公共:配置/搜索/抓取/总结/去重
│   │   ├── config.py                 #   环境变量配置
│   │   ├── search.py                 #   检索(ddgs/tavily)+ 磁盘缓存
│   │   ├── fetcher.py                #   trafilatura 正文抽取
│   │   ├── summarizer.py             #   LLM 总结 + 抽取式降级
│   │   └── dedup.py                  #   去重 + 可信度分级
│   ├── esg_monthly/                  # 案例一:ESG 月报
│   │   ├── queries.py                #   三板块查询模板
│   │   └── pipeline.py               #   月报流水线
│   ├── esg_bidding/                  # 案例二:ESG 投标汇总
│   │   ├── extract.py                #   字段抽取(金额/日期/单位/分类)
│   │   ├── stats.py                  #   分布统计
│   │   └── pipeline.py               #   汇总/监控双模式流水线
│   ├── run.py                        # CLI 入口
│   ├── test_offline.py               # 离线确定性自测(27 项)
│   └── demo_gen.py                   # 端到端 demo(合成数据)
├── comparison/
│   └── report.md                     # 对比报告(核心交付)
└── examples/                         # demo 产出的示例报告
    ├── ESG月报_陕西煤业_2026-10.md
    └── ESG招投标汇总_20261125.md
```

## 快速开始
```bash
cd 作业2
. .venv/bin/activate                  # 或 source .venv/bin/activate
pip install -r requirements.txt       # 已装 ddgs/trafilatura;openai 可选

# 1) 离线自测(无需网络,验证确定性部分)
python scripts/test_offline.py

# 2) 端到端 demo(合成数据,验证完整链路)
python scripts/demo_gen.py

# 3) 真实运行(需可达的搜索后端)
python scripts/run.py monthly --client 陕西煤业 --industry 煤炭 --year-month 2026-10
python scripts/run.py bidding --mode aggregate --max-queries 30
python scripts/run.py bidding --mode monitor
```

## 可选环境变量
| 变量 | 作用 | 默认 |
|---|---|---|
| `ESG_SEARCH_BACKEND` | 搜索后端:`ddgs`/`tavily` | `ddgs` |
| `TAVILY_API_KEY` | Tavily 后端 key(国内推荐,绕开被墙) | — |
| `ESG_LLM_API_KEY` / `ZHIPUAI_API_KEY` | LLM 总结;不设则降级本地抽取式 | — |
| `ESG_LLM_BASE_URL` | LLM 接口(默认智谱 GLM) | `https://open.bigmodel.cn/api/paas/v4` |
| `ESG_LLM_MODEL` | 模型名 | `glm-4-flash` |
| `ESG_CACHE_DIR` | 检索/抓取缓存目录 | `.esg_cache` |

## 设计要点
1. **确定性优先**:金额/日期/分类/统计/去重/可信度全部代码实现,可复算、可审计、零 token。
2. **LLM 受约束**:只把干净正文交给 LLM 做受约束总结(固定 system prompt + 结构化输出),降低幻觉。
3. **降级稳健**:LLM 不可用时自动降级抽取式摘要;检索失败不中断流水线。
4. **全程指标**:查询数/结果数/抓取数/耗时落盘,供对比与审计。
5. **可插拔后端**:搜索/LLM 均可通过环境变量切换。


