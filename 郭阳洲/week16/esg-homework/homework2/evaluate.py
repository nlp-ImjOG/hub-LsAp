"""Aggregate recorded A/B outputs and a separately saved factual audit."""
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'skills/esg-monthly-report/scripts'))
from research import save
from render_report import render


def run_metrics(folder):
    run = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    response = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
    corpus = json.loads((folder / 'prepared-corpus.json').read_text(encoding='utf-8'))
    ids = {d['id'] for d in corpus['documents'] + corpus.get('pending', []) + corpus.get('duplicates', [])}
    metrics = json.loads((folder / 'model/metrics.json').read_text(encoding='utf-8'))
    usage = metrics.get('usage') or {}
    events = [json.loads(line) for line in (folder / 'model/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    tool_items = [e['item'] for e in events if e.get('type') == 'item.completed' and e.get('item', {}).get('type') in ('command_execution', 'mcp_tool_call', 'web_search')]
    recovered = (folder / 'recovery.json').exists()
    return {'run': folder.name, 'completed': run['completed'] or recovered, 'first_attempt_completed': run['completed'],
            'recovered': recovered, 'elapsed_seconds': run['elapsed_seconds'],
            'input_sha256': run.get('input_sha256'), 'source_count': len(corpus['documents']),
            'item_count': len(response['items']), 'invalid_ids': [i['source_id'] for i in response['items'] if i['source_id'] not in ids],
            'tool_calls': len(tool_items), 'input_tokens': usage.get('input_tokens'),
            'cached_input_tokens': usage.get('cached_input_tokens'), 'output_tokens': usage.get('output_tokens'),
            'duplicate_ids': [d['id'] for d in corpus.get('duplicates', [])]}


def main():
    registration = json.loads((ROOT / 'experiment-registration.json').read_text(encoding='utf-8'))
    corpus_hash = hashlib.sha256((ROOT / 'fixed-materials/benchmark-corpus.json').read_bytes()).hexdigest()
    runs = [run_metrics(ROOT / 'runs/fixed' / name) for name in ['A-1', 'B-1', 'B-2', 'A-2']]
    assert all(r['input_sha256'] == corpus_hash for r in runs)
    audit = json.loads((ROOT / 'manual-audit.json').read_text(encoding='utf-8'))
    for run in runs:
        scores = audit['runs'][run['run']]['checks']
        run['factual_audit_score'] = sum(c['score'] for c in scores)
        run['factual_audit_max'] = len(scores)
    aggregate = {}
    for variant in ('A', 'B'):
        group = [r for r in runs if r['run'].startswith(variant)]
        aggregate[variant] = {'runs': len(group), 'mean_seconds': round(mean(r['elapsed_seconds'] for r in group), 2),
                              'mean_input_tokens': round(mean(r['input_tokens'] for r in group), 1),
                              'mean_output_tokens': round(mean(r['output_tokens'] for r in group), 1),
                              'mean_audit_score': mean(r['factual_audit_score'] for r in group)}
    data = {'experiment': registration, 'fixed_runs': runs, 'aggregate': aggregate,
            'audit': audit, 'cost': None, 'note': 'CLI用量为其实际报告值；费用未取得，人工评价为本研究者复核。'}
    save(ROOT / 'comparison-metrics.json', data)
    table = [[r['run'], '恢复后完成' if r['recovered'] else '首次完成', str(r['source_count']), str(r['item_count']), str(r['invalid_ids']),
              f"{r['factual_audit_score']}/{r['factual_audit_max']}", str(r['elapsed_seconds']),
              str(r['input_tokens']), str(r['cached_input_tokens']), str(r['output_tokens'])] for r in runs]
    audit_rows = []
    for name, result in audit['runs'].items():
        for check in result['checks']:
            audit_rows.append([name, check['id'], str(check['score']), check['evidence']])
    report = {'title': '作业二 · ESG Skill脚本化对照实验', 'subtitle': '2026年11月26日 · 共同业务规范 esg-research-1.0',
              'summary': audit['conclusion'], 'kpis': [{'label': '固定材料独立运行', 'value': '4次'},
                  {'label': '独立原文 / 重复链接', 'value': '6 / 1'}, {'label': '针对性回归检查', 'value': '14项'}],
              'sections': [
                  {'heading': '实验范围与方法', 'paragraphs': [
                      '任务为中国神华2026年10月ESG月报，资料截止2026年11月25日，实际检索与实验于11月26日进行。A版在研究决策阶段采用模型指令，B版使用程序检索、正文提取、去重、校验和模型总结。',
                      '先完成一对联网探索性试跑，再以7条公开网页材料（6篇独立原文和1个重复链接）按A1、B1、B2、A2顺序独立运行。四次固定实验原始输入摘要值一致。两版的阅读展示采用相同渲染层，展示层不计为研究处理差异。',
                      '使用本机已登录的Codex CLI。CLI默认模型标识未在接口输出中暴露，四次使用相同可执行程序和命令配置。正文总结关闭搜索，程序审计检查实际工具事件。']},
                  {'heading': '脚本实现', 'table': {'headers': ['文件', '已实现职责'], 'rows': [
                      ['research.py', '原生搜索工具编排/可选公开RSS、HTML正文读取、链接与正文去重、日期初筛、摘要校验、报告生成'],
                      ['model_client.py', '通过Codex CLI请求模型，保存提示、响应、事件、用量与脱敏错误日志'],
                      ['analyze.py', '修复跨采购人同编号集中度与获取开始日期缺失判断，兼容既有数据'],
                      ['benchmark.py / evaluate.py', '实验登记、原始输入保留、运行计时、实际输出与事实复核汇总']]}},
                  {'heading': '固定材料实测结果', 'paragraphs': [
                      '耗时单位为秒，包含CLI连接与模型运行。B1保留首次校验失败，复用已保存模型输出恢复，表中耗时为首次运行至失败，不含代码编辑和恢复时间。A输入7份正文，B输入6份正文及1条去重记录。input/output tokens为CLI报告累计值，缓存输入单列，费用未取得。',
                      '事实评分采用8项预先登记的核对项，满足1分、部分满足0.5分、错误或缺失0分。评价由本研究者对照原文完成，尚未开展独立盲评。'],
                   'table': {'headers': ['运行', '运行状态', '正文条目', '返回条目', '非法来源ID', '事实复核', '耗时秒', '输入tokens', '缓存输入', '输出tokens'], 'rows': table}},
                  {'heading': '联网试跑与失败恢复', 'paragraphs': audit['live_findings']},
                  {'heading': '事实逐项核对', 'table': {'headers': ['运行', '核对项', '得分', '输出依据与复核判断'], 'rows': audit_rows}},
                  {'heading': '脚本修复与兼容验证', 'paragraphs': [
                      '合成回归用例中，不同采购人共用项目编号的最大项目金额占比，从旧脚本100%修正为50%。缺少文件获取开始时间的机会，从可新参与改为期限待核验。',
                      '首次B版联网运行发现已知待核验来源被校验器误判为未知ID。修复后允许pending/outside表达，继续禁止把未读材料确认为included。首次失败记录和复用原模型响应恢复的记录均保留。',
                      '固定B1首次运行又发现已知重复项的outside记录被误拒。修复后允许审计记录保留重复项，报告事实表继续排除重复事件，原模型输出保持原样。',
                      '14项针对性回归检查通过。以作业一真实数据复跑，44包、16项目、39包有效金额合计58,471,800元以及金额分布与原数据对账一致。']},
                  {'heading': '结论及适用条件', 'paragraphs': audit['interpretation']},
                  {'heading': '在Codex调用与复演', 'table': {'headers': ['用途', '调用内容'], 'rows': [
                      ['无脚本版', '$esg-monthly-no-scripts 为中国神华生成2026年10月ESG月报'],
                      ['脚本版', '$esg-monthly-scripted 为中国神华生成2026年10月ESG月报'],
                      ['固定材料新增A运行', 'python "' + str(ROOT / 'benchmark.py') + '" fixed A --run new-A'],
                      ['固定材料新增B运行', 'python "' + str(ROOT / 'benchmark.py') + '" fixed B --run new-B'],
                      ['回归检查', 'python "' + str(ROOT / 'test_regressions.py') + '"']]}},
                  {'heading': '限制与复演', 'paragraphs': [
                      '固定材料只有6篇独立原文，每版重复2次，结果只反映本次样本。搜索渠道、材料可读性及连接回退均可能影响全流程结果。任务信息截止日与实际访问日之间的网页变化无法完整还原。',
                      '实验提示注入了Skill入口、共同业务规范和任务，入口引用的月报研究细则未单独展开。两版均采用相同共同规范，本次主要评价材料处理效果，完整细则遵循能力需另行验证。',
                      '脚本正文读取当前支持公开HTML。PDF、动态页面及图片需其他阅读能力，脚本将其保留为待核验。模型摘要具有生成波动，结构校验不能替代事实核验。B版并非全部确定性。',
                      '运行 python test_regressions.py 复验回归场景。使用 benchmark.py fixed A/B --run <新编号> 可在保持材料文件不变时新增独立运行，联网实验使用live模式。执行需要本机Codex登录及网络权限。查看experiment-registration.json、audit-criteria.json、comparison-metrics.json和各run目录复核配置、输入摘要、模型结果及用量。']}]}
    save(ROOT / 'comparison-report.json', report)
    render(report, ROOT / 'comparison-report.html')
    print(json.dumps(aggregate, ensure_ascii=False))


if __name__ == '__main__':
    main()
