---
name: esg-monthly-report
description: 生成中国神华 ESG 月度简报：按自然月检索国内 ESG 政策、行业与对标企业动态、神华自身动态，过滤去重、逐条标注来源并校验后输出 Markdown（可选 PDF）。当用户提到“ESG 月报”“ESG 月度简报”“中国神华 ESG”“ESG 政策汇总”“双碳月报”，或要求按某个自然月汇总 ESG 政策/行业动态时使用；即使用户没说出“月报”，只要任务是按自然月汇总 ESG 信息，也应使用。
---

# ESG 月报生成（中国神华版）

本 Skill 把月报拆成“搜索 → 过滤 → 撰写 → 校验”四个阶段，每个阶段读取 `agents/` 下对应的提示词。拆分的目的是让检索结果先落成结构化记录，再进入写作，避免模型在写作时用参数化知识补全未检索到的内容。

## 何时使用

用户需要按**自然月**汇总中国神华相关 ESG 信息时使用，例如：

- “生成 2026 年 11 月的 ESG 月报”
- “汇总上个月的双碳政策和行业动态”
- “中国神华这个月的 ESG 有什么值得关注”
- “做一份 ESG 月度简报，对标几家同行”

不适用于：单篇新闻解读、实时舆情、非 ESG 主题的月报。

## 输入

- `target_month`（必填）：`YYYY-MM`。用户没给就**先问**，不要用“最近一个月”代替。
- `include_peers`（可选，默认 `false`）：`true` 时重新圈定对标企业并覆盖 `peer_set.json`。

## 工作流

### 1. 确认自然月

把 `target_month` 转成闭区间 `[YYYY-MM-01, YYYY-MM-最后一天]`，后续所有检索和校验都用这个区间。不要自行扩展成“最近 30 天”。

### 2. 并行检索

读取并执行以下三个提示词；它们可以并行：

- `agents/policy_search.md`：政策、标准、监管口径。
- `agents/industry_peer_search.md`：行业动态与对标企业；需要 `peer_set.json`。
- `agents/shenhua_search.md`：中国神华自身动态。

三个 Agent 都调用同一个检索脚本，示例：

```bash
conda run -n py312 python scripts/search_deepseek.py \
  --query "ESG 政策 2026 年 11 月" \
  --start 2026-11-01 --end 2026-11-30 \
  --site gov.cn --limit 20 \
  --output /tmp/esg-policy.json
```

脚本从环境变量 `DEEPSEEK_API_KEY` 读取密钥，请求 `https://api.deepseek.com/v1/tools/search`。没有密钥时脚本会退出并提示，此时停止检索并向用户说明，不要改用模型记忆编造结果。

### 3. 过滤与去重

读取 `agents/filter.md`，把三路结果合并后：

- 丢弃没有 URL、没有标题、没有可验证发布日期的记录。
- 只保留发布日期落在目标自然月内的记录。
- 按规范化 URL 去重（去掉 `utm_*`、`spm` 等追踪参数和末尾斜杠）。
- 输出结构化记录，并附上 `kept` / `dropped` 计数。

### 4. 撰写

读取 `agents/writer.md` 和 `templates/report.md`，生成 800–1200 字简体中文简报。每个事实陈述后面必须带 `[来源: URL]`；某一节没有检索结果时写 `暂无数据`，不要用常识补齐。

### 5. 校验

读取 `agents/validator.md`，并运行：

```bash
conda run -n py312 python scripts/validate_report.py --file report.md --month 2026-11
```

校验规则：除标题、空行、分隔线、代码块、引用块外，每个非空行必须含 `[来源: http(s)://...]` 或整行为 `暂无数据`；剥离 URL 后出现的 `YYYY-MM-DD`、`YYYY/MM/DD`、`YYYY年M月D日`、`YYYY年M月` 必须落在目标月内；空文件或纯空白文件直接判失败。校验不通过时回到撰写阶段修正，最多两轮。

### 6. 输出

先在对话中输出 Markdown 全文。用户需要 PDF 时再运行：

```bash
conda run -n py312 python scripts/md_to_pdf.py --input report.md --output report.pdf
```

PDF 是可选产物；没有 PDF 工具链时，Markdown 仍然是完整交付。若用户要求“自动附 PDF”，在 Markdown 定稿后立即调用上面的命令；PDF 失败只记录错误，不回滚 Markdown。

## 硬规则

- **句句有源**：每条事实陈述必须带 `[来源: URL]`，URL 必须来自实际检索结果。
- **零幻觉**：检索不到就写 `暂无数据`；禁止用模型参数化知识补全政策、金额、日期、企业动态。
- **时间硬约束**：只使用目标自然月内的记录；不要用“最近”“近期”模糊表述代替具体日期。
- **语言**：只检索、只输出简体中文。
- **来源优先级**：`gov.cn`、`ndrc.gov.cn`、`mee.gov.cn`、`sasac.gov.cn`、`csrc.gov.cn`、`sse.com.cn`、`szse.cn`、`cninfo.com.cn`、港交所披露易优先。

## 失败处理

- 缺少 `DEEPSEEK_API_KEY`：停止，说明需要配置密钥；不要伪造检索结果。
- 某一路检索为空：该节写 `暂无数据`，其余章节继续。
- 校验连续两轮不通过：输出带违规标记的草稿，明确告诉用户哪些行需要人工补来源。
- `peer_set.json` 损坏：先备份为 `peer_set.json.bak`，再按空列表重建。

## 定时触发

OpenCode 没有内置调度器。推荐以手动触发为主：用户说“生成某月 ESG 月报”时调用本 Skill。需要每月自动跑时，用 `scripts/run_monthly.py` 把“第 1 个工作日”和 `target_month` 的计算固定下来，再让 cron 调用：

```cron
# 每个工作日 09:00 尝试一次；只有本月第 1 个工作日才继续
# 把 <作业目录> 替换成绝对路径
0 9 * * 1-5 cd <作业目录> && TZ=Asia/Shanghai sh -c 'MONTH=$(conda run -n py312 python skill/esg-skills/esg-monthly-report/scripts/run_monthly.py) && opencode run "使用 @esg-monthly-report 生成 ${MONTH} 的中国神华 ESG 月报（target_month=${MONTH}）"' >> /tmp/esg-monthly.log 2>&1
```

- `run_monthly.py` 命中本月第 1 个工作日时输出上个月 `YYYY-MM` 并退出 0；否则退出 3，`&&` 会阻止后续 `opencode run`。
- 工作日默认按周一至周五计算。中国法定节假日用 `--holiday YYYY-MM-DD` 显式传入（可重复），节假日自动顺延到下一个工作日；不传就按普通工作日处理。
- `TZ=Asia/Shanghai` 固定触发时区；`target_month` 由脚本注入，不让模型在非交互运行中自行推断“上个月”。

macOS 也可以用 launchd 的 `StartCalendarInterval` 每天 09:00 执行同一段 `sh -c` 命令，由 `run_monthly.py` 的退出码决定是否真正生成。

## 依赖

- Python 3.12，`requests`、`reportlab`。
- `DEEPSEEK_API_KEY`（检索）。
- 建议模型：Qwen3.8-flash；不可用时使用当前会话模型，但不要降低引用与零幻觉要求。
