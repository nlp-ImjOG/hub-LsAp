# 作业二：给 ESG 月报技能沉淀确定性脚本，并做 A/B 对照

承接作业一的 `esg-monthly-report` 技能，把"检索互联网 + 内容归集"里**有唯一正确答案**的部分
沉淀成脚本，然后用同一客户、同一统计期、同一模型跑两遍，量出"有脚本 vs 无脚本"的差别。

**结论速览：引用合格率 73.9% → 100%，引用未闭环 6 → 0，模型自带日期错误率 17.4% 且全部被自动标记；
但期外标注 5:5 打平、数字可溯源 20% → 46.7% 两者都不及格。脚本替代的不是"搜索能力"，
而是"搜索之后的归集与质检"。**

完整分析见 **[`reports/A_B对比实验报告.md`](reports/A_B对比实验报告.md)**。

## 一、这次沉淀了什么

在技能里新增一个单文件 CLI（5 个子命令）与两份数据文件。**改知识只改数据文件，不改代码。**

| 新增 | 作用 |
|---|---|
| `scripts/esg_source_pipeline.py` | `plan` 检索计划 / `search` 结构化源采集 / `fetch` 正文与元数据抽取 / `ledger` 去重分档编号 / `check` 七项门禁 |
| `references/search-matrix.json` | 六方向检索矩阵（检索式写在这里） |
| `references/tier-map.json` | 域名 → 权威度 T1/T2/T3（加信源写在这里） |

确定性的事交给脚本：检索式生成、结构化源采集、日期取证（`jsonld>meta>URL>正文>接口`）、
机构抽取、事件去重、时效分档、权威度分级、编号、闭环校验、数字溯源。
判断的事留给模型：语义检索、相关性、影响评估、行动建议、写作。

## 二、目录结构

```text
作业二/
├── .agents/skills/esg-monthly-report/     # 升级后的技能
│   ├── SKILL.md                           # 新版：写明分工、五步流程、门禁、已知边界
│   ├── scripts/
│   │   ├── esg_source_pipeline.py         # ★ 新增：plan/search/fetch/ledger/check
│   │   └── build_report.py                # 沿用作业一：md → 单文件 HTML
│   ├── references/
│   │   ├── search-matrix.json             # ★ 新增：六方向检索矩阵
│   │   ├── tier-map.json                  # ★ 新增：域名权威度分级
│   │   ├── source-catalog.md              # 沿用
│   │   ├── report-spec.md                 # 沿用
│   │   └── quality-checklist.md           # 沿用
│   └── assets/report.css                  # 沿用
├── reports/
│   ├── A_B对比实验报告.md                  # ★ 核心交付：实验设计与结论
│   ├── A_无script_中国神华_ESG月报_2026-11.md
│   └── B_有script_中国神华_ESG月报_2026-11.md
├── data/
│   ├── profile_shenhua.json               # 客户画像输入
│   ├── plan.json / hits.jsonl / docs.jsonl # 计划 / 候选 / 结构化文档
│   ├── raw_discovery.jsonl                # 模型语义检索到的三方向来源（两臂共用）
│   ├── metrics.json                       # 对比指标原始数据
│   ├── armA_original_skill/SKILL_no_script.md  # 作业一技能原文，便于 diff
│   ├── armA/                              # 无脚本组：手工清单 + 审计台账
│   │   ├── sources_A.md  ingest_A.jsonl  docs_A.jsonl  audit_A.json  ledger_A.md
│   └── armB/                              # 有脚本组：台账 + 事实卡
│       ├── sources_B.json  factcards_B.csv  ledger_B.md
├── ab_metrics.py                          # 指标计算（复用管线口径）
└── README.md
```

## 三、环境

Python 3.12（`py312`），依赖预装无需安装：`requests`、`beautifulsoup4`、`PyPDF2`、`matplotlib`、`pandas`。

```powershell
E:\software_data_center\conda_envs\py312\python.exe --version   # Python 3.12.13
```

## 四、复现命令

```powershell
cd "作业二"
$env:PYTHONIOENCODING = "utf-8"
$py = "E:\software_data_center\conda_envs\py312\python.exe"
$S  = ".agents\skills\esg-monthly-report\scripts\esg_source_pipeline.py"

# 有脚本组：五步流水线
& $py $S plan   --profile data\profile_shenhua.json --since 2026-10-25 --until 2026-11-24 --out data\plan.json
& $py $S search --plan data\plan.json --out data\hits.jsonl
& $py $S fetch  --hits data\hits.jsonl --out data\docs.jsonl
& $py $S fetch  --ingest data\raw_discovery.jsonl --out data\docs_semantic.jsonl
& $py $S ledger --docs data\docs.jsonl data\docs_semantic.jsonl `
      --since 2026-10-25 --until 2026-11-24 `
      --out data\armB\sources_B.json --cards data\armB\factcards_B.csv --md data\armB\ledger_B.md
& $py $S check  --ledger data\armB\sources_B.json --report "reports\B_有script_中国神华_ESG月报_2026-11.md"

# 无脚本组：用同一把尺子审计手工产物
& $py $S fetch  --ingest data\armA\ingest_A.jsonl --out data\armA\docs_A.jsonl
& $py $S ledger --docs data\armA\docs_A.jsonl --since 2026-10-25 --until 2026-11-24 --keep-ids `
      --out data\armA\audit_A.json --md data\armA\ledger_A.md
& $py $S check  --ledger data\armA\audit_A.json --report "reports\A_无script_中国神华_ESG月报_2026-11.md"

# 对比指标
& $py ab_metrics.py
```

一次冷启动约 8 分钟（实测 292 次网络请求）；网络响应落盘缓存在技能目录 `.cache/`，
二次运行零请求、约 4 分钟、台账指纹逐字节一致。

## 五、实验设计要点

- **只改一个变量**：客户、统计期、模型、六方向、质量线全部相同，唯一差别是技能里有没有脚本。
- **输入受控**：国际规则 / 评级 / 行业三方向没有免密结构化入口，两臂共用同一份语义检索结果
  （`data/raw_discovery.jsonl`），差别只在其后的加工方式。
- **判官独立**：两臂产物都由同一个 `check` 门禁与 `ab_metrics.py` 审计，
  无脚本组的清单先转成结构化输入（`ingest_A.jsonl`），再被同一套规则度量，避免"自己判自己"。
- **容错的真实性**：无脚本组的日期、权威度、重复问题都是模型真实犯的错误，未经人为放大。

## 六、已知局限

1. **表格型 PDF 的数字抽不出来**：月度运营数据公告、季报主要指标表抽出文本后"数字—单位"关系被破坏，
   脚本的 `numbers` 字段为空。"数字可溯源"门禁因此对这类条目系统性误报，只能当抽查清单用。
2. **免密通用检索不可用**：必应 RSS 对中文政策查询返回百科与首页，且 `pubDate` 是抓取时间而非发布时间。
   国际规则 / 评级 / 行业三方向仍需模型语义检索，脚本只做归一化。
3. **台账是候选池不是必引清单**：89 条入账里有"乐东气田批复""铁路科技创新规划"等关键词命中但与本客户
   无关的条目，相关性判断仍归模型。
4. **`sources_B.json` 含正文，约 4 MB**：`check` 的数字溯源需要正文，故未剥离。
5. **单一客户、单一统计期**：只有一次实验，不能替代多期回归；但脚本的可复现性使多期回归成为可能
   ——这正是本次沉淀的目的。