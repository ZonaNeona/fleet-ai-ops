"""Live emulator → worker → real AI regression check. Never sends Telegram messages."""
import json
import time
from pathlib import Path
import httpx
from sqlalchemy import select, func
from app.db import db, Space, Item, Job, URL, now


def main():
    sid = None
    with httpx.Client(base_url=URL, headers={'Origin': URL}, timeout=25) as client:
        def post(path, body):
            response = client.post('/api/v1' + path, json=body)
            response.raise_for_status()
            return response.json()

        def sim(body):
            job = post('/bot/sim', body)
            deadline = time.monotonic() + 115
            while time.monotonic() < deadline:
                response = client.get('/api/v1/bot/sim/' + job['id'])
                response.raise_for_status()
                result = response.json()
                if result['state'] == 'done':
                    return result['result']
                if result['state'] == 'failed':
                    raise RuntimeError('Emulator job failed')
                time.sleep(.5)
            raise RuntimeError('Emulator reply timeout')

        def count_tickets():
            with db() as s:
                return s.scalar(select(func.count()).select_from(Item).where(Item.space == sid, Item.kind == 'ticket'))

        try:
            session = post('/session', {})
            sid = session['id']
            sim({'text': '/start'})
            sim({'callback': 'role:driver'})
            sim({'callback': 'd:ticket'})
            sim({'text': '/menu'})
            sim({'text': '/start'})
            before = count_tickets()
            replies = []
            for question in ['сколько стоит машина', 'Сколько стоит аренда Volkswagen Polo в сутки? Назови базовую ставку из каталога.']:
                result = sim({'text': question})
                answer = '\n\n'.join(m['text'] for m in result['messages'])
                assert 'AI временно недоступен' not in answer and 'не удалось' not in answer.lower(), answer
                assert count_tickets() == before
                replies.append({'question': question, 'answer': answer})
            with db() as s:
                jobs = s.scalars(select(Job).where(Job.space == sid, Job.kind == 'ai').order_by(Job.due)).all()
                assert len(jobs) == 2 and all(j.state == 'done' and j.result.get('model') for j in jobs)
                models = [{'model': j.result['model'], 'cost': j.result.get('cost'), 'tokens': j.result.get('tokens'),
                           'tools': [t['title'] for t in j.result.get('trace', []) if t.get('step') == 'tool']} for j in jobs]
            output = {'checked_at': now().isoformat(), 'passed': True, 'new_tickets': 0,
                      'transport': 'HTTPS emulator / worker / actual configured model', 'replies': replies, 'models': models}
            path = Path('reports/miniapp/bot-question-live.json')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(output, ensure_ascii=False, indent=2))
        finally:
            if sid:
                with db() as s:
                    space = s.get(Space, sid)
                    if space:
                        s.delete(space)


if __name__ == '__main__':
    main()
