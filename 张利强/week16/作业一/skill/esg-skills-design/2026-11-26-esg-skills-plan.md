# ESG 双 Skill 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `张利强/week16/作业一/` 内交付两个可读、可加载的 OpenCode Skill（ESG 月报、ESG 招投标监控），脚本接口完整、可运行部分实际运行。

**Architecture:** 自包含 Skill 包（方案 A）。每个 Skill 用 `SKILL.md` 编排阶段，`agents/` 存阶段提示词，`templates/` 存输出模板，`scripts/` 存检索、校验、图表、PDF 工具；根级 `opencode.json` 通过 `skills: ["./skill/esg-skills"]` 发现技能。

**Tech Stack:** Python 3.12（conda `py312`）、requests、pandas、matplotlib、reportlab、Markdown。

**Spec:** `skill/esg-skills-design/2026-11-26-esg-skills-design.md`

## Global Constraints

- 所有文件只能位于 `张利强/week16/作业一/`，不得读写其他目录。
- 运行 Python 一律用 `conda run -n py312 python`；不要用系统 `python3`（3.13.4）。
- 仅使用标准库 + `requests`、`pandas`、`matplotlib`、`reportlab`；不新增依赖。
- 输出语言为简体中文；每条事实陈述带 `[来源: URL]`，无数据写 `暂无数据`。
- 检索接口固定为 `https://api.deepseek.com/v1/tools/search`，密钥从 `DEEPSEEK_API_KEY` 读取。
- `target_month` 为 `YYYY-MM`；自然月语义，不是“最近 30 天”。
- 招投标金额单位为万元，`amount_wan` 只接受万元正数或 `null`；日期 `YYYY-MM-DD`；时区 `Asia/Shanghai`。
- 图表分桶固定：`(0,50]`、`(50,100]`、`(100,200]`、`(200,500]`、`>500`。
- 文件名不含空格或多余 `.`；Skill ID 与目录名一致，kebab-case。
- 不修改现有 `README.md`；不提交 PDF/PNG/检索缓存。

## Review Focus

- `DEEPSEEK_API_KEY` 缺失时，脚本必须退出 2 并给出明确错误，不发请求、不编造结果。
- 有效金额为 0 时，`chart.py` 不生成空 PNG，报告写 `暂无数据`。
- 有效金额条数 1–4 时，只生成柱状图并标注“样本量较小，分布仅供参考”，不生成饼图。
- 金额为千分位字符串、带“亿/万”单位、负数或非数字时，必须跳过并计数，不能静默归入错误分桶。
- 报告存在无来源行或越界日期时，`validate_report.py` 必须退出 1 并给出行号。

---

### Task 1: 配置与交付骨架

**Files:**
- Create: `opencode.json`
- Keep: `AGENTS.md`、`skill/esg-skills-design/2026-11-26-esg-skills-design.md`、本计划

**Interfaces:**
- Produces: `opencode.json` 的 `"skills": ["./skill/esg-skills"]`，让 OpenCode 在作业目录为工作目录时发现两个 Skill。

- [ ] **Step 1: 写 `opencode.json`**

```json
{
  "$schema": "https://opencode.ai/config.json",
  "skills": ["./skill/esg-skills"]
}
```

- [ ] **Step 2: 校验 JSON**

Run: `conda run -n py312 python -c "import json; d=json.load(open('opencode.json')); print(d['skills'])"`
Expected: `['./skill/esg-skills']`

- [ ] **Step 3: 提交骨架**

```bash
git add opencode.json AGENTS.md skill/esg-skills-design/2026-11-26-esg-skills-design.md skill/esg-skills-design/2026-11-26-esg-skills-plan.md
git commit -m "张利强 week16 ESG双Skill 作业骨架"
```

---

### Task 2: 月报 Skill 文档

**Files:**
- Create: `skill/esg-skills/esg-monthly-report/SKILL.md`
- Create: `skill/esg-skills/esg-monthly-report/agents/policy_search.md`
- Create: `skill/esg-skills/esg-monthly-report/agents/industry_peer_search.md`
- Create: `skill/esg-skills/esg-monthly-report/agents/shenhua_search.md`
- Create: `skill/esg-skills/esg-monthly-report/agents/filter.md`
- Create: `skill/esg-skills/esg-monthly-report/agents/writer.md`
- Create: `skill/esg-skills/esg-monthly-report/agents/validator.md`
- Create: `skill/esg-skills/esg-monthly-report/templates/report.md`
- Create: `skill/esg-skills/esg-monthly-report/peer_set.json`

**Interfaces:**
- Produces: Skill ID `esg-monthly-report`；输入 `target_month`（`YYYY-MM`，必填）、`include_peers`（布尔，默认 `false`）。
- Consumes: Task 3 的 `scripts/search_deepseek.py`、`scripts/validate_report.py`、`scripts/md_to_pdf.py`。
- Produces: `peer_set.json` 结构 `{"peers": [], "updated_at": null}`；`templates/report.md` 中的占位符 `{{TARGET_MONTH}}`、`{{GENERATED_AT}}`、`{{BODY}}`、`{{PEERS}}`。

- [ ] **Step 1: 写 `SKILL.md`**

frontmatter 必须严格写成：

```yaml
---
name: esg-monthly-report
description: 生成中国神华 ESG 月度简报：按自然月检索国内 ESG 政策、行业与对标企业动态、神华自身动态，过滤去重、逐条标注来源并校验后输出 Markdown（可选 PDF）。当用户提到“ESG 月报”“ESG 月度简报”“中国神华 ESG”“ESG 政策汇总”“双碳月报”，或要求按某个自然月汇总 ESG 政策/行业动态时使用；即使用户没说出“月报”，只要任务是按自然月汇总 ESG 信息，也应使用。
---
```

正文依次写：适用场景、输入参数、四阶段工作流（搜索 → 过滤 → 撰写 → 校验）、引用与零幻觉规则、脚本调用示例、cron/launchd 触发示例、失败处理。控制在 150 行内。

- [ ] **Step 2: 写 6 个阶段提示词**

每个文件包含：角色、输入、执行步骤、输出格式、禁止事项。`policy_search.md` 负责政策/标准；`industry_peer_search.md` 负责行业与对标企业；`shenhua_search.md` 负责神华自身动态；`filter.md` 负责自然月过滤与 URL 去重；`writer.md` 按模板写作；`validator.md` 删除无来源陈述并检查日期越界。

- [ ] **Step 3: 写模板与初始 `peer_set.json`**

`templates/report.md` 至少包含：标题、月份、生成时间、摘要、政策动态、行业与对标、神华动态、影响建议、来源清单。`peer_set.json` 写：

```json
{"peers": [], "updated_at": null}
```

- [ ] **Step 4: 校验结构**

Run: `conda run -n py312 python -c "import json; print(json.load(open('skill/esg-skills/esg-monthly-report/peer_set.json')))"`
Expected: `{'peers': [], 'updated_at': None}`

Run: `skill_validate(skillPath=".../skill/esg-skills/esg-monthly-report")`
Expected: 校验通过，无 frontmatter/name/description 错误。

- [ ] **Step 5: 检查关键约束是否写进文档**

Run: `grep -c "\[来源: URL\]" skill/esg-skills/esg-monthly-report/SKILL.md`
Expected: ≥1

Run: `grep -c "target_month" skill/esg-skills/esg-monthly-report/SKILL.md`
Expected: ≥1

- [ ] **Step 6: 提交**

```bash
git add skill/esg-skills/esg-monthly-report
git commit -m "张利强 week16 ESG月报 Skill 作业"
```

---

### Task 3: 月报脚本

**Files:**
- Create: `skill/esg-skills/esg-monthly-report/scripts/search_deepseek.py`
- Create: `skill/esg-skills/esg-monthly-report/scripts/validate_report.py`
- Create: `skill/esg-skills/esg-monthly-report/scripts/md_to_pdf.py`

**Interfaces:**
- `search_deepseek.py`：CLI `--query`（必填）、`--start`、`--end`、`--site`（可重复）、`--limit`（默认 20）、`--output`；环境变量 `DEEPSEEK_API_KEY`；成功输出 `{"query","start","end","results":[{"title","url","snippet","published_at"}]}`；退出码 0/2/3。
- `validate_report.py`：CLI `--file`、`--month`；输出 `{"ok","month","violations":[{"line","reason"}],"checked_lines"}`；退出码 0/1。
- `md_to_pdf.py`：CLI `--input`、`--output`、`--title`；使用 `UnicodeCIDFont("STSong-Light")`；退出码 0/2。

- [ ] **Step 1: 写 `search_deepseek.py`**

用 `requests.post` 调 README 指定端点；请求体包含 `query`、`max_results`、`start_date`、`end_date`、`site`。响应做兼容映射（`results`/`data`/`items`；`title`/`name`；`url`/`link`/`source_url`；`snippet`/`content`/`description`；`published_at`/`date`/`publish_date`）。缺 Key 时 `print` 错误到 stderr 并 `sys.exit(2)`。

- [ ] **Step 2: 校验检索脚本的失败路径**

Run: `conda run -n py312 python skill/esg-skills/esg-monthly-report/scripts/search_deepseek.py --help`
Expected: 打印用法，退出 0。

Run: `env -u DEEPSEEK_API_KEY conda run -n py312 python skill/esg-skills/esg-monthly-report/scripts/search_deepseek.py --query test`
Expected: stderr 含 `DEEPSEEK_API_KEY`，退出 2。

- [ ] **Step 3: 写 `validate_report.py` 并测试正常/异常输入**

跳过 `#` 标题、空行、`---`、代码围栏；其余非空行必须含 `[来源: http(s)://...]` 或整行为 `暂无数据`。剥离 URL 后扫描 `YYYY-MM-DD` 与 `YYYY年M月D日`。

Run:
```bash
TMP=$(mktemp -d)
cat > "$TMP/bad.md" <<'EOF'
# 测试
- 没有来源的陈述
- 2026-10-01 越界 [来源: https://example.com/a]
- 正常陈述 [来源: https://example.com/b]
EOF
conda run -n py312 python skill/esg-skills/esg-monthly-report/scripts/validate_report.py --file "$TMP/bad.md" --month 2026-11
echo "exit=$?"
```
Expected: JSON 中 `ok=false`，违规行号为 2、3；`exit=1`。

```bash
TMP=$(mktemp -d)
cat > "$TMP/good.md" <<'EOF'
# 测试
- 2026-11-05 某政策发布 [来源: https://example.com/a]
- 暂无数据
EOF
conda run -n py312 python skill/esg-skills/esg-monthly-report/scripts/validate_report.py --file "$TMP/good.md" --month 2026-11
echo "exit=$?"
```
Expected: `ok=true`，`exit=0`。

- [ ] **Step 4: 写 `md_to_pdf.py` 并生成 PDF**

Run:
```bash
conda run -n py312 python skill/esg-skills/esg-monthly-report/scripts/md_to_pdf.py \
  --input skill/esg-skills/esg-monthly-report/templates/report.md \
  --output /tmp/esg-monthly-test.pdf --title "ESG 月报测试"
test -s /tmp/esg-monthly-test.pdf && echo PDF_OK
```
Expected: 输出 `PDF_OK`。

- [ ] **Step 5: 编译检查并提交**

Run: `conda run -n py312 python -m py_compile skill/esg-skills/esg-monthly-report/scripts/*.py`
Expected: 退出 0，无输出。

```bash
git add skill/esg-skills/esg-monthly-report/scripts
git commit -m "张利强 week16 ESG月报脚本 作业"
```

---

### Task 4: 招投标 Skill 文档

**Files:**
- Create: `skill/esg-skills/esg-bid-monitor/SKILL.md`
- Create: `skill/esg-skills/esg-bid-monitor/agents/slice_search.md`
- Create: `skill/esg-skills/esg-bid-monitor/agents/extract.md`
- Create: `skill/esg-skills/esg-bid-monitor/agents/dedupe.md`
- Create: `skill/esg-skills/esg-bid-monitor/agents/daily_push.md`
- Create: `skill/esg-skills/esg-bid-monitor/agents/writer.md`
- Create: `skill/esg-skills/esg-bid-monitor/templates/monthly-report.md`
- Create: `skill/esg-skills/esg-bid-monitor/templates/daily-push.md`
- Create: `skill/esg-skills/esg-bid-monitor/buffer/daily_buffer.json`

**Interfaces:**
- Produces: Skill ID `esg-bid-monitor`；模式 `history`（近 2 年汇总）与 `daily`（每日增量）。
- Consumes: Task 5 的 `scripts/search_deepseek.py`、`scripts/validate_records.py`、`scripts/chart.py`、`scripts/md_to_pdf.py`。
- Produces: `buffer/daily_buffer.json` 初始 `[]`；记录 Schema 字段 `project_name`、`buyer`、`winner`、`amount_wan`、`publish_date`、`category`、`source_url`。

- [ ] **Step 1: 写 `SKILL.md`**

frontmatter 必须严格写成：

```yaml
---
name: esg-bid-monitor
description: 监控国内 ESG、可持续发展、双碳相关招投标与中标信息：支持近 2 年半年度分片汇总、金额统一为万元并生成分桶图表，以及每日新增标讯推送。当用户提到“ESG 招投标”“中标监控”“双碳招标”“ESG 标讯日报”“近两年招投标汇总”“招标信息监控”，或要求汇总/监控 ESG 相关招标、中标公告时使用；即使用户没有明确说“监控”，只要任务是招投标信息的汇总或增量追踪，也应使用。
---
```

正文写：两种模式、分片策略、Schema、金额/日期/时区规则、图表规则、每日窗口 `[昨天 00:00, 今天 00:00]`、cron/launchd 示例、失败处理。控制在 180 行内。

- [ ] **Step 2: 写 5 个阶段提示词**

`slice_search.md` 负责半年度切片与关键词组合；`extract.md` 负责统一 Schema 与金额归一；`dedupe.md` 负责 URL 去重与缓冲区合并；`daily_push.md` 负责每日列表与追加写入；`writer.md` 负责综合报告与图表说明。

- [ ] **Step 3: 写模板与初始缓冲区**

`templates/monthly-report.md` 包含：概览、金额分布图占位、买方类型、高频项目词、重点项目表、数据说明。`templates/daily-push.md` 包含日期窗口、新增列表、无数据提示。`buffer/daily_buffer.json` 写 `[]`。

- [ ] **Step 4: 校验结构**

Run: `conda run -n py312 python -c "import json; print(json.load(open('skill/esg-skills/esg-bid-monitor/buffer/daily_buffer.json')))"`
Expected: `[]`

Run: `skill_validate(skillPath=".../skill/esg-skills/esg-bid-monitor")`
Expected: 校验通过。

- [ ] **Step 5: 检查关键约束是否写进文档**

Run: `grep -c "amount_wan" skill/esg-skills/esg-bid-monitor/SKILL.md`
Expected: ≥1

Run: `grep -c "昨天 00:00" skill/esg-skills/esg-bid-monitor/SKILL.md`
Expected: ≥1

- [ ] **Step 6: 提交**

```bash
git add skill/esg-skills/esg-bid-monitor
git commit -m "张利强 week16 ESG招投标 Skill 作业"
```

---

### Task 5: 招投标脚本

**Files:**
- Create: `skill/esg-skills/esg-bid-monitor/scripts/search_deepseek.py`（从月报复制，接口相同）
- Create: `skill/esg-skills/esg-bid-monitor/scripts/md_to_pdf.py`（从月报复制，接口相同）
- Create: `skill/esg-skills/esg-bid-monitor/scripts/validate_records.py`
- Create: `skill/esg-skills/esg-bid-monitor/scripts/chart.py`

**Interfaces:**
- `validate_records.py`：CLI `--input`、`--output`；输出 `{"ok","total","valid","violations":[{"index","field","reason"}]}`；退出码 0/1/2。
- `chart.py`：CLI `--input`、`--output-prefix`、`--title`；输出 `{"generated","chart","records","valid_amounts","buckets","output","note"}`；退出码 0/2。

- [ ] **Step 1: 复制共用脚本并编译**

Run:
```bash
cp skill/esg-skills/esg-monthly-report/scripts/search_deepseek.py skill/esg-skills/esg-bid-monitor/scripts/
cp skill/esg-skills/esg-monthly-report/scripts/md_to_pdf.py skill/esg-skills/esg-bid-monitor/scripts/
conda run -n py312 python -m py_compile skill/esg-skills/esg-bid-monitor/scripts/*.py
```
Expected: 退出 0。

- [ ] **Step 2: 写 `validate_records.py` 并测试**

校验字段齐全、日期可解析、`amount_wan` 为万元正数或 `null`、`source_url` 为 http(s)、`source_url` 不重复。

Run:
```bash
TMP=$(mktemp -d)
cat > "$TMP/bad.json" <<'EOF'
[
  {"project_name":"A","buyer":"甲","winner":null,"amount_wan":"约1200万","publish_date":"2026-13-01","category":"ESG","source_url":"not-a-url"},
  {"project_name":"B","buyer":"乙","winner":"丙","amount_wan":120,"publish_date":"2026-11-01","category":"双碳","source_url":"https://example.com/b"}
]
EOF
conda run -n py312 python skill/esg-skills/esg-bid-monitor/scripts/validate_records.py --input "$TMP/bad.json"
echo "exit=$?"
```
Expected: `ok=false`，列出 `amount_wan`、`publish_date`、`source_url` 违规；`exit=1`。

Run 正常输入：

```bash
TMP=$(mktemp -d)
cat > "$TMP/good.json" <<'EOF'
[
  {"project_name":"A","buyer":"甲","winner":null,"amount_wan":120,"publish_date":"2026-11-01","category":"ESG","source_url":"https://example.com/a"},
  {"project_name":"B","buyer":"乙","winner":"丙","amount_wan":null,"publish_date":"2026-11-02","category":"双碳","source_url":"https://example.com/b"}
]
EOF
conda run -n py312 python skill/esg-skills/esg-bid-monitor/scripts/validate_records.py --input "$TMP/good.json"
echo "exit=$?"
```
Expected: `ok=true`、`total=2`、`valid=2`；`exit=0`。

- [ ] **Step 3: 写 `chart.py` 并测试 0、1–4、≥5 条有效金额**

金额解析只接受 `int`/`float` 与纯数字字符串（可含千分位逗号）；带“亿/万”、负数、`null` 计入跳过。`matplotlib.use("Agg")`；中文字体候选 `PingFang SC`、`Heiti TC`、`STHeiti`、`Arial Unicode MS`、`DejaVu Sans`。

Run 6 条有效金额：

```bash
mkdir -p /tmp/esg-chart-test
cat > /tmp/esg-chart-test/six.json <<'EOF'
[
  {"project_name":"P1","buyer":"甲","winner":null,"amount_wan":10,"publish_date":"2026-11-01","category":"ESG","source_url":"https://example.com/1"},
  {"project_name":"P2","buyer":"甲","winner":"乙","amount_wan":60,"publish_date":"2026-11-02","category":"ESG","source_url":"https://example.com/2"},
  {"project_name":"P3","buyer":"甲","winner":"乙","amount_wan":80,"publish_date":"2026-11-03","category":"ESG","source_url":"https://example.com/3"},
  {"project_name":"P4","buyer":"甲","winner":"乙","amount_wan":120,"publish_date":"2026-11-04","category":"ESG","source_url":"https://example.com/4"},
  {"project_name":"P5","buyer":"甲","winner":"乙","amount_wan":250,"publish_date":"2026-11-05","category":"ESG","source_url":"https://example.com/5"},
  {"project_name":"P6","buyer":"甲","winner":"乙","amount_wan":600,"publish_date":"2026-11-06","category":"ESG","source_url":"https://example.com/6"}
]
EOF
conda run -n py312 python skill/esg-skills/esg-bid-monitor/scripts/chart.py --input /tmp/esg-chart-test/six.json --output-prefix /tmp/esg-chart-test/six
test -s /tmp/esg-chart-test/six.png && echo PNG_OK
```
Expected: JSON `generated=true`、`chart="bar+pie"`、`valid_amounts=6`；输出 `PNG_OK`。

Run 4 条：

```bash
mkdir -p /tmp/esg-chart-test
cat > /tmp/esg-chart-test/four.json <<'EOF'
[
  {"project_name":"P1","buyer":"甲","winner":null,"amount_wan":10,"publish_date":"2026-11-01","category":"ESG","source_url":"https://example.com/1"},
  {"project_name":"P2","buyer":"甲","winner":"乙","amount_wan":60,"publish_date":"2026-11-02","category":"ESG","source_url":"https://example.com/2"},
  {"project_name":"P3","buyer":"甲","winner":"乙","amount_wan":120,"publish_date":"2026-11-03","category":"ESG","source_url":"https://example.com/3"},
  {"project_name":"P4","buyer":"甲","winner":"乙","amount_wan":250,"publish_date":"2026-11-04","category":"ESG","source_url":"https://example.com/4"}
]
EOF
conda run -n py312 python skill/esg-skills/esg-bid-monitor/scripts/chart.py --input /tmp/esg-chart-test/four.json --output-prefix /tmp/esg-chart-test/four
test -s /tmp/esg-chart-test/four.png && echo PNG_OK
```
Expected: `chart="bar"`、`note` 含“样本量较小，分布仅供参考”；输出 `PNG_OK`。

Run 0 条（全 `null`）：

```bash
mkdir -p /tmp/esg-chart-test
rm -f /tmp/esg-chart-test/zero.png
cat > /tmp/esg-chart-test/zero.json <<'EOF'
[
  {"project_name":"P1","buyer":"甲","winner":null,"amount_wan":null,"publish_date":"2026-11-01","category":"ESG","source_url":"https://example.com/1"},
  {"project_name":"P2","buyer":"甲","winner":"乙","amount_wan":"暂无数据","publish_date":"2026-11-02","category":"ESG","source_url":"https://example.com/2"}
]
EOF
conda run -n py312 python skill/esg-skills/esg-bid-monitor/scripts/chart.py --input /tmp/esg-chart-test/zero.json --output-prefix /tmp/esg-chart-test/zero
test ! -e /tmp/esg-chart-test/zero.png && echo NO_PNG
```
Expected: `generated=false`、`valid_amounts=0`；输出 `NO_PNG`。

- [ ] **Step 4: 编译检查并提交**

Run: `conda run -n py312 python -m py_compile skill/esg-skills/esg-bid-monitor/scripts/*.py`
Expected: 退出 0。

```bash
git add skill/esg-skills/esg-bid-monitor/scripts
git commit -m "张利强 week16 ESG招投标脚本 作业"
```

---

### Task 6: 交付说明与最终校验

**Files:**
- Create: `交付说明.md`

**Interfaces:**
- Consumes: 前五个 Task 的全部产物。
- Produces: 老师阅读入口：文件地图、加载方式、触发示例、环境变量、定时示例、限制与验证结果。

- [ ] **Step 1: 写 `交付说明.md`**

包含：两个 Skill 的一句话说明；目录树；如何加载（在作业目录运行 OpenCode，`opencode.json` 自动发现 `./skill/esg-skills`）；触发示例（中英文关键词）；`DEEPSEEK_API_KEY` 配置；cron/launchd 示例；无 Key、PDF 可选、定时器需外部实现的限制；已执行的校验命令与结果。

- [ ] **Step 2: 最终结构校验**

Run: `skill_validate(skillPath=".../skill/esg-skills/esg-monthly-report")` 与 `skill_validate(skillPath=".../skill/esg-skills/esg-bid-monitor")`
Expected: 两者均通过。

Run: `skill_parse` 两个 Skill
Expected: `name` 与目录名一致，`description` 非空。

Run: `conda run -n py312 python -m py_compile skill/esg-skills/esg-monthly-report/scripts/*.py skill/esg-skills/esg-bid-monitor/scripts/*.py`
Expected: 退出 0。

- [ ] **Step 3: 端到端冒烟**

Run: 用 Task 3/5 的临时数据再次执行 `chart.py`、`validate_report.py`、`validate_records.py`、`md_to_pdf.py`
Expected: PNG/PDF 生成，validator 正常/异常输入分别退出 0/1。

- [ ] **Step 4: 检查改动范围**

Run: `git status --short`
Expected: 只出现 `张利强/week16/作业一/` 下的预期文件；不出现其他目录、PDF、PNG、缓存。

- [ ] **Step 5: 提交**

```bash
git add 交付说明.md
git commit -m "张利强 week16 ESG双Skill 交付说明 作业"
```
