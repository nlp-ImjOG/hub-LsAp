# 研究规范

起点为公司官网与交易所公告、生态环境部、财政部、国家能源局、国家矿山安全监察局及适用上市地交易所。国际规则按公司业务暴露查询制定机构。每次核对现行版本。

示例查询为「公司全称 月份 公告」「行业 月份 安全 环保」「site:mee.gov.cn 年月 碳」「评级机构 公司名 评级日期」「对标公司 月份 修复 职业健康」。结果少时去掉月份，按正文日期筛选，采用同义词并查询发布方列表。补搜事故、处罚、诉讼、劳动、安全和供应链。

证据记录id、title、url、publisher、published_at、event_date、accessed_at、verification、facts、inclusion_reason。verification取直接原文、索引正文、官方镜像、待核验。facts用简短转述和章节/页码。查询日志记录query、searched_at、purpose、result及限制。

煤电实质议题包括碳与转型、水、矿区生态、甲烷、职业健康安全、承包商、社区和关联交易。影响判断给出传导路径。产销量变化须结合活动数据与排放因子才能判断排放变化。对标比较技术阶段、组织边界、适用业务和可获得的证据。评级证据缺失时说明检索范围和缺口。存量规则跟踪需写原发布日期及当月关注理由。

## 排版JSON

顶层title、subtitle、summary、kpis、sections、sources。kpis为label/value数组。sections为heading、paragraphs、table、bars的组合。table含headers和rows，单元格是字符串或{text,url}。bars为label/value数组，需另在段落说明单位。sources含id/title/url/publisher/published_at/verification。脚本自动转义正文，内容无需HTML。
