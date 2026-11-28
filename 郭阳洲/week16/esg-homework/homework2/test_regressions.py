"""Regression checks for observed business-rule failures and evidence preparation."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent
TENDER = ROOT.parent / 'skills/esg-tender-intelligence/scripts'
MONTHLY = ROOT.parent / 'skills/esg-monthly-report/scripts'
sys.path.insert(0, str(TENDER))
sys.path.insert(0, str(MONTHLY))
from analyze import history, daily, amount_yuan
from research import clean, canonical_url, validate_summary


class BusinessRegressionTests(unittest.TestCase):
    def setUp(self):
        self.record = dict(project_id='2026-001', lot='1', title='碳核查', buyer='采购人甲',
            region='江苏', category='碳核查', published_at='2026-10-01', supplier='供应商',
            amount='100', unit='万元', currency='CNY', amount_type='total', status='awarded',
            url='https://example.org/a', verification='测试输入')
        self.history = dict(start='2026-01-01', end='2027-01-01', records=[self.record], title='测试', coverage='测试')
        row = dict(project_id='demo', lot='1', buyer='甲', title='碳服务', url='https://example.org/a',
            published_at='2026-11-25T08:00:00+08:00', deadline='2026-12-01T09:00:00+08:00',
            acquisition_end='2026-11-30T17:00:00+08:00', version='v1', status='open', budget_text='100万元',
            scope='核查', qualification='待核验')
        self.daily = dict(as_of='2026-11-25T10:00:00+08:00', window_start='2026-11-24T10:00:00+08:00',
                          coverage='测试', title='测试', records=[row])

    def test_project_number_collision(self):
        other = dict(self.record, buyer='采购人乙')
        self.history['records'].append(other)
        report, stats = history(self.history)
        self.assertEqual(stats['projects'], 2)
        self.assertIn('最高金额占比50.0%', report['sections'][-1]['paragraphs'][-1])

    def test_ambiguous_legacy_project_total(self):
        self.history['records'].append(dict(self.record, buyer='采购人乙'))
        self.history['project_totals'] = {'2026-001': '1000000'}
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            history(self.history)

    def test_buyer_specific_project_totals(self):
        self.history['records'].append(dict(self.record, buyer='采购人乙'))
        self.history['project_totals_by_buyer'] = [dict(buyer=b, project_id='2026-001', total_yuan='1000000') for b in ['采购人甲', '采购人乙']]
        self.assertEqual(history(self.history)[1]['lots'], 2)

    def test_legacy_total_and_exact_duplicate(self):
        self.history['records'].append(copy.deepcopy(self.record))
        self.history['project_totals'] = {'2026-001': '1000000'}
        self.assertEqual(history(self.history)[1]['lots'], 1)

    def test_missing_acquisition_start(self):
        report, _, _ = daily(self.daily, {})
        self.assertEqual(report['sections'][0]['heading'], '期限待核验')

    def test_future_acquisition(self):
        self.daily['records'][0]['acquisition_start'] = '2026-11-26T09:00:00+08:00'
        self.assertEqual(daily(self.daily, {})[0]['sections'][0]['heading'], '文件获取尚未开始')

    def test_repetition_and_updated_cancellation(self):
        _, state, first = daily(self.daily, {})
        self.assertEqual(first['new_records'], 1)
        self.assertEqual(daily(self.daily, state)[2]['new_records'], 0)
        self.daily['records'][0].update(published_at='2026-10-01T08:00:00+08:00', updated_at='2026-11-25T09:00:00+08:00', version='v2', status='cancelled')
        self.assertEqual(daily(self.daily, state)[0]['sections'][0]['heading'], '撤销或终止')

    def test_empty_history(self):
        self.history['records'] = []
        self.assertEqual(history(self.history)[1]['total_yuan'], '0')

    def test_currency_and_units(self):
        self.assertEqual(str(amount_yuan(dict(self.record, amount='1.25', unit='亿元'))), '125000000.00')
        self.assertIsNone(amount_yuan(dict(self.record, currency='USD')))

    def test_url_and_content_dedup(self):
        doc = dict(id='1', title='政策', url='https://example.org/p?utm_source=x', text='政策正文', fetch_status='ok', published_at='2026-10-02')
        corpus = {'documents': [doc, dict(doc, id='2', url='https://example.org/p?utm_source=y')]}
        result = clean(corpus, dict(month='2026-10', cutoff='2026-11-25'))
        self.assertEqual(len(result['documents']), 1)
        self.assertEqual(len(result['duplicates']), 1)

    def test_after_cutoff_is_pending(self):
        doc = dict(id='1', title='政策', url='https://example.org/p', text='政策', fetch_status='ok', published_at='2026-11-26')
        result = clean({'documents': [doc]}, dict(month='2026-10', cutoff='2026-11-25'))
        self.assertEqual(len(result['pending']), 1)

    def test_summary_id_validation(self):
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            validate_summary({'items': [{'source_id': 'invented', 'decision': 'included'}]}, {'documents': [{'id': 'real'}]})

    def test_known_unread_source_can_be_pending(self):
        corpus = {'documents': [{'id': 'read'}], 'pending': [{'id': 'unread'}]}
        validate_summary({'items': [{'source_id': 'read', 'decision': 'included'}, {'source_id': 'unread', 'decision': 'pending'}]}, corpus)
        with self.assertRaisesRegex(ValueError, 'Unread'):
            validate_summary({'items': [{'source_id': 'read', 'decision': 'included'}, {'source_id': 'unread', 'decision': 'included'}]}, corpus)

    def test_known_duplicate_can_be_outside(self):
        corpus = {'documents': [{'id': 'read'}], 'duplicates': [{'id': 'duplicate'}]}
        validate_summary({'items': [{'source_id': 'read', 'decision': 'included'}, {'source_id': 'duplicate', 'decision': 'outside'}]}, corpus)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            validate_summary({'items': [{'source_id': 'read', 'decision': 'included'}, {'source_id': 'duplicate', 'decision': 'included'}]}, corpus)


if __name__ == '__main__':
    unittest.main(verbosity=2)
