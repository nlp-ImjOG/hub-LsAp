"""Record isolated model runs for the no-script and script-assisted ESG experiment."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT.parent / 'skills/esg-monthly-report/scripts'
sys.path.insert(0, str(SCRIPTS))
from model_client import invoke
from research import SUMMARY_SCHEMA, build_report, clean, save, search, collect, summary_prompt, validate_summary
from render_report import render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['fixed', 'live'])
    parser.add_argument('variant', choices=['A', 'B'])
    parser.add_argument('--run', default='1')
    args = parser.parse_args()
    config = json.loads((ROOT / 'task.json').read_text(encoding='utf-8'))
    name = 'esg-monthly-no-scripts' if args.variant == 'A' else 'esg-monthly-scripted'
    variant = ROOT / 'variants' / args.variant / name
    folder = ROOT / 'runs' / args.mode / f'{args.variant}-{args.run}'
    folder.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    rules = (variant / 'references/business-rules.md').read_text(encoding='utf-8')
    instruction = (variant / 'SKILL.md').read_text(encoding='utf-8')
    save(folder / 'task.json', config)
    result = {'mode': args.mode, 'variant': args.variant, 'run': args.run, 'completed': False}
    try:
        if args.mode == 'fixed':
            corpus_path = ROOT / 'fixed-materials/benchmark-corpus.json'
            payload = corpus_path.read_bytes()
            corpus = json.loads(payload)
            result['input_sha256'] = hashlib.sha256(payload).hexdigest()
            save(folder / 'raw-corpus.json', corpus)
            if args.variant == 'B':
                prepared = clean(corpus, config)
                prompt = summary_prompt(prepared, config, rules)
            else:
                prepared = corpus
                prompt = summary_prompt(corpus, config, rules)
                prompt += '\n自行判定重复链接与时间归属，对重复材料写outside并给出依据。'
            answer, metrics = invoke(instruction + '\n' + prompt, SUMMARY_SCHEMA, folder / 'model', timeout=420)
            if args.variant == 'B':
                validate_summary(answer, prepared)
            save(folder / 'prepared-corpus.json', prepared)
        elif args.variant == 'B':
            config['search_log_directory'] = str((folder / 'search-model').resolve())
            found = search(config)
            save(folder / 'search.json', found)
            corpus = collect(found)
            save(folder / 'raw-corpus.json', corpus)
            prepared = clean(corpus, config)
            save(folder / 'prepared-corpus.json', prepared)
            if not prepared['documents']:
                raise RuntimeError('No readable evidence in live search')
            answer, metrics = invoke(instruction + '\n' + summary_prompt(prepared, config, rules), SUMMARY_SCHEMA,
                                     folder / 'model', timeout=420)
            validate_summary(answer, prepared)
        else:
            schema = json.loads(json.dumps(SUMMARY_SCHEMA))
            schema['properties']['sources'] = {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                'properties': {k: {'type': 'string'} for k in ['id', 'title', 'url', 'published_at', 'text']},
                'required': ['id', 'title', 'url', 'published_at', 'text']}}
            schema['properties']['queries'] = {'type': 'array', 'items': {'type': 'string'}}
            schema['required'] += ['sources', 'queries']
            prompt = (instruction + '\n规范\n' + rules + '\n任务\n' + json.dumps(config, ensure_ascii=False)
                      + '\n使用真实网页搜索与读取工具完成任务。可以定向补搜，研究范围覆盖任务登记的四条查询，最多12个来源。'
                      '禁止执行命令、调用业务脚本或写文件。输出中文结构化报告。items每项引用sources中的id，'
                      'decision取included/background/pending/outside。text保存所采用的证据短摘录，日期未知则为空字符串。'
                      'queries保存真实执行的查询。保留负面信息、历史日期与整改证据缺口。')
            answer, metrics = invoke(prompt, schema, folder / 'model', live_search=True, timeout=720)
            prepared = {'documents': [dict(s, fetch_status='model_read', verification='模型工具读取，见事件日志') for s in answer['sources']],
                        'pending': [], 'duplicates': [], 'queries': answer['queries']}
            save(folder / 'prepared-corpus.json', prepared)
        save(folder / 'summary.json', answer)
        report = build_report(answer, prepared, config)
        report['subtitle'] = args.mode + ' · ' + args.variant + '版 · 同一公共展示层'
        save(folder / 'report.json', report)
        render(report, folder / 'report.html')
        result.update(completed=True, model_metrics=metrics, source_count=len(prepared['documents']),
                      duplicate_count=len(prepared.get('duplicates', [])), pending_count=len(prepared.get('pending', [])))
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        result['elapsed_seconds'] = round(time.monotonic()-started, 3)
        save(folder / 'run.json', result)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
