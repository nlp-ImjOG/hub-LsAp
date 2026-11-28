"""Render evidence-based report JSON as a standalone, printable HTML document."""
import argparse
import html
import json
from pathlib import Path
from urllib.parse import urlparse

CSS = """
:root{--ink:#153832;--green:#176953;--paper:#f4f5ef;--muted:#62716c}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.8 'Microsoft YaHei',sans-serif}
main{max-width:1180px;margin:auto;padding:48px 36px 70px}header{border-top:7px solid var(--green);padding-top:28px;margin-bottom:32px}
h1{font-size:38px;line-height:1.35;max-width:950px;margin:12px 0 18px}h2{font-size:24px;margin:0 0 18px}p{margin:10px 0 18px}
.sub,.muted{color:var(--muted);font-size:14px}.summary{font-size:19px;border-left:4px solid #a3b76b;padding:10px 22px;background:#e9eee1}
.kpis{display:flex;flex-wrap:wrap;gap:16px;margin:26px 0}.kpi{flex:1;min-width:175px;background:var(--ink);color:white;padding:20px 24px;border-radius:4px}
.kpi strong{display:block;font-size:30px;font-weight:600}.kpi span{font-size:13px;color:#d3dfd3}section{background:white;padding:28px;margin:22px 0;border:1px solid #e2e8df;border-radius:5px}
.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th{text-align:left;background:#eaf0e7;color:#214e40}th,td{padding:12px 14px;border-bottom:1px solid #e4e9e4;vertical-align:top;min-width:95px}td{max-width:420px;overflow-wrap:anywhere}
a{color:#176953;text-decoration:underline;text-underline-offset:3px}button{float:right;padding:9px 18px;background:white;border:1px solid #8c9e92;border-radius:3px;color:var(--ink);cursor:pointer}
.bar{display:grid;grid-template-columns:210px 1fr 90px;align-items:center;gap:14px;margin:12px 0}.track{background:#eef2e9;height:22px}.fill{background:#47876b;height:100%}.bar span{font-size:14px}.sources li{margin-bottom:16px;overflow-wrap:anywhere}
input{padding:9px 12px;border:1px solid #bbc9bc;width:100%;margin:0 0 16px;font:inherit}footer{font-size:13px;color:var(--muted)}
@media(max-width:700px){main{padding:24px 16px}section{padding:20px 16px}h1{font-size:28px}.bar{grid-template-columns:120px 1fr 60px}.kpi{min-width:135px}}
@media print{body{background:white;font-size:11pt}main{padding:0;max-width:none}button,input{display:none}.kpi{background:#eef2e9;color:#153832}.kpi span{color:#153832}section{break-inside:auto;padding:16px 0;border:0;border-top:1px solid #bbb}tr{break-inside:avoid}thead{display:table-header-group}h2{break-after:avoid}a{color:inherit}.scroll{overflow:visible}}
"""


def escape(value):
    return html.escape(str(value))


def cell(value):
    if isinstance(value, dict):
        url = str(value.get('url', ''))
        if urlparse(url).scheme not in ('https', 'http'):
            return escape(value.get('text', ''))
        return f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(value.get("text", url))}</a>'
    return escape(value)


def render(data, output):
    title = escape(data['title'])
    parts = [f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{CSS}</style></head><body><main>',
             f'<header><button onclick="window.print()">打印 / 保存PDF</button><p class="sub">{escape(data.get("subtitle", ""))}</p><h1>{title}</h1><p class="summary">{escape(data.get("summary", ""))}</p></header>']
    parts.append('<div class="kpis">')
    for item in data.get('kpis', []):
        parts.append(f'<div class="kpi"><strong>{escape(item["value"])}</strong><span>{escape(item["label"])}</span></div>')
    parts.append('</div>')
    for section in data.get('sections', []):
        parts.append(f'<section><h2>{escape(section["heading"])}</h2>')
        for paragraph in section.get('paragraphs', []):
            parts.append(f'<p>{escape(paragraph)}</p>')
        bars = section.get('bars', [])
        maximum = max([float(x['value']) for x in bars] + [1])
        for item in bars:
            width = max(0, float(item['value'])) / maximum * 100
            parts.append(f'<div class="bar"><span>{escape(item["label"])}</span><div class="track"><div class="fill" style="width:{width:.2f}%"></div></div><span>{escape(item["value"])}</span></div>')
        table = section.get('table')
        if table:
            parts.append('<input aria-label="筛选本节表格" placeholder="输入关键词筛选本节表格" oninput="filterRows(this)"><div class="scroll"><table><thead><tr>')
            parts.extend(f'<th>{escape(x)}</th>' for x in table['headers'])
            parts.append('</tr></thead><tbody>')
            for row in table['rows']:
                if len(row) != len(table['headers']):
                    raise ValueError('Table row width differs from headers')
                parts.append('<tr>' + ''.join(f'<td>{cell(x)}</td>' for x in row) + '</tr>')
            parts.append('</tbody></table></div>')
        parts.append('</section>')
    if data.get('sources'):
        parts.append('<section><h2>来源与证据</h2><ol class="sources">')
        for source in data['sources']:
            parts.append('<li>' + cell({'text': source['id'] + ' · ' + source['title'], 'url': source['url']}) + f'<div class="muted">{escape(source.get("publisher", ""))} · {escape(source.get("published_at", ""))} · {escape(source.get("verification", ""))}</div></li>')
        parts.append('</ol></section>')
    parts.append('<footer>报告保留公开资料的时间与组织边界，分析建议供业务讨论。表格支持本节筛选，打印包含全部已显示内容。</footer></main><script>function filterRows(input){const q=input.value.toLowerCase();input.parentElement.querySelectorAll("tbody tr").forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(q));}</script></body></html>')
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(''.join(parts), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    args = parser.parse_args()
    render(json.loads(Path(args.input).read_text(encoding='utf-8-sig')), args.output)
