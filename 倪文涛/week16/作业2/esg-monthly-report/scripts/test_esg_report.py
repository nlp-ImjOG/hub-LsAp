"""Offline regression checks; synthetic facts, no external requests or API costs."""
import argparse
import copy
import csv
import io
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import esg_report as esg


def example():
    text = '【合成测试资料】示例企业于2025年4月10日发布节水项目。项目仍在试点，尚无经验证的节水量。'
    batches = [dict(query='示例企业 节水', searched_at='2026-11-23T10:00:00+08:00',
                    provider='test-fixture', query_id='Q01', results=[dict(
                        url='https://example.org/event?id=1&utm_source=test', title='合成测试公告',
                        text=text, published_date='2025-04-10')])]
    bundle = esg.collect_batches(batches)
    source = bundle['sources'][0]
    profile = dict(client='合成测试企业', start='2025-04-01', end='2025-04-30',
                   cutoff='2025-04-30', timezone='Asia/Shanghai')
    event = dict(id='E01', section='client', title='试点启动', entity='合成测试企业',
                 event_date='2025-04-10', published_date='2025-04-10', inclusion_basis='event',
                 status='selected', reviewed=True, selection_reason='本期项目启动',
                 fact='发布节水试点，尚无经验证成效。', impact='需进一步确定用水基线。',
                 recommendation='核对试点基线与边界。', evidence=[dict(
                     source_id=source['id'], quote='项目仍在试点', locator='公告第二句')])
    report = dict(profile=profile, events=[event], executive_summary=[dict(text='建议核查试点基线。', event_ids=['E01'])],
                  actions=[dict(event_ids=['E01'], action='建立用水基线', owner='EHS', due='2025-05',
                                deliverable='基线清单', priority='中')],
                  coverage={k: '仅合成资料测试，未执行该类别检索。' for k in esg.CATEGORIES},
                  limitations=['全部内容为合成测试资料。'], outlook=[], peer_basis=[])
    return batches, bundle, report


class PipelineTests(unittest.TestCase):
    def test_period_and_future_boundaries(self):
        self.assertEqual(esg.period(date(2026, 11, 23)), ('2026-10-24', '2026-11-22'))
        self.assertEqual(esg.period(date(2024, 3, 1), month='2024-02'), ('2024-02-01', '2024-02-29'))
        self.assertEqual(esg.period(date(2026, 11, 23), month='2026-11'), ('2026-11-01', '2026-11-23'))
        for values in [dict(start='2025-01-01'), dict(month='2027-01'),
                       dict(start='2025-05-01', end='2025-04-01')]:
            with self.assertRaises(ValueError):
                esg.period(date(2026, 11, 23), **values)

    def test_dedupe_preserves_identity_and_provenance(self):
        batches, _, _ = example()
        other = copy.deepcopy(batches[0])
        other.update(query_id='Q02', query='示例企业 ESG')
        other['results'] = [dict(url='https://example.org/event?id=1#top', content='搜索摘要', title='转载标题'),
                            dict(url='https://example.org/event?id=2', content='另一事项', title='不同记录')]
        result = esg.collect_batches(batches + [other])
        self.assertEqual(len(result['sources']), 2)
        source = result['sources'][0]
        self.assertEqual(source['content_status'], 'extracted')
        self.assertEqual(source['query_ids'], ['Q01', 'Q02'])
        self.assertIn('仍在试点', source['excerpt'])
        self.assertEqual(len(result['search_log']), 2)

    def test_summary_is_extractive(self):
        text = '导航菜单。公司发布节水目标。尚未披露实际成效。'
        summary = esg.extract_summary(text, '节水 目标')
        for sentence in summary.split():
            self.assertIn(sentence, text)
        self.assertEqual(esg.source_date('Tue, 11 Mar 2025 17:00:00 GMT'), '2025-03-11')
        self.assertEqual(esg.source_date('昨天'), '')

    def test_evidence_and_historical_gates(self):
        _, bundle, report = example()
        self.assertEqual(esg.validate_report(report, bundle), [])
        cases = [('published_date', '2025-05-01'), ('event_date', '2025-03-30'), ('reviewed', False)]
        for key, value in cases:
            altered = copy.deepcopy(report)
            altered['events'][0][key] = value
            self.assertTrue(esg.validate_report(altered, bundle), key)
        altered = copy.deepcopy(bundle)
        altered['sources'][0]['content_status'] = 'snippet'
        self.assertTrue(esg.validate_report(report, altered))
        report['events'][0]['evidence'][0]['quote'] = '已实现节水百分之五十'
        self.assertTrue(esg.validate_report(report, bundle))

    def test_old_rule_effective_this_month_is_allowed(self):
        _, bundle, report = example()
        event = report['events'][0]
        event.update(section='policy', event_date='2024-09-01', published_date='2024-09-01',
                     effective_date='2025-04-01', inclusion_basis='effective',
                     policy_status='本月实施', applicability='待核实主体门槛')
        bundle['sources'][0]['published_dates'] = ['2024-09-01']
        self.assertEqual(esg.validate_report(report, bundle), [])
        event.pop('applicability')
        self.assertTrue(esg.validate_report(report, bundle))

    def test_no_key_and_bounded_api_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'sources.json'
            args = argparse.Namespace(out=str(out), plan=str(Path(temp) / 'plan.json'), limit=3, max_results=5)
            with patch.dict(os.environ, {}, clear=True), patch.object(esg, 'tavily_request') as api:
                with self.assertRaisesRegex(ValueError, '未配置'):
                    esg.search(args)
                api.assert_not_called()
                self.assertFalse(out.exists())
            esg.init(argparse.Namespace(client='示例', industry='能源', region=[], peer=[], today='2026-11-23',
                     timezone='Asia/Shanghai', month='2025-04', start=None, end=None, out=temp))
            response = dict(results=[dict(url='https://example.org/a', title='示例', raw_content='示例公告。')])
            error = HTTPError('https://api.tavily.com/search', 429, 'rate limit', {}, None)
            with patch.dict(os.environ, {'TAVILY_API_KEY': 'synthetic-key'}), patch.object(
                    esg, 'tavily_request', side_effect=[response, error]) as api:
                self.assertEqual(esg.search(args), 2)
                self.assertEqual(api.call_count, 2)
                self.assertEqual(api.call_args_list[0].args[0]['end_date'], '2025-05-01')
            data = esg.read_json(out)
            self.assertEqual(len(data['sources']), 1)
            self.assertIn('HTTP 429', data['search_log'][1]['error'])
            self.assertNotIn('synthetic-key', out.read_text())

    def test_render_escaping_csv_and_no_overwrite(self):
        _, bundle, report = example()
        report['events'][0]['fact'] = '<script>alert(1)</script> | 合成资料'
        report['events'][0]['title'] = '=SUM(1,2)'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rp, sp = root / 'report.json', root / 'sources.json'
            rp.write_text(esg.dump(report))
            sp.write_text(esg.dump(bundle))
            args = argparse.Namespace(report=str(rp), sources=str(sp), out=str(root / 'out'), draft=False)
            esg.render(args)
            page = next((root / 'out').glob('*.html')).read_text()
            self.assertNotIn('<script>', page)
            self.assertIn('&lt;script&gt;', page)
            with next((root / 'out').glob('*.csv')).open(encoding='utf-8-sig', newline='') as stream:
                row = list(csv.DictReader(stream))[0]
            self.assertEqual(row['标题'], "'=SUM(1,2)")
            self.assertEqual(row['核验状态'], '已核验（执行者标记）')
            self.assertIn('项目仍在试点', row['原文摘录'])
            self.assertIn('2026-11-23', row['来源日期与访问时间'])
            old = next((root / 'out').glob('*.html')).read_bytes()
            with self.assertRaises(ValueError):
                esg.render(args)
            self.assertEqual(next((root / 'out').glob('*.html')).read_bytes(), old)

    def test_unreviewed_report_cannot_be_published(self):
        _, bundle, report = example()
        report['events'][0]['reviewed'] = False
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rp, sp = root / 'report.json', root / 'sources.json'
            rp.write_text(esg.dump(report))
            sp.write_text(esg.dump(bundle))
            args = argparse.Namespace(report=str(rp), sources=str(sp), out=str(root / 'out'), draft=False)
            with self.assertRaises(ValueError):
                esg.render(args)
            self.assertFalse((root / 'out').exists())
            args.draft = True
            esg.render(args)
            self.assertIn('待核验草稿', next((root / 'out').glob('ESG月报*.md')).read_text())
            with next((root / 'out').glob('*.csv')).open(encoding='utf-8-sig', newline='') as stream:
                row = list(csv.DictReader(stream))[0]
            self.assertEqual(row['核验状态'], '未核验')
            self.assertEqual(row['报告状态'], '待核验草稿')

    def test_peer_cross_reference(self):
        _, bundle, report = example()
        report['events'][0]['section'] = 'industry'
        report['peer_basis'] = [dict(name='示例同行', reason='同类业务', event_ids=['E01'])]
        self.assertEqual(esg.validate_report(report, bundle), [])
        body = esg.render_blocks(esg.blocks(report, bundle, [], False), 'html')
        self.assertIn('本期同行实践已在其他章节分析，参见：E01', body)
        report['peer_basis'][0]['event_ids'] = ['E99']
        self.assertTrue(esg.validate_report(report, bundle))

    def test_reject_unsafe_urls(self):
        for url in ['javascript:alert(1)', 'file:///etc/passwd', 'https://user:pass@example.org']:
            with self.assertRaises(ValueError):
                esg.canonical_url(url)


if __name__ == '__main__':
    unittest.main()
