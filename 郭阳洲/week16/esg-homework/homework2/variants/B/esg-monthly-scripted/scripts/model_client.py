"""Use the locally authenticated Codex CLI as a structured model adapter."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


def redact(text):
    text = re.sub(r'https?://\S+', '[URL redacted]', text)
    return re.sub(r'(?i)(bearer|api[_-]?key|token)\s*[=:]\s*\S+', r'\1=[redacted]', text)


def invoke(prompt, schema, directory, live_search=False, timeout=300):
    folder = Path(directory).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    schema_path = folder / 'output-schema.json'
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'prompt.txt').write_text(prompt, encoding='utf-8')
    executable = os.environ.get('CODEX_APP_RUNTIME_CLI_PATH') or shutil.which('codex.exe') or shutil.which('codex.cmd') or shutil.which('codex')
    if not executable:
        raise RuntimeError('Codex CLI is required. Run codex login before using this adapter.')
    command = [executable, 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
               '--sandbox', 'read-only', '-c', 'model_providers.openai.supports_websockets=false',
               '-c', 'web_search="live"' if live_search else 'web_search="disabled"',
               '--output-schema', str(schema_path), '--json', '-']
    started = time.monotonic()
    metrics = {'backend': 'codex-cli', 'web_search': live_search, 'success': False,
               'model': 'CLI/server default; not exposed by this adapter', 'usage': None}
    try:
        result = subprocess.run(command, input=prompt, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', cwd=folder, timeout=timeout, shell=False)
        events = []
        answers = []
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(event)
            item = event.get('item', {})
            if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                answers.append(item.get('text', ''))
            if event.get('type') == 'turn.completed':
                metrics['usage'] = event.get('usage')
        (folder / 'events.jsonl').write_text('\n'.join(json.dumps(e, ensure_ascii=False) for e in events), encoding='utf-8')
        (folder / 'stderr.txt').write_text(redact(result.stderr), encoding='utf-8')
        metrics['exit_code'] = result.returncode
        if result.returncode or not answers:
            raise RuntimeError('Model call failed; inspect events.jsonl and redacted stderr.txt')
        answer = json.loads(answers[-1])
        metrics['success'] = True
        metrics['tool_types'] = [e.get('item', {}).get('type') for e in events if e.get('type') == 'item.completed']
        (folder / 'response.json').write_text(json.dumps(answer, ensure_ascii=False, indent=2), encoding='utf-8')
        return answer, metrics
    except subprocess.TimeoutExpired:
        metrics['error'] = 'model timeout'
        raise RuntimeError(f'Model call exceeded {timeout} seconds') from None
    finally:
        metrics['elapsed_seconds'] = round(time.monotonic() - started, 3)
        (folder / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
