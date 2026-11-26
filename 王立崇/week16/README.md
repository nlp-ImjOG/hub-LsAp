# Week16 作业：ESG 月报 Skill 与 ESG 投标监控 Skill

本周完成两件事：

1. **作业1**：构建两个可自主联网搜索、自主筛选、自动成稿的 **Skill**
   - 案例1 `ESG月报`：以中国神华为例，汇总过去一个月 ESG 政策/标准动态、所属行业新闻与最佳实践、客户与对标企业的关键行动，产出 ESG 月报。
   - 案例2 `ESG投标信息汇总`：汇总过去 2 年 ESG / 可持续发展 / 双碳相关中标信息并做热点与金额分布分析；同时监控每天新增招标信息并推送。
2. **作业2**：把两个 Skill 里「搜索互联网 + 内容总结」的部分沉淀为**高代码确定性脚本**，并对比「有确定性脚本的 Skill」与「没有任何脚本、纯靠模型自由发挥的 Skill」的效果差异。

## 目录结构

```
week16/
├── README.md                          # 本文件
├── scripts/                           # 沉淀的确定性脚本库（作业2 核心）
│   ├── config.py                      # LLM + 搜索 API + 推送配置
│   ├── web_search.py                  # 互联网搜索（Serper/博查/DDG/Bing 多后端降级）
│   ├── web_fetch.py                   # 网页抓取 + 正文抽取
│   ├── llm_summarize.py               # 结构化摘要 / 相关性筛选 / 去重
│   ├── report_writer.py               # Markdown 报告生成
│   ├── demo_data.py                   # 离线演示数据（无网络/无 Key 也能跑通）
│   ├── esg_monthly_report.py          # 案例1 编排脚本
│   ├── esg_bid_monitor.py             # 案例2 编排脚本
│   └── requirements.txt
├── 作业1/
│   ├── 案例1-ESG月报/
│   │   ├── SKILL.md                   # 案例1 Skill（Claude Code 格式）
│   │   └── output/中国神华ESG月报_2026-11.md
│   └── 案例2-ESG投标/
│       ├── SKILL.md                   # 案例2 Skill
│       └── output/
│           ├── ESG中标信息汇总_2024-2026.md
│           └── 每日招标推送_2026-11-27.md
└── 作业2/
    ├── 对比报告.md                    # 有脚本 vs 无脚本 的效果对比
    └── 对比实验.py                    # 可复现的对比实验（计时/计 token/打分）
```

## 快速开始

```bash
# 1. 安装依赖
cd week16
pip install -r scripts/requirements.txt

# 2. 配置（可选，全部留空也能用离线 demo 跑通流程）
cp scripts/.env.example scripts/.env   # 按需填写

# 3. 离线演示（无需网络、无需 API Key，跑通全流程并输出示例报告）
python scripts/esg_monthly_report.py --demo --out 作业1/案例1-ESG月报/output
python scripts/esg_bid_monitor.py      --demo --out 作业1/案例2-ESG投标/output

# 4. 真实联网运行（需配置搜索后端 + LLM Key，见 scripts/.env.example）
python scripts/esg_monthly_report.py --company 中国神华 --days 30 --out 作业1/案例1-ESG月报/output
python scripts/esg_bid_monitor.py --mode history --years 2 --out 作业1/案例2-ESG投标/output
python scripts/esg_bid_monitor.py --mode daily --push --out 作业1/案例2-ESG投标/output
```

> 说明：`--demo` 模式会把「搜索」替换为内置演示数据、把「LLM 摘要」替换为规则抽取，
> 用于**离线验证整条确定性流水线**；真实模式则调用搜索后端 + LLM 拿到实时信息。

## 关于本次会话的联网说明

构建时当前会话处于受限权限模式，`WebSearch` / `WebFetch` 及带网络的 `Bash` 均被拦截，
**无法在此会话内实时检索互联网**。因此：

- 脚本已经内置了完整的联网搜索能力（`web_search.py` 支持 Serper / 博查 / DuckDuckGo / Bing 四后端降级），
  你在本地配置好搜索后端后即可拿到真实、当月的数据；
- `output/` 里的示例报告为**演示稿**，基于模型训练时间之前的公开信息整理，并在文首明确标注，
  运行 Skill/脚本后可自动刷新为最新一个月数据。

如需我在后续会话直接联网生成真实报告，请切换到允许网络访问的权限模式
（例如 `Shift+Tab` 切换为 acceptEdits / bypassPermissions，或放行 WebSearch / Bash 网络命令）。
