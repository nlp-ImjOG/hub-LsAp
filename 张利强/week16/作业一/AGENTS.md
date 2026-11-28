# AGENTS.md

## 仓库性质

- Python 课程作业提交仓库：每位学生一个目录，每周一个子目录；根目录没有构建、测试、lint、CI 配置。
- 当前分支 `main`，提交信息格式：`张利强 weekNN <主题> 作业`。

## 硬性规则（来自根 README.md）

- 只在自己名下的作业目录内创建/修改文件。本会话范围为 `张利强/week16/作业一/`，不要读取或修改其他同学、老师、其他周次的文件。
- 文件名/目录名不得包含空格或 `.`（扩展名除外），用 `-`、`_` 代替。
- 根目录的 `å¼ å©å¼º/` 是 `张利强/` 的错误编码副本，忽略它，禁止在其中写文件。
- 仓库没有 `.gitignore`：不要提交 `.DS_Store`、`.idea/`、`__pycache__/`、`.mypy_cache/`、`.pytest_cache/`。
- 无依赖清单；需要第三方库时，在作业目录内添加 `requirements.txt` 并说明。

## 运行环境

- Python 基线为 **3.12**。系统没有 `python3.12` 命令，系统 `python3` 是 3.13.4，不要用它。
- 使用已存在的 conda 环境 `py312`（`/opt/anaconda3/envs/py312/bin/python`，Python 3.12.14）：
  `conda run -n py312 python <脚本>`，或先 `conda activate py312`。
- 安装依赖用 `conda run -n py312 pip install <包>`，并在作业目录的 `requirements.txt` 中记录。

## 当前作业：week16/作业一

以 `张利强/week16/作业一/README.md` 为唯一需求来源，实现两个 OpenCode Skill：

- 目录约定：设计/计划放 `skill/esg-skills-design/`，两个 Skill 放 `skill/esg-skills/`。
- `skill/esg-skills/esg-monthly-report/`：`SKILL.md` + `agents/{policy_search,industry_peer_search,shenhua_search,filter,writer,validator}.md` + `templates/report.md` + `scripts/`（含 `run_monthly.py`）；运行期使用 `peer_set.json`。
- `skill/esg-skills/esg-bid-monitor/`：`SKILL.md` + `agents/{slice_search,extract,dedupe,daily_push,writer}.md` + `templates/` + `scripts/`（含 `chart.py`、`daily_window.py`）+ `buffer/daily_buffer.json`。

容易违反的业务约束：

- 检索接口固定为 `https://api.deepseek.com/v1/tools/search`，需 API Key；只检索、只输出简体中文。
- 每条事实必须带 `[来源: URL]`；检索不到就写 `暂无数据`，禁止用模型知识补全。
- `target_month` 由调度器以 `YYYY-MM` 注入；“一个月”指自然月，不是“最近 30 天”。
- 招投标金额统一为“万元”，不明确则 `null`；字段固定为 `project_name`、`buyer`、`winner`、`amount_wan`、`publish_date`、`category`、`source_url`；日期用 `YYYY-MM-DD`；时区 `Asia/Shanghai`。
- 每日推送窗口固定为 `[昨天 00:00, 今天 00:00]`，结果追加写入 `daily_buffer.json`。
- 图表分桶：`≤50万`、`50-100万`、`100-200万`、`200-500万`、`>500万`；有效记录少于 5 条只出柱状图并注明“样本量较小”，0 条不出图。
- 图表脚本依赖 `pandas`、`matplotlib`。

## 验证

- 没有测试框架或运行器；直接 `conda run -n py312 python <脚本>` 执行，检查作业目录下生成的 Markdown/PNG/JSON 是否符合上述约束。
