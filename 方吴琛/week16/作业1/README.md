# 作业1:ESG Skill 构建

> 构建两个 Skill/Agent,可自主检索互联网、筛选信息、形成报告。
> 交付物位于本目录。

## 目录结构
```
作业1/
├── README.md                         # 本文件
├── esg-monthly-report/               # 案例一:ESG 月报
│   ├── SKILL.md                      # Skill 主文件(含 frontmatter + 工作流)
│   ├── report-template.md            # 报告模板(可直接套用)
│   └── reference/
│       ├── sources.md                # ESG 权威信源清单(A/B/C 级)
│       └── framework.md              # ESG 框架与对标维度速查
└── esg-bidding-monitor/              # 案例二:ESG 投标信息汇总
    ├── SKILL.md                      # Skill 主文件(汇总 + 监控双模式)
    ├── report-template.md            # 汇总报告模板
    └── reference/
        ├── platforms.md              # 招标平台清单与使用规则
        └── keywords.md               # 关键词矩阵 + 分类体系 + 打分
```

## 案例一:ESG 月报 Skill
- **触发**:"生成 ESG 月报""客户 ESG 月度报告"等。
- **参数化输入**:客户公司、所属行业(必填);对标企业(默认中国神华)、报告期间、重点关切(选填)。
- **三大板块**:
  1. ESG 政策、评级、标准动态
  2. 行业 ESG 新闻与最佳实践
  3. 客户公司动态影响 + 对标(中国神华)+ 行动建议
- **质量机制**:信源 A/B/C 分级、关键数据交叉验证、来源链接全程留存、8 项自检清单。
- **产出**:Markdown 月报,文件名 `ESG月报_<客户公司>_<年月>.md`。

## 案例二:ESG 投标信息汇总 Skill
- **触发**:"ESG 招投标汇总""监控 ESG 招标""每日招标推送"等。
- **双模式**:
  - **汇总模式**:过去 2 年 ESG/可持续发展/双碳中标汇总,分析热点招标与金额分布。
  - **监控模式**:每日检索新增 ESG 招标,去重、打分筛选、生成《每日推送》;可用 CronCreate 或 `/loop` 定时驱动。
- **结构化**:每条提取 8 字段,按 10 类 taxonomy 分类,金额区间/地区/时间/中标企业多维分析。
- **产出**:汇总报告 + 项目清单 CSV;每日推送 Markdown。

## 安装与使用
两个 Skill 包均为标准 Claude Code skill 结构。安装方式:

```bash
# 复制到项目级 skill 目录(推荐)
cp -r esg-monthly-report  .claude/skills/
cp -r esg-bidding-monitor .claude/skills/

# 或用户级(全局可用)
cp -r esg-monthly-report  ~/.claude/skills/
cp -r esg-bidding-monitor ~/.claude/skills/
```

安装后:
- 自然语言触发:对 Claude 说"帮我为陕西煤业生成 ESG 月报""汇总过去 2 年 ESG 中标"。
- Skill 会自动询问缺失参数,然后用 WebSearch/WebFetch 检索、筛选、套模板、落盘报告。

## 设计要点(为什么报告效果好)
1. **检索有计划**:把任务拆成「板块 × 关键词组 × 中英文」多轮检索,覆盖全面。
2. **信源分级 + 交叉验证**:政策/数据类断言至少 2 个独立来源,剔除营销稿。
3. **结构化抽取**:招投标强制 8 字段、ESG 对标强制 8 维表格,报告可直接交付。
4. **来源可追溯**:每个事实带链接,附录按板块汇总,可审计。
5. **质量自检清单**:输出前逐项核对,杜绝空板块与未核实结论。
6. **模板与参考分离**:SKILL.md 保持精简,深度资料放 `reference/`,按需加载。

