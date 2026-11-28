# ESG 技能作业：ESG 月报 + ESG 招投标情报

两个可直接使用的 Pi 技能（Agent Skills 规范），附完整运行产物。

## 一、目录结构

```text
作业一/
├── .agents/skills/                      # Pi 自动发现的项目级技能目录
│   ├── esg-monthly-report/              # 技能一：ESG 月报
│   │   ├── SKILL.md
│   │   ├── assets/report.css
│   │   ├── scripts/build_report.py      # md → 单文件 HTML + 引用质检
│   │   └── references/
│   │       ├── source-catalog.md        # 六方向信源分级与检索式
│   │       ├── report-spec.md           # 结构与写作规范
│   │       └── quality-checklist.md     # 交付质检清单
│   └── esg-tender-intel/                # 技能二：招投标情报
│       ├── SKILL.md
│       ├── scripts/tender_intel.py      # 采集/入库/统计/报告/推送
│       └── references/
│           ├── keyword-matrix.md        # 四簇关键词矩阵
│           └── sources.md               # 数据源可达性实测
├── data/
│   ├── case1/                            # 案例一的检索底稿
│   └── case2/
│       ├── tenders.db                    # SQLite 数据底座（565 条）
│       ├── stats_2024_2026.json          # 统计分析结果
│       ├── meta_report.json              # 报告的人工解读层
│       └── seeds/award_seed_2024_2026.json  # 人工核验的高置信度中标记录
└── reports/
    ├── 01_中国神华_ESG月报_2026-11.md / .html
    ├── 02_ESG招投标情报分析报告_2024-2026.md / .html
    ├── 03_ESG招标日报_样例_2026-11-24.md
    └── assets/                           # 报告图表（PNG）
```

## 二、环境

使用名为 `py312` 的虚拟环境（Python 3.12.13）：

```powershell
conda activate py312
# 或直接指定解释器
E:\software_data_center\conda_envs\py312\python.exe --version
```

依赖（均已预装，无需额外安装）：`requests`、`matplotlib`、`pandas`、`beautifulsoup4`。脚本本身只用标准库 + requests + matplotlib。

## 三、两个案例的完成情况

### 案例一：ESG 月报（以中国神华为客户）

- **统计期**：2026-10-25 ~ 2026-11-24
- **产出**：`reports/01_中国神华_ESG月报_2026-11.md`（及单文件 HTML）
- **覆盖**：政策/标准/评级动态、煤炭行业动态与最佳实践、公司动态的 ESG 影响与建议、对标企业关键行动
- **质量**：37 条来源全部带机构、日期、链接；引用质检 0 错误 0 提示；正文无占位符
- **关键判断**（详见报告第一节）：范围三是 2026 年报唯一带硬截止日的合规缺口；ISO 煤矿甲烷监测标准立项将重构范围一计量口径；碳市场配额收紧（预分配降至 50%）直接改写火电成本曲线

### 案例二：ESG 招投标情报

- **统计期**：2024-11-24 ~ 2026-11-24（过去 2 年）
- **产出**：
  - `reports/02_ESG招投标情报分析报告_2024-2026.md`（及 HTML，含 4 张图表）
  - `reports/03_ESG招标日报_样例_2026-11-24.md`（每日推送样例，幂等）
- **样本**：565 条入库 → 247 条有效公告（窗口内，已剔除 37 条白皮书/报告类文档）→ 86 条可定价（覆盖率 34.8%），可核验金额 1.83 亿元；其中**中标/成交阶段 61 条、可定价 47 条、金额合计 8,777 万元**
- **热点结论**：碳核查/核算是“低频厚利”（48 条 / 1.11 亿元 / 占可核验金额 60.5% / 单均 444 万元）；ESG 报告编制是“高频薄利”（72 条 / 777 万元 / 单均 43 万元）；碳足迹是确定性最高的增量带（41 条 / 单均 108 万元）
- **推送验证**：首次运行推送 4 条，二次运行推送 0 条（`pushed` 标记保证不重复打扰）

## 四、复现命令

```powershell
cd "作业一"
$env:PYTHONIOENCODING = "utf-8"

# 案例一：渲染 + 引用质检
python .agents\skills\esg-monthly-report\scripts\build_report.py `
  reports\01_中国神华_ESG月报_2026-11.md `
  --html reports\01_中国神华_ESG月报_2026-11.html --check

# 案例二：采集（增量幂等，可重复执行）
python .agents\skills\esg-tender-intel\scripts\tender_intel.py --db data\case2\tenders.db `
  collect --source 203060 --pages 2 --detail --kw ESG 碳核查 碳足迹 双碳

# 案例二：入库人工核验记录
python .agents\skills\esg-tender-intel\scripts\tender_intel.py --db data\case2\tenders.db `
  ingest "data\case2\seeds\*.json"

# 案例二：统计 + 图表
python .agents\skills\esg-tender-intel\scripts\tender_intel.py --db data\case2\tenders.db `
  analyze --since 2024-11-24 --assets reports\assets

# 案例二：出报告
python .agents\skills\esg-tender-intel\scripts\tender_intel.py --db data\case2\tenders.db `
  report --since 2024-11-24 --until 2026-11-24 --assets reports\assets `
  --meta data\case2\meta_report.json `
  --out reports\02_ESG招投标情报分析报告_2024-2026.md `
  --html reports\02_ESG招投标情报分析报告_2024-2026.html

# 案例二：每日推送
python .agents\skills\esg-tender-intel\scripts\tender_intel.py --db data\case2\tenders.db `
  push --days 1 --out reports\日报.md
```

## 五、两个技能的设计要点

| 设计 | 解决什么问题 |
| --- | --- |
| 技能只描述**流程与质量线**，脚本只做确定性工作 | 判断类工作留给模型，数字类工作留给代码，避免"模型编数字" |
| 报告数字由脚本产出，解读由 `meta.json` 注入 | 同一套数据可产出不同视角的报告，且数字永不出错 |
| `build_report.py --check` 强制引用闭环 | 引用编号与来源表不匹配直接报错，杜绝"看起来有来源" |
| 金额只从标题解析 + 上限校验 | 避开正文市场统计数据污染（曾出现 2.1 万亿元的假金额） |
| 中标人只接受人工核验输入，不做标题猜测 | 标题尾部猜公司名会把采购人误判为中标人（实测出现“云南红塔银行”之类错标） |
| `pushed` 字段做推送去重 | 定时任务重复执行不会重复打扰 |
| 数据局限写进报告正文（附录 D / 第 10 节） | 覆盖率 34.4%、中标人缺失 92% 都如实披露，结论不越界 |

## 六、已知局限

1. **中标人字段几乎全部缺失**（247 条仅 2 条可核验，缺 99.2%）：聚合站把成交供应商设为会员可见。报告因此不做市场份额推断，只归纳中标人类型。
2. **金额覆盖率为 34.8%**：报告所有金额结论均标注“可核验下限”，不反推市场规模。
3. **区域字段 59% 未标注**：区域结论只代表可识别子集，报告已声明。
4. **来源集中**（241/247 条，97.6% 来自 203060 双碳文库的标题抽取）：属二手聚合，关键结论建议回查原始公告（明细表已保留原文链接）。
5. **案例一的部分数据取自第三方解读**（神华 2025 年排放与强度），正式引用应以公司 ESG 报告原文为准，报告附录 D 已注明。