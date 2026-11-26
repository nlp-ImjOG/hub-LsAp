# 公告与统计口径

入口为中国政府采购网 https://www.ccgp.gov.cn/ ，全国公共资源交易平台 https://www.ggzy.gov.cn/ ，中国招标投标公共服务平台 https://www.cebpubservice.com/ ，各省平台及采购人原站。按季度和主题搜索ESG/环境社会治理、可持续发展报告/鉴证、碳盘查/核算/核查、碳足迹、碳达峰规划、节能诊断/能碳平台，分别查中标、成交、招标、竞争性磋商、更正和终止。ESG编号、材料设备和通用政策条款的误匹配记入排除日志。

## 历史JSON

start和end为YYYY-MM-DD，表示[start,end)北京时间自然日。title、coverage、insights描述样本。records每项必需project_id、lot、title、buyer、region、category、published_at、supplier、url、verification、status。status为awarded。amount为原始数字字符串或null，unit为元/万元/亿元，currency默认CNY，amount_type为total。金额不适合统计时置null并记录note。采购人+项目编号+标包去重，重招轮次在编号中明确。

更正由研究阶段核验后，仅将有效结果传给统计脚本。project_totals可选，键为project_id，值为人民币元字符串，完整纳入一个项目全部标包时用它对账。

## 日报JSON

title、as_of、window_start、coverage、records。时间字段为带+08:00的ISO时间。每条包含project_id、lot、buyer、title、url、published_at、deadline、acquisition_start、acquisition_end、version、status、budget_text、scope、qualification、remarks。deadline/acquisition_end可null，缺失时判待核验。获取开始时间已知时记录acquisition_start，用于识别尚未开放。version为真实公告更新时间或内容哈希，更正时变化。status取open/cancelled。资格需保留中小企业、联合体及特定要求。

更正公告保存updated_at（带时区的实际更新时间），日报按updated_at优先判断是否落入检索窗口，原published_at保留首发时间。状态文件记录已在本地HTML展示的项目版本，在HTML写入成功后原子更新。独占锁避免同时使用同一状态。重复版本不再展示，重新回放用独立state。正式推送另需发送回执及幂等键。

## 报告口径

项目与标包分别计数，联合体每包计一次。金额缺失计入缺失率。图表从records计算，桶为[0,50万)、[50万,100万)、[100万,300万)、[300万,+∞)。零样本正常输出。样本量、来源偏向、多年服务总价、单个项目多包集中应显著注明。报告支持读者从明细回查公告。
