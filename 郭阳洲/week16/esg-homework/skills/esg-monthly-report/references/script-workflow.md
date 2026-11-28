# 脚本化研究与复演

scripts/research.py使用Python标准库完成公开HTML读取、正文抽取、URL和正文去重、日期初步识别、来源校验及排版。scripts/model_client.py通过本机Codex CLI调用已登录账户，负责搜索工具编排与模型总结。实际模型能力、联网权限和账号配额以运行环境为准。

## 输入

任务JSON包含company、month、cutoff，month为YYYY-MM，cutoff为YYYY-MM-DD。可指定queries数组、search_provider及per_query。默认search_provider为codex；bing使用公开RSS搜索网页，结果相关性须按实际输出核验。

完整调用为 `python <skill路径>/scripts/research.py run <任务JSON> <输出目录>`。程序保存查询、候选链接、原始正文、规范化材料、摘要、HTML和模型调用事件。正文中未能可靠确定的发布日期保留空值，交由后续核验。

分阶段支持search、collect、clean、summarize。后三者通过 `--input <上一步JSON>`读取数据。例如固定材料运行 `python <skill路径>/scripts/research.py summarize <任务JSON> <输出目录> --input <正文材料JSON>`。

## 行为与限制

- 模型客户端优先使用CODEX_APP_RUNTIME_CLI_PATH指定的本地程序，其次查找已安装的codex可执行文件。首次运行用codex login建立本机授权，调用过程不读取或打印登录令牌。
- CLI使用只读执行沙箱，正文总结关闭搜索，检索阶段开启原生搜索。以当次命令参数运行，模型/工具事件和可获得的用量写入日志。
- 默认每次总结超时300秒，实验运行可登记更长超时。失败时保留阶段文件与错误，使用独立运行目录重试。
- HTML最多读取3MB，单页超时20秒，最多4页并发。PDF、图片正文、登录页、动态内容或访问拒绝需要其他可用阅读方式继续核验。程序返回待核验，报告需披露未成功读取的资料。
- 日期初步识别只采用显式元数据或可见发布标签。业务结论仍需核对主体、时间、事件阶段和适用性。source_id与结构检查通过不等同于事实已经全部正确。
- 已准备固定材料的实验可复演；完整联网结果会随工具与网站变化。程序化总结依赖模型，具有生成波动。

## 实验版本

作业二A版在研究决策阶段采用纯指令，B版调用上述脚本。统一展示层用于阅读两版结果，测量程序负责记录输入、输出和耗时，单独声明其作用。业务规则相同，输入和代码摘要值登记后再比较。
