"""Compute tender history or generate a local daily demonstration from researched JSON."""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from statistics import median

from render_report import render

SHANGHAI = timezone(timedelta(hours=8))


def amount_yuan(record):
    if record.get('amount') is None or record.get('currency', 'CNY') != 'CNY' or record.get('amount_type') != 'total':
        return None
    multiplier = {'元': 1, '万元': 10000, '亿元': 100000000}[record['unit']]
    value = Decimal(str(record['amount']).replace(',', '')) * multiplier
    if not value.is_finite() or value < 0:
        raise ValueError('Invalid award amount')
    return value


def key(record):
    return '|'.join(str(record[x]).strip() for x in ('buyer', 'project_id', 'lot'))


def money(value):
    return f'{value / Decimal(10000):,.2f}'


def history(data):
    start, end = date.fromisoformat(data['start']), date.fromisoformat(data['end'])
    if start >= end:
        raise ValueError('start must precede end')
    records = {}
    for record in data['records']:
        day = date.fromisoformat(record['published_at'][:10])
        if record['status'] != 'awarded' or not start <= day < end:
            continue
        identity = key(record)
        if identity in records and record != records[identity]:
            raise ValueError('Resolve conflicting duplicate before analysis: ' + identity)
        records[identity] = record
    rows = list(records.values())
    amounts = [amount_yuan(r) for r in rows]
    valid = [a for a in amounts if a is not None]
    total = sum(valid, Decimal(0))
    projects = {(r['buyer'], r['project_id']) for r in rows}
    project_amounts = defaultdict(Decimal)
    for record, amount in zip(rows, amounts):
        if amount is not None:
            project_amounts[record['project_id']] += amount
    for project, expected in data.get('project_totals', {}).items():
        if project_amounts[project] != Decimal(expected):
            raise ValueError('Project amount reconciliation failed: ' + project)
    buckets = Counter({'低于50万元': 0, '50万至不足100万元': 0, '100万至不足300万元': 0, '300万元及以上': 0})
    for value in valid:
        bucket = next(label for limit, label in [(500000, '低于50万元'), (1000000, '50万至不足100万元'), (3000000, '100万至不足300万元'), (Decimal('Infinity'), '300万元及以上')] if value < limit)
        buckets[bucket] += 1
    sections = [{'heading': '样本结论与业务判断', 'paragraphs': data.get('insights', [])},
                {'heading': '成交金额分布', 'paragraphs': ['单位为标包数，桶为左闭右开。金额为合同总价，多年服务未年化。'], 'bars': [{'label': k, 'value': v} for k, v in buckets.items()]},
                {'heading': '主题与地域', 'table': {'headers': ['维度', '类别', '标包数', '金额合计（万元）'], 'rows': []}}]
    for field, label in [('category', '主题'), ('region', '采购人地区')]:
        groups = defaultdict(list)
        for record in rows:
            groups[record[field]].append(record)
        for group, entries in sorted(groups.items()):
            subtotal = sum((amount_yuan(r) or Decimal(0) for r in entries), Decimal(0))
            sections[-1]['table']['rows'].append([label, group, str(len(entries)), money(subtotal)])
    months = Counter(r['published_at'][:7] for r in rows)
    timeline = []
    current = start.replace(day=1)
    while current < end:
        month = current.strftime('%Y-%m')
        timeline.append([month, str(months[month]), '已检出' if months[month] else '本次样本未检出，市场情况待进一步检索'])
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    sections.append({'heading': '时间覆盖', 'paragraphs': ['首尾月份按统计窗口裁切。零条表示本次样本未检出。'], 'table': {'headers': ['月份', '标包数', '覆盖说明'], 'rows': timeline}})
    detail = []
    for record, amount in sorted(zip(rows, amounts), key=lambda pair: (pair[0]['published_at'], pair[0]['project_id'], str(pair[0]['lot']))):
        detail.append([record['published_at'], {'text': record['title'], 'url': record['url']}, record['project_id'] + ' / ' + str(record['lot']), record['buyer'], record['supplier'], money(amount) if amount is not None else '未披露', record['verification']])
    sections.append({'heading': '逐标包证据明细', 'table': {'headers': ['发布日期', '公告与原文', '编号 / 标包', '采购人', '中标人', '成交万元', '证据方式'], 'rows': detail}})
    concentration = max(project_amounts.values(), default=Decimal(0)) / total * 100 if total else Decimal(0)
    sections.append({'heading': '口径与覆盖限制', 'paragraphs': [data['coverage'], f'统计窗口为 {start} 至 {end}（不含结束日）。去重后{len(rows)}个标包、{len(projects)}个项目；有效人民币总价{len(valid)}条，金额缺失率{(len(rows)-len(valid))/len(rows)*100 if rows else 0:.1f}%。单一项目最高金额占比{concentration:.1f}%。样本受公开搜索索引及本次筛选影响，市场总量与市场份额需更完整的数据支持。']})
    stats = {'lots': len(rows), 'projects': len(projects), 'total_yuan': str(total), 'valid_amounts': len(valid), 'buckets': dict(buckets)}
    return {'title': data['title'], 'subtitle': '中国大陆公开公告 · 服务采购 · 真实数据演示', 'summary': f'在近两年窗口内筛选{len(projects)}个项目、{len(rows)}个标包，有效成交总价合计{money(total)}万元。以下热点与分布反映本次样本。', 'kpis': [{'label': '独立项目', 'value': len(projects)}, {'label': '去重标包', 'value': len(rows)}, {'label': '成交合计 / 万元', 'value': money(total)}, {'label': '标包中位数 / 万元', 'value': money(median(valid)) if valid else '暂无'}], 'sections': sections}, stats


def timestamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Timestamp requires an explicit timezone')
    return result.astimezone(SHANGHAI)


def daily(data, state):
    as_of, start = timestamp(data['as_of']), timestamp(data['window_start'])
    if start >= as_of:
        raise ValueError('window_start must precede as_of')
    seen = dict(state.get('seen', {}))
    groups = defaultdict(list)
    for record in data['records']:
        published = timestamp(record.get('updated_at') or record['published_at'])
        identity = key(record)
        version = str(record['version'])
        if not start <= published <= as_of or seen.get(identity) == version:
            continue
        deadline = timestamp(record['deadline']) if record.get('deadline') else None
        acquisition = timestamp(record['acquisition_end']) if record.get('acquisition_end') else None
        acquisition_start = timestamp(record['acquisition_start']) if record.get('acquisition_start') else None
        if record['status'] == 'cancelled':
            status = '撤销或终止'
        elif deadline and deadline <= as_of:
            status = '已截止'
        elif deadline is None or acquisition is None:
            status = '期限待核验'
        elif acquisition < as_of:
            status = '已获取文件者可跟进'
        elif acquisition_start and acquisition_start > as_of:
            status = '文件获取尚未开始'
        else:
            status = '可新参与（须满足资格）'
        groups[status].append(record)
        seen[identity] = version
    sections = []
    for status in ['可新参与（须满足资格）', '文件获取尚未开始', '已获取文件者可跟进', '期限待核验', '已截止', '撤销或终止']:
        entries = sorted(groups[status], key=lambda r: r.get('deadline') or '9999')
        if not entries:
            continue
        rows = [[{'text': r['title'], 'url': r['url']}, r['buyer'], r['budget_text'], r.get('acquisition_end') or '待核验', r.get('deadline') or '待核验', r['scope'], r['qualification'], r.get('remarks', '')] for r in entries]
        sections.append({'heading': status, 'table': {'headers': ['公告', '采购人', '预算', '文件获取截止', '投标截止', '内容', '资格', '跟进事项'], 'rows': rows}})
    count = sum(len(v) for v in groups.values())
    sections.append({'heading': '检索与演示口径', 'paragraphs': [data['coverage'], f'检索窗口 {start.isoformat()} 至 {as_of.isoformat()}。本次新增展示{count}条。状态文件表示本地报告已生成。']})
    return {'title': data['title'], 'subtitle': f'判断时点 {as_of.isoformat()} · 北京时间', 'summary': f'本次新增展示{count}条，可新参与{len(groups["可新参与（须满足资格）"])}条。请根据资格和文件获取要求选择项目。', 'sections': sections}, {'seen': seen, 'last_success_at': as_of.isoformat()}, {'new_records': count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['history', 'daily'])
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('--state')
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
    state_path = Path(args.state) if args.state else None
    lock_path = Path(str(state_path) + '.lock') if state_path else None
    locked = False
    try:
        if lock_path:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open('x', encoding='utf-8') as lock:
                lock.write('local report generation')
            locked = True
        if args.mode == 'history':
            report, stats = history(data)
            new_state = None
        else:
            state = json.loads(state_path.read_text(encoding='utf-8')) if state_path and state_path.exists() else {}
            report, new_state, stats = daily(data, state)
        render(report, args.output)
        if state_path and new_state is not None:
            temporary = state_path.with_suffix(state_path.suffix + '.tmp')
            temporary.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(state_path)
        Path(args.output).with_suffix('.stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(stats, ensure_ascii=False))
    finally:
        if locked:
            lock_path.unlink()


if __name__ == '__main__':
    main()
