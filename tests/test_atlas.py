import io
import json
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from atlas.app import create_app
from atlas.planner import plan, local_datetime
from atlas.store import Store


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name, testing=True)
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as session:
            self.headers = {'X-ATLAS-CSRF': session['csrf']}
        self.store = self.app.extensions['atlas_store']
        self.auth = self.app.extensions['atlas_auth']

    def tearDown(self):
        self.temp.cleanup()

    def post(self, url, data):
        return self.client.post(url, json=data, headers=self.headers)

    def test_csrf_host_and_cross_origin(self):
        data = {'title': 'Test', 'body': 'Tekst'}
        self.assertEqual(self.client.post('/api/notes', json=data).status_code, 403)
        self.assertEqual(self.client.get('/api/state', headers={'Host': 'evil.example'}).status_code, 403)
        headers = dict(self.headers, Origin='https://evil.example')
        self.assertEqual(self.client.post('/api/notes', json=data, headers=headers).status_code, 403)
        self.assertEqual(self.post('/api/notes', data).status_code, 201)

    def test_tasks_edit_and_persist(self):
        result = self.post('/api/tasks', {'title': 'Toets', 'subject': 'Nederlands', 'kind': 'toets',
                                         'due': '2026-10-20T10:00', 'minutes': 90})
        self.assertEqual(result.status_code, 201)
        id_ = result.json['id']
        result = self.client.patch(f'/api/tasks/{id_}', json={'done': True, 'title': 'Toets lezen'}, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        reopened = Store(self.temp.name).rows('SELECT * FROM tasks')[0]
        self.assertEqual(reopened['title'], 'Toets lezen')
        self.assertEqual(reopened['done'], 1)
        self.assertEqual(self.post('/api/tasks', {'title': 'Invalid'}).status_code, 400)

    def test_documents_and_recipe_scaling(self):
        result = self.client.post('/api/documents', data={'file': (io.BytesIO(b'School notitie'), '../school.md')}, headers=self.headers)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(self.store.rows('SELECT title FROM notes')[0]['title'], 'school.md')
        result = self.client.post('/api/documents', data={'file': (io.BytesIO(b'bad'), 'run.py')}, headers=self.headers)
        self.assertEqual(result.status_code, 400)
        result = self.post('/api/recipes', {'title': 'Deeg', 'portions': 4,
            'ingredients': [{'name': 'Bloem', 'amount': 250, 'unit': 'g'}], 'method': 'Meng.'})
        self.assertEqual(result.status_code, 201)
        scaled = self.client.get(f"/api/recipes/{result.json['id']}/scale?portions=6").json
        self.assertEqual(scaled['ingredients'][0]['amount'], 375)
        self.assertEqual(self.client.get('/api/recipes/1/scale?portions=nan').status_code, 400)

    def test_ai_proposals_require_approval_and_cannot_replay(self):
        output = [{'type': 'function_call', 'name': 'create_note', 'arguments': json.dumps({'title': 'Recept', 'body': 'Onthouden'})}]
        with patch.object(self.auth, 'respond', return_value=output):
            result = self.post('/api/ai', {'model': 'test', 'message': 'Bewaar dit'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.store.rows('SELECT * FROM notes'), [])
        id_ = result.json['actions'][0]['id']
        self.assertEqual(self.post(f'/api/actions/{id_}/approve', {}).status_code, 200)
        self.assertEqual(self.post(f'/api/actions/{id_}/approve', {}).status_code, 400)
        self.assertEqual(len(self.store.rows('SELECT * FROM notes')), 1)

    def test_ai_auto_actions_and_allowlist(self):
        self.store.set_setting('automatic', True)
        output = [{'type': 'function_call', 'name': 'create_note', 'arguments': '{"title":"A","body":"B"}'}]
        with patch.object(self.auth, 'respond', return_value=output):
            result = self.post('/api/ai', {'model': 'test', 'message': 'Onthoud'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(self.store.rows('SELECT * FROM notes')), 1)
        with patch.object(self.auth, 'respond', return_value=[{'type': 'function_call', 'name': 'shell', 'arguments': '{}'}]):
            result = self.post('/api/ai', {'model': 'test', 'message': 'Run'})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(len(self.store.rows('SELECT * FROM actions')), 1)

    def test_failure_creates_no_actions_and_memory_is_opt_in(self):
        self.store.write('INSERT INTO notes(title,body) VALUES (?,?)', ('Private', 'Secret'))
        with patch.object(self.auth, 'respond', side_effect=ValueError('Interrupted')) as mock:
            result = self.post('/api/ai', {'model': 'test', 'message': 'Hallo'})
        self.assertEqual(result.status_code, 400)
        self.assertNotIn('notes', mock.call_args.args[2])
        self.assertEqual(self.store.rows('SELECT * FROM actions'), [])
        exported = self.client.get('/api/export').json
        self.assertNotIn('access_token', json.dumps(exported))
        self.assertNotIn('session.key', json.dumps(exported))


class PlannerTests(unittest.TestCase):
    def test_no_overlap_deadline_and_replan(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.write('INSERT INTO tasks(title,subject,kind,due,minutes) VALUES (?,?,?,?,?)',
                        ('Verslag', 'School', 'taak', '2026-10-15T19:00', 120))
            store.write('INSERT INTO events(title,start,end) VALUES (?,?,?)',
                        ('Werk', '2026-10-14T16:00', '2026-10-14T18:00'))
            now = datetime(2026, 10, 14, 15)
            result = plan(store, now)
            self.assertFalse(result['unplanned'])
            duration = 0
            for block in result['blocks']:
                start, end = local_datetime(block['start']), local_datetime(block['end'])
                self.assertLessEqual(end, datetime(2026, 10, 15, 19))
                self.assertTrue(end <= datetime(2026, 10, 14, 16) or start >= datetime(2026, 10, 14, 18))
                duration += (end-start).total_seconds()/60
            self.assertEqual(duration, 120)
            first_count = len(store.rows('SELECT * FROM events'))
            plan(store, now)
            self.assertEqual(len(store.rows('SELECT * FROM events')), first_count)
            self.assertEqual(len(store.rows('SELECT * FROM events WHERE generated=0')), 1)

    def test_impossible_deadline_reports_remaining(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.write('INSERT INTO tasks(title,subject,kind,due,minutes) VALUES (?,?,?,?,?)',
                        ('Toets', 'School', 'toets', '2026-10-14T16:20', 60))
            result = plan(store, datetime(2026, 10, 14, 16))
            self.assertEqual(result['unplanned'][0]['minutes'], 40)


if __name__ == '__main__':
    unittest.main()
