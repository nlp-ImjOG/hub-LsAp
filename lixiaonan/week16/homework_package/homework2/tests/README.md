# homework2 测试手册（M1）

> 所有命令均在本目录上级（`homework2/`）执行。**零第三方依赖、零联网**，只需 Python 3.9+。

---

## 1. T1 单元测试（约 2 秒）

```bash
cd homework2
python3 -m unittest discover -s tests -v
```

**期望输出**（末尾两行）：

```
Ran 58 tests in ~2s
OK
```

覆盖：parse_args（时间表达/行业查表/CLI 契约）、filter + URL/标题归一化（设计文档 8 条规则逐条断言、黑名单三场景）、check（R1–R7 每条规则 1 正 1 反）。任何一条 FAIL 都对应一个明确的规则回归。

## 2. 端到端 Demo（可执行验收单，约 1 秒）

```bash
python3 tests/demo_m1.py
```

**期望**：6 个阶段全部 ✓，末尾 `演示结果: 16/16 项符合预期`，**退出码 0**。

阶段流程：

| 阶段 | 脚本 | 演示内容 | 预期 |
|------|------|---------|------|
| 0 | `parse_args.py` | "近一个月"→日期区间 + 行业查表 | window=2026-10-25:2026-11-24，行业=煤炭/传统能源 |
| 1 | `filter.py monthly` | 7 条候选规则初筛 | 4 过 3 拒（dup_url/dup_title/out_of_window 各 1） |
| 2 | — | passed 交接清单展示 | 4 条待模型语义终判 |
| 3 | `check.py report` | 合格报告放行 / 违规报告拦截 | good: 0 error；bad: 8 error + 4 warn，exit 1 |
| 4 | `check.py db` | bids.jsonl 体检 | 合法库放行；问题库 6 error |
| 5 | `filter.py bid` | 黑名单拦截与 unless 豁免 | 绿色通道拦截、绿化带 keyword_miss、碳汇豁免放行 |

产物落盘 `tests/demo_output/`（meta/filtered/check_good/check_bad/check_db/filtered_bid 共 6 个 JSON），可随时删除，重跑自动重建。任一阶段 ✗ → 退出码 1，可直接接 CI。

## 3. 单脚本手动体验（直观感受每个脚本）

```bash
# ① 参数解析：换几个时间表达试
python3 .claude/skills/esg-monthly-report-scripted/scripts/parse_args.py --today 2026-11-24 --period "2026-11"
python3 .claude/skills/esg-monthly-report-scripted/scripts/parse_args.py --today 2026-11-24 --mode report          # 默认近2年
python3 .claude/skills/esg-monthly-report-scripted/scripts/parse_args.py --client 某某科技                          # 行业查不到 → needs_search 提示

# ② 规则初筛：monthly 宽松 / bid 硬规则（stdout 输出 JSON，--out 可落盘）
python3 .claude/skills/esg-monthly-report-scripted/scripts/filter.py \
    --input tests/fixtures/candidates_monthly.json --window "2026-10-25:2026-11-24" \
    --mode monthly --client 中国神华
python3 .claude/skills/esg-monthly-report-scripted/scripts/filter.py \
    --input tests/fixtures/candidates_bid.json --window "2026-10-25:2026-11-24" \
    --mode bid --keywords .claude/skills/esg-bid-monitor-scripted/references/keywords.json

# ③ 报告自查：对同一份报告改一个字符观察 exit code 变化
python3 .claude/skills/esg-monthly-report-scripted/scripts/check.py report \
    --file tests/fixtures/report_good.md --window "2026-10-25:2026-11-24" \
    --notes tests/fixtures/notes_good.md; echo "exit=$?"
python3 .claude/skills/esg-monthly-report-scripted/scripts/check.py report \
    --file tests/fixtures/report_bad.md --window "2026-10-25:2026-11-24"; echo "exit=$?"

# ④ 标讯库体检
python3 .claude/skills/esg-monthly-report-scripted/scripts/check.py db \
    --db tests/fixtures/bids_bad.jsonl --state tests/fixtures/state_bad.json; echo "exit=$?"
```

**看什么**：① 输出 meta.json 结构（设计文档第 2 章契约）；② rejected 每条必带 reason_code，passed 带中文 filter_notes；③/④ error→exit 1、warn 不影响 exit code。

## 4. 常见问题

- **为什么测试不用今天的日期？** parse_args/filter 都支持 `--today` 固定锚点，测试必须可重放；真实运行时不传即取系统日期。
- **词库在哪、怎么换？** `--keywords` 显式指定；不传时 filter.py 自动取本 skill 包的 `references/keywords.json`。
- **check.py 的 `--min-words`？** 各正文章节内容量下限（默认 300，跳过"摘要"与"附录"章）；demo 的 bad 样本用 150 以保证违规数精确可控。
- **`近2年` 算到哪天？** 规则是 today − 730 天（闭区间到 today），如 2026-11-24 → 2024-11-24。

## 5. 后续里程碑的测试（占位）

| 里程碑 | 测试 | 命令（实现后可用） |
|--------|------|--------------------|
| M2 search.py | T3 联网冒烟（单次小预算，验证 URL 打开率 ≥70%） | `python3 scripts/search.py plan/run/fetch …` |
| M3 render.py | golden-file 对比 | `python3 -m unittest tests.test_render` |
| M4 extract/store | 金额换算表 7 用例 + 入库合并 | `python3 -m unittest tests.test_extract tests.test_store` |
| M5 A/B 实验 | 每组 3 次 + evaluate.py 采指标 + 盲评 | 见 `作业2_设计文档.md` 第 5 章 T4 步骤 |
