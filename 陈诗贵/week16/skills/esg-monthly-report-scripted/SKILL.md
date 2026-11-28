---
name: esg-monthly-report-scripted
description: 带确定性脚本的 ESG 月报技能。当用户需要汇总过去一个月真实发生的 ESG 政策、评级、标准动态，客户行业新闻与最佳实践，客户公司动态及对标企业关键行动并生成月报时报此技能。脚本负责联网搜索、信息抽取校验、周期过滤、去重与模板渲染，DeepSeek 负责内容总结；与纯提示词版 esg-monthly-report 配合用于效果对比。
---

# ESG 月报技能（确定性脚本版）

将 ESG 月报工作拆成两层：

- **确定性层（Python 脚本）**：联网搜索、抓取正文、周期过滤、去重、字段校验、分类归档、模板渲染、完整性检查。同一输入必然得到同一结果。
- **智能层（DeepSeek LLM）**：从素材中抽取结构化事实、生成摘要与建议。**只允许基于脚本提供的素材，禁止引入新事实。**

## 一、环境准备

依赖（已在本机验证可用）：

```powershell
pip install -r .claude/skills/esg-monthly-report-scripted/requirements.txt
```

模型配置从环境变量读取，脚本会自动向上查找仓库根目录的 `.env`：

| 变量 | 说明 |
|---|---|
| `DS_API_KEY` | DeepSeek API Key（必需） |
| `LLM_BASE_URL` | OpenAI 兼容接口地址，默认 `https://api.deepseek.com` |
| `LLM_MODEL` | 模型名，默认 `deepseek-chat` |

缺少 Key 或网络失败时脚本会**明确报错退出**，不会用假数据填充。

## 二、执行流程（在项目根目录 `week16` 下运行）

```powershell
# 1) 搜索 + 抽取 + 过滤（默认统计到昨天为止的 30 天）
python .claude/skills/esg-monthly-report-scripted/scripts/collect_news.py --days 30 --company 中国神华 --industry 煤炭

# 2) 渲染月报（确定性模板 + 质量检查）
python .claude/skills/esg-monthly-report-scripted/scripts/render_report.py
```

常用参数：

- `--as-of YYYY-MM-DD`：报告截止日（复现对比实验时固定此参数）
- `--days 30`：报告周期长度
- `--top-per-query 8`：每个检索词保留的搜索结果数
- `--fetch-top 5`：每个检索词抓取正文的页面数
- `--out-dir`：输出目录，默认 `output/`

产物：

- `output/collected.json`：结构化新闻 + 过滤/去重/校验记录 + LLM 摘要建议
- `output/ESG月报_<as_of>.md`：最终月报
- 控制台打印：搜索命中数、窗口内/外/日期未知数量、去重数量、质量检查表

## 三、脚本与职责边界

| 脚本 | 确定性职责 | DeepSeek 职责 |
|---|---|---|
| `scripts/collect_news.py` | 生成检索词、调用搜索引擎、抓正文、按 `as_of/--days` 过滤、URL/标题去重、日期格式归一化 | 把素材抽取为 `date/category/dimension/summary/impact`；生成摘要、ESG 建议、信息缺口 |
| `scripts/render_report.py` | 固定章节模板、按分类排序渲染、统计各章节条数、检查必填字段与附录一致性 | 无（只消费 `collected.json` 中的 editorial 字段） |
| `scripts/web_search.py` | 360 / Bing / DuckDuckGo 检索，多引擎自动降级 | 无 |
| `scripts/deepseek_client.py` | 环境变量加载、JSON 解析、重试 | 调用 `LLM_BASE_URL` 返回 JSON |

## 四、抽取与校验规则（脚本强制执行）

1. **日期**：LLM 给出的日期必须能从素材文本中找到对应写法（`YYYY-MM-DD`、`YYYY年M月D日`、`YYYY/M/D` 等），否则标记 `date_unverified` 并单独列出。
2. **分类**：只接受 `policy / rating / industry / best_practice / company / peer`，非法值归入 `industry` 并记录告警。
3. **维度**：只接受 `E / S / G`，非法值置空并告警。
4. **周期过滤**：确定性执行——窗口内进正文；窗口外进 `out_of_window`；日期未知进 `date_unknown`，在"信息缺口"中列明，不混入正文。
5. **去重**：规范化 URL 或去标点后的标题相同即视为重复，保留首条并记录。
6. **摘要/建议**：LLM 被要求只能引用已入选项，脚本检查建议中引用的编号是否存在。

## 五、报告结构（脚本模板固定）

1. 本期摘要（LLM，基于入选项）
2. ESG 政策与标准动态（policy / rating）
3. 行业新闻与最佳实践（industry / best_practice）
4. 客户公司动态与 ESG 影响（company）
5. 对标企业 ESG 关键行动（peer，表格）
6. ESG 建议（LLM，按 E/S/G）
7. 风险与信息缺口（脚本统计 + LLM 补充）
8. 附录：信息清单（脚本生成，与正文条目一一对应）

## 六、失败与降级

| 情况 | 处理 |
|---|---|
| 搜索引擎不可达 | 尝试第二引擎；均失败则报错退出，提示检查网络，不生成报告 |
| LLM 返回非 JSON | 重试 2 次；仍失败则报错退出 |
| 某检索词 0 结果 | 跳过并在 `meta.queries` 中记录 |
| 窗口内条目为 0 | 仍渲染报告，正文注明"本周期未采集到符合条件的公开信息"，不虚构 |
| 页面正文抓取失败 | 使用搜索摘要作为素材，并标注 `text_source=snippet` |

## 七、与纯提示词版的对比实验

同一问题分别调用 `esg-monthly-report`（纯提示词）与 `esg-monthly-report-scripted`，固定 `--as-of`，对比：条目数量、来源可追溯率、日期/分类错误数、结构完整度、耗时、Token 消耗。结论记录到 `week16/对比.md`。
