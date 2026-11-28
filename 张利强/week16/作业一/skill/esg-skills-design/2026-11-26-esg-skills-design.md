# ESG 双 Skill 设计（week16/作业一）

日期：2026-11-26
状态：已确认
需求来源：`README.md`（本周作业说明）

## 1. 背景与目标

在 `张利强/week16/作业一/` 内交付两个可被 OpenCode 加载的 Skill：

1. `esg-monthly-report`：按自然月汇总中国神华相关的 ESG 政策、行业/对标企业动态、神华自身动态，输出逐条带来源的 Markdown 简报，可选 PDF。
2. `esg-bid-monitor`：监控国内 ESG/可持续/双碳招投标与中标信息，支持近 2 年分片汇总（含金额分桶图表）与每日新增推送。

作业验收方式为老师直接阅读文件/文档，不依赖真实 API Key 跑通检索。因此目标是：结构完整、职责清晰、脚本接口真实可读，能在本机运行的部分实际运行。

## 2. 方案选择

考虑过三种组织方式：

- A. 自包含 Skill 包：`skill/esg-skills/<id>/` 内放 `SKILL.md`、`agents/`、`templates/`、`scripts/`，用 `opencode.json` 的 `skills` 指向 `./skill/esg-skills`。
- B. OpenCode 原生多 Agent：`.opencode/skills/` + `.opencode/agents/`，通过 `subagent` 工具拉起独立上下文。
- C. 单文件提示词：每个 Skill 只有一个 `SKILL.md`。

选择 **A**。原因：按用户要求把设计文档与 Skill 分目录存放（`skill/esg-skills-design/` 与 `skill/esg-skills/`），老师可直接按文件阅读；`opencode.json` 让它在当前目录下仍可被 OpenCode 发现；不引入子 Agent 的本地 ID 依赖和分散配置。代价是多 Agent 协作是“提示词分阶段”，不是真正隔离的上下文——这是文档型作业可接受的取舍。

## 3. 目录结构

```text
张利强/week16/作业一/
├── README.md                       # 原有作业说明，不改
├── AGENTS.md                       # 本目录开发约定
├── 交付说明.md                     # 文件地图、加载方式、限制
├── requirements.txt                # 第三方依赖
├── opencode.json                   # "skills": ["./skill/esg-skills"]
└── skill/
    ├── esg-skills-design/
    │   ├── 2026-11-26-esg-skills-design.md
    │   └── 2026-11-26-esg-skills-plan.md
    └── esg-skills/
        ├── esg-monthly-report/
        │   ├── SKILL.md
        │   ├── agents/
        │   │   ├── policy_search.md
        │   │   ├── industry_peer_search.md
        │   │   ├── shenhua_search.md
        │   │   ├── filter.md
        │   │   ├── writer.md
        │   │   └── validator.md
        │   ├── templates/report.md
        │   ├── scripts/
        │   │   ├── search_deepseek.py
        │   │   ├── validate_report.py
        │   │   ├── run_monthly.py
        │   │   └── md_to_pdf.py
        │   └── peer_set.json
        ├── esg-bid-monitor/
        │   ├── SKILL.md
        │   ├── agents/
        │   │   ├── slice_search.md
        │   │   ├── extract.md
        │   │   ├── dedupe.md
        │   │   ├── daily_push.md
        │   │   └── writer.md
        │   ├── templates/
        │   │   ├── monthly-report.md
        │   │   └── daily-push.md
        │   ├── scripts/
        │   │   ├── search_deepseek.py
        │   │   ├── validate_records.py
        │   │   ├── chart.py
        │   │   ├── daily_window.py
        │   │   └── md_to_pdf.py
        │   └── buffer/daily_buffer.json
        └── tests/
            ├── test_monthly_scripts.py
            └── test_bid_scripts.py
```

两个 Skill 各自复制 `search_deepseek.py` 与 `md_to_pdf.py`。这是有意为之：每个 Skill 必须能单独拷走使用，跨 Skill 引用会破坏自包含性；两个脚本都很小。

## 4. 月报 Skill

### 流程

1. 调度或用户注入 `target_month`（`YYYY-MM`）。未提供时先问用户，不猜测“最近一个月”。自动调度时由 `scripts/run_monthly.py` 判断第 1 个工作日并计算上个月。
2. `policy_search`、`industry_peer_search`、`shenhua_search` 三路并行检索。后两者读取 `peer_set.json`；为空时由 AI 圈定不超过 4 家对标企业并写回。
3. `filter` 剔除目标自然月之外的数据，按 URL 去重，保留标题、日期、摘要、来源。
4. `writer` 按 `templates/report.md` 写 800–1200 字简报。
5. `validator` 删除无来源陈述、修正越界日期；有硬错误时退回 writer。校验脚本同时拒绝空报告。
6. 输出 Markdown；用户需要时用 `scripts/md_to_pdf.py` 生成 PDF（可选，不阻断 Markdown 交付）。

### 硬约束

- 每条事实陈述带 `[来源: URL]`；无数据写 `暂无数据`。
- 只用检索结果，禁止用模型知识补全。
- 仅简体中文检索与输出。
- 数据源优先 `gov.cn`、`sse.com.cn` 等国内权威域名。

## 5. 招投标 Skill

### 工作流 A：近 2 年历史汇总

1. `slice_search` 按半年度切片，组合“ESG/可持续发展/双碳 + 招标/中标”等关键词检索。
2. `extract` 将结果转为统一 Schema；金额统一为万元，不明确填 `null`，并尽量标注 `announcement_type`。
3. `dedupe` 按 `source_url` 去重，并与 `buffer/daily_buffer.json` 比对；只读，不写盘。
4. `validate_records.py` 校验 Schema、类型、日期、金额、URL 和重复项。
5. `chart.py` 生成金额分桶图，默认只统计中标金额；有效金额 ≥5 时柱状图 + 饼图，1–4 时只出柱状图并注明样本量，0 条删除旧图且不出图。
6. `writer` 输出带图表的 Markdown 分析报告。

### 工作流 B：每日新增

1. 用 `scripts/daily_window.py` 计算固定窗口 `[昨天 00:00, 今天 00:00]`，时区 `Asia/Shanghai`。
2. 检索 → 抽取 → 去重 → `validate_records.py` 校验 → 输出去重后的当日列表。
3. 仅由 `daily_push` 一次性追加写入 `buffer/daily_buffer.json`；无记录输出 `暂无数据`，缓冲区不变。

### 统一 Schema

```json
{
  "project_name": "项目名称全称",
  "buyer": "买方全称",
  "winner": "中标方全称或 null",
  "amount_wan": 120.5,
  "publish_date": "YYYY-MM-DD",
  "category": "ESG/可持续/双碳",
  "source_url": "https://...",
  "announcement_type": "tender 或 award（可选）"
}
```

`amount_wan` 只接受万元正数或 `null`；`winner` 在招标公告无结果时为 `null`；`announcement_type` 是可选的派生字段，用来区分招标预算与中标金额。

## 6. 脚本接口

### `search_deepseek.py`

```text
--query 必填
--start / --end  YYYY-MM-DD
--site 可重复
--limit 默认 20
--output 可选，缺省输出 stdout
```

- `DEEPSEEK_API_KEY` 必填；缺失时退出码 2，明确报错，不发请求、不伪造结果。
- POST `https://api.deepseek.com/v1/tools/search`。
- 统一输出：`{"query", "start", "end", "results": [{"title","url","snippet","published_at"}]}`。
- 响应字段做兼容映射；README 未给出完整字段，代码注释注明“以官方响应为准”。

### `validate_report.py`

```text
--file 必填
--month YYYY-MM 必填
```

- 跳过标题、空行、分隔线、代码围栏。
- 其余非空行必须含 `[来源: http(s)://...]`，或整行为 `暂无数据`。
- 剥离 URL 后扫描 `YYYY-MM-DD` / `YYYY/MM/DD` / `YYYY年M月D日` / `YYYY年M月`，超出目标月即违规；中文紧邻日期也能识别。
- 空文件或纯空白文件直接判失败。
- 输出 JSON，退出码 0/1。

### `md_to_pdf.py`

```text
--input 必填
--output 必填
--title 可选
```

- reportlab + `UnicodeCIDFont("STSong-Light")`，不依赖 LaTeX/外部中文字体。
- 支持标题、段落、无序/有序列表、代码块、分隔线；表格按文本行渲染。

### `chart.py`

```text
--input 必填（数组或 {"records": [...]}）
--output-prefix 必填
--title 可选
--scope award|all  默认 award
```

- 分桶：`(0,50]`、`(50,100]`、`(100,200]`、`(200,500]`、`>500`，单位万元。
- 默认只统计中标金额：`announcement_type="tender"` 的记录不进入金额图；`--scope all` 时计入。
- 有效金额 ≥5：`<prefix>.png` 内柱状图 + 饼图。
- 1–4 条：只出柱状图并加“样本量较小，分布仅供参考”。
- 0 条：删除同前缀旧 PNG，不生成新文件，输出 `generated=false`。
- 非数字、`0`、负数金额跳过并计数，不静默归入错误桶。

### `validate_records.py`

```text
--input 必填
--output 可选
```

- 校验字段齐全、字段类型、日期格式与真实性、`amount_wan` 正数/null、URL 协议、重复 `source_url`。
- 对象输入必须显式包含 `records` 键；否则视为不可读输入。
- 输出 JSON 与违规列表，退出码 0/1；输入不可读时退出码 2。

### `run_monthly.py`

```text
--today YYYY-MM-DD 可选（测试/补跑）
--holiday YYYY-MM-DD 可重复
```

- 命中本月第 1 个工作日时输出上个月 `YYYY-MM`，退出 0；否则退出 3。
- 工作日默认周一至周五；节假日显式传入并顺延。

### `daily_window.py`

```text
--now ISO 8601 可选（测试/补跑）
```

- 输出 `{"timezone","start","end","start_date","end_date"}`，窗口为 `[昨天 00:00, 今天 00:00]`（`Asia/Shanghai`）。

## 7. 数据与状态

- `peer_set.json`：`{"peers": [], "updated_at": null}`，首次运行后写回。
- `daily_buffer.json`：初始 `[]`；只有 `daily` 模式的 `daily_push` 一次性追加，`history` 与 `dedupe` 只读。
- 生成物（PDF、PNG、检索缓存）不提交；脚本默认写到调用方指定路径。

## 8. 触发策略

两个 `description` 都要覆盖“用户没说出 Skill 名称但任务本质相同”的情况：

- 月报：ESG 月报、月度简报、中国神华 ESG、ESG 政策汇总、双碳月报、某月 ESG 动态汇总。
- 招投标：ESG 招投标、中标监控、双碳招标、ESG 标讯日报、近两年招投标汇总、招标信息监控。

描述里写清“做什么 + 什么时候用”，保持 kebab-case ID 与目录名一致。

## 9. 非目标

- 不做真实定时器；只提供手动触发与 cron/launchd 示例。
- 不实现真实搜索 API 的端到端验证（无 Key）。
- 不引入数据库、向量库、外部服务。
- 不修改其他目录、其他周次或其他同学的文件。

## 10. 约束

- Python 3.12（conda `py312`，`/opt/anaconda3/envs/py312/bin/python`）。
- 仅使用标准库 + 已安装的 `requests`、`pandas`、`matplotlib`、`reportlab`。
- 所有文件位于 `张利强/week16/作业一/` 内。
- 文件名不含空格或多余 `.`。

## 11. 验证

- `skill_validate` 校验两个 `SKILL.md`。
- `python -m py_compile` 校验全部脚本。
- 用临时数据实跑：`chart.py` 的 0 / 1–4 / ≥5 条有效金额三种情况、两个 validator 的正常/异常输入、`md_to_pdf.py` 生成 PDF。
- `run_monthly.py` 的第 1 个工作日/节假日顺延，`daily_window.py` 的 Asia/Shanghai 窗口。
- `search_deepseek.py --help` 与缺失 Key 的报错路径。
- 最终 `git status` 只包含本作业目录内的预期文件。
