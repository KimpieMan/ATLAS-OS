import io
import json
import math
import os
import secrets
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, render_template, session, redirect, send_file
from werkzeug.exceptions import HTTPException

from .auth import ChatGPT, atomic_private
from .planner import TZ, local_datetime, plan
from .store import Store


def text(value, label, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{label}: vul 1 tot {maximum} tekens in')
    return value.strip()


def number(value, label, minimum=1, maximum=10000):
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'{label}: vul een geldig getal in')
    if isinstance(value, bool) or not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f'{label}: kies tussen {minimum} en {maximum}')
    return result


def task_values(data):
    due = local_datetime(text(data.get('due'), 'Deadline', 40)).isoformat(timespec='minutes')
    kind = data.get('kind', 'taak')
    if kind not in ('taak', 'toets', 'deadline'):
        raise ValueError('Ongeldig taaktype')
    return (text(data.get('title'), 'Titel'), text(data.get('subject', 'Algemeen'), 'Vak'), kind,
            due, int(number(data.get('minutes', 45), 'Minuten', 1, 3000)))


TOOLS = [
    {'type': 'function', 'name': 'create_task', 'description': 'Maak een schooltaak, toets of deadline aan.',
     'parameters': {'type': 'object', 'properties': {
         'title': {'type': 'string'}, 'subject': {'type': 'string'},
         'kind': {'type': 'string', 'enum': ['taak', 'toets', 'deadline']},
         'due': {'type': 'string', 'description': 'Europe/Amsterdam ISO datum en tijd'},
         'minutes': {'type': 'integer'}}, 'required': ['title', 'subject', 'kind', 'due', 'minutes'], 'additionalProperties': False}},
    {'type': 'function', 'name': 'create_note', 'description': 'Bewaar een lokale notitie.',
     'parameters': {'type': 'object', 'properties': {'title': {'type': 'string'}, 'body': {'type': 'string'}},
                    'required': ['title', 'body'], 'additionalProperties': False}},
    {'type': 'function', 'name': 'plan_week', 'description': 'Verdeel open taken over vrije studietijd in de komende zeven dagen.',
     'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}
]


def create_app(directory=None, testing=False, port=8080):
    app = Flask(__name__)
    store = Store(directory or os.environ.get('ATLAS_DATA', str(Path.home() / '.local/share/atlas')))
    secret_path = store.directory / 'session.key'
    if not secret_path.exists():
        atomic_private(secret_path, secrets.token_bytes(32))
    app.secret_key = secret_path.read_bytes()
    app.config.update(TESTING=testing, MAX_CONTENT_LENGTH=2 * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
    auth = ChatGPT(store.directory, port)
    action_lock = threading.Lock()
    ai_lock = threading.Lock()
    app.extensions.update(atlas_store=store, atlas_auth=auth)

    @app.before_request
    def protect():
        host = urlparse('http://' + request.host).hostname
        if host not in ('127.0.0.1', 'localhost'):
            return jsonify(error='ATLAS is alleen lokaal bereikbaar'), 403
        if request.path == '/auth/callback':
            return None
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            token = session.get('csrf')
            if not token or not secrets.compare_digest(request.headers.get('X-ATLAS-CSRF', ''), token):
                return jsonify(error='Ongeldige sessie. Vernieuw de pagina.'), 403
            if request.headers.get('Origin') and request.headers['Origin'] != request.host_url.rstrip('/'):
                return jsonify(error='Ongeldige herkomst'), 403

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(Exception)
    def unexpected(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        # Never log OAuth query strings, tokens, document contents, or upstream responses.
        return jsonify(error='Actie mislukt. Probeer opnieuw of controleer de verbinding.'), 500

    @app.get('/')
    def index():
        session.setdefault('csrf', secrets.token_urlsafe(32))
        return render_template('index.html', csrf=session['csrf'])

    @app.get('/api/state')
    def state():
        return jsonify(tasks=store.rows('SELECT * FROM tasks ORDER BY done,due,id'),
                       events=store.rows('SELECT * FROM events ORDER BY start'),
                       notes=store.rows('SELECT * FROM notes ORDER BY id DESC'),
                       recipes=store.rows('SELECT * FROM recipes ORDER BY title'),
                       actions=store.rows('SELECT * FROM actions ORDER BY id DESC LIMIT 50'),
                       settings={'automatic': store.setting('automatic', False),
                                 'study_start': store.setting('study_start', 16),
                                 'study_end': store.setting('study_end', 20)},
                       chatgpt=auth.public_accounts())

    @app.post('/api/tasks')
    def add_task():
        values = task_values(request.get_json())
        id_ = store.write('INSERT INTO tasks(title,subject,kind,due,minutes) VALUES (?,?,?,?,?)', values)
        return jsonify(id=id_), 201

    @app.patch('/api/tasks/<int:id_>')
    def edit_task(id_):
        rows = store.rows('SELECT * FROM tasks WHERE id=?', (id_,))
        if not rows:
            return jsonify(error='Taak bestaat niet'), 404
        data = request.get_json()
        if 'done' in data and type(data['done']) is not bool:
            raise ValueError('Afgevinkt moet ja of nee zijn')
        values = task_values(dict(rows[0], **data))
        done = int(data.get('done', bool(rows[0]['done'])))
        with store.connection() as db:
            db.execute('UPDATE tasks SET title=?,subject=?,kind=?,due=?,minutes=?,done=? WHERE id=?', (*values, done, id_))
            if done:
                db.execute('DELETE FROM events WHERE generated=1 AND task_id=? AND start>=?',
                           (id_, datetime.now(TZ).replace(tzinfo=None).isoformat(timespec='minutes')))
        return jsonify(ok=True)

    @app.post('/api/events')
    def add_event():
        data = request.get_json()
        start, end = (local_datetime(text(data.get(key), key, 40)) for key in ('start', 'end'))
        if end <= start:
            raise ValueError('Eindtijd moet na begintijd liggen')
        id_ = store.write('INSERT INTO events(title,start,end) VALUES (?,?,?)',
                         (text(data.get('title'), 'Titel'), start.isoformat(timespec='minutes'), end.isoformat(timespec='minutes')))
        return jsonify(id=id_), 201

    @app.delete('/api/events/<int:id_>')
    def delete_event(id_):
        store.write('DELETE FROM events WHERE id=?', (id_,))
        return jsonify(ok=True)

    @app.post('/api/notes')
    def add_note():
        data = request.get_json()
        id_ = store.write('INSERT INTO notes(title,body) VALUES (?,?)',
                         (text(data.get('title'), 'Titel'), text(data.get('body'), 'Notitie', 100000)))
        return jsonify(id=id_), 201

    @app.post('/api/documents')
    def add_document():
        file = request.files.get('file')
        if not file or Path(file.filename or '').suffix.lower() not in ('.txt', '.md'):
            raise ValueError('Kies een UTF-8 .txt of .md document (maximaal 1 MB)')
        content = file.read(1000001)
        if len(content) > 1000000:
            raise ValueError('Document is groter dan 1 MB')
        try:
            body = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError('Document moet UTF-8 tekst bevatten')
        name = (file.filename or '').replace('\\', '/').split('/')[-1]
        id_ = store.write('INSERT INTO notes(title,body,source) VALUES (?,?,?)',
                         (text(name, 'Bestandsnaam'), text(body, 'Document', 1000000), 'document'))
        return jsonify(id=id_), 201

    @app.post('/api/recipes')
    def add_recipe():
        data = request.get_json()
        ingredients = data.get('ingredients')
        if not isinstance(ingredients, list) or not 1 <= len(ingredients) <= 100:
            raise ValueError('Gebruik 1 tot 100 ingrediënten')
        clean = []
        for row in ingredients:
            unit = row.get('unit')
            if unit not in ('g', 'ml', 'stuks'):
                raise ValueError('Gebruik g, ml of stuks')
            clean.append({'name': text(row.get('name'), 'Ingrediënt'),
                          'amount': number(row.get('amount'), 'Hoeveelheid', 0.01, 1000000), 'unit': unit})
        id_ = store.write('INSERT INTO recipes(title,portions,ingredients,method) VALUES (?,?,?,?)',
                         (text(data.get('title'), 'Titel'), number(data.get('portions'), 'Porties', 0.1, 1000),
                          json.dumps(clean), text(data.get('method', '-'), 'Bereiding', 10000)))
        return jsonify(id=id_), 201

    @app.get('/api/recipes/<int:id_>/scale')
    def scale_recipe(id_):
        rows = store.rows('SELECT * FROM recipes WHERE id=?', (id_,))
        if not rows:
            return jsonify(error='Recept bestaat niet'), 404
        portions = number(request.args.get('portions'), 'Porties', 0.1, 1000)
        recipe = rows[0]
        ingredients = json.loads(recipe['ingredients'])
        for row in ingredients:
            row['amount'] = round(row['amount'] * portions / recipe['portions'], 2)
        return jsonify(title=recipe['title'], portions=portions, ingredients=ingredients, method=recipe['method'])

    @app.post('/api/settings')
    def settings():
        data = request.get_json()
        if type(data.get('automatic')) is not bool:
            raise ValueError('Automatische acties: kies ja of nee')
        start = int(number(data.get('study_start'), 'Beginuur', 0, 23))
        end = int(number(data.get('study_end'), 'Einduur', 1, 24))
        if end <= start or end == 24:
            raise ValueError('Studie-einduur moet na het beginuur liggen en uiterlijk 23 zijn')
        for key, value in [('automatic', data['automatic']), ('study_start', start), ('study_end', end)]:
            store.set_setting(key, value)
        return jsonify(ok=True)

    def validate_action(name, payload):
        if not isinstance(payload, dict):
            raise ValueError('Ongeldige actiegegevens')
        if name == 'create_task':
            task_values(payload)
        elif name == 'create_note':
            text(payload.get('title'), 'Titel')
            text(payload.get('body'), 'Notitie', 100000)
        elif name == 'plan_week':
            if payload:
                raise ValueError('Weekplanning accepteert geen extra parameters')
        else:
            raise ValueError('Deze actie is niet toegestaan')

    def execute(id_):
        with action_lock:
            rows = store.rows('SELECT * FROM actions WHERE id=?', (id_,))
            if not rows or rows[0]['status'] != 'pending':
                raise ValueError('Actie bestaat niet of is al afgehandeld')
            row = rows[0]
            payload = json.loads(row['payload'])
            validate_action(row['name'], payload)
            # At-most-once: a crash after claiming never causes an automatic replay.
            store.write("UPDATE actions SET status='running' WHERE id=?", (id_,))
            try:
                if row['name'] == 'create_task':
                    result = {'id': store.write('INSERT INTO tasks(title,subject,kind,due,minutes) VALUES (?,?,?,?,?)', task_values(payload))}
                elif row['name'] == 'create_note':
                    result = {'id': store.write('INSERT INTO notes(title,body) VALUES (?,?)', (payload['title'], payload['body']))}
                else:
                    result = plan(store)
                store.write("UPDATE actions SET status='completed',result=? WHERE id=?", (json.dumps(result), id_))
                return result
            except Exception:
                store.write("UPDATE actions SET status='failed',result='Uitvoering mislukt' WHERE id=?", (id_,))
                raise

    @app.post('/api/plan')
    def make_plan():
        id_ = store.write('INSERT INTO actions(name,payload,status) VALUES (?,?,?)', ('plan_week', '{}', 'pending'))
        return jsonify(execute(id_))

    @app.post('/api/actions/<int:id_>/approve')
    def approve(id_):
        return jsonify(execute(id_))

    @app.post('/api/actions/<int:id_>/reject')
    def reject(id_):
        with action_lock:
            store.write("UPDATE actions SET status='rejected' WHERE id=? AND status='pending'", (id_,))
        return jsonify(ok=True)

    @app.get('/api/system')
    def system():
        total, used, free = shutil.disk_usage(store.directory)
        temperature = None
        try:
            temperature = round(int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000, 1)
        except (OSError, ValueError):
            pass
        return jsonify(version='0.1.0', temperature=temperature, disk_free_gb=round(free / 1024**3, 1),
                       disk_total_gb=round(total / 1024**3, 1), local_time=datetime.now(TZ).isoformat(timespec='minutes'),
                       allowed_actions=['create_task', 'create_note', 'plan_week'])

    @app.get('/api/export')
    def export():
        output = {table: store.rows(f'SELECT * FROM {table}') for table in ('tasks', 'events', 'notes', 'recipes', 'actions', 'settings')}
        return send_file(io.BytesIO(json.dumps(output, ensure_ascii=False, indent=2).encode()),
                         mimetype='application/json', as_attachment=True, download_name='atlas-backup.json')

    @app.post('/api/auth/start')
    def start_login():
        return jsonify(url=auth.start(request.get_json().get('account_id')))

    @app.get('/auth/callback')
    def callback():
        try:
            auth.callback(request.args)
        except Exception:
            return 'ChatGPT-inloggen mislukt of geannuleerd. Ga terug naar ATLAS en probeer opnieuw.', 400
        return redirect('/')

    @app.post('/api/auth/select')
    def select_account():
        auth.select(request.get_json().get('account_id'))
        return jsonify(ok=True)

    @app.post('/api/auth/logout')
    def logout():
        return jsonify(remote_revocation_confirmed=auth.logout())

    @app.get('/api/ai/models')
    def models():
        return jsonify(models=auth.models())

    @app.post('/api/ai')
    def ai():
        data = request.get_json()
        message = text(data.get('message'), 'Bericht', 10000)
        model = text(data.get('model'), 'Model')
        if not ai_lock.acquire(blocking=False):
            return jsonify(error='ATLAS verwerkt al een AI-verzoek'), 409
        try:
            context = {'now': datetime.now(TZ).isoformat(timespec='minutes'),
                       'tasks': store.rows('SELECT * FROM tasks WHERE done=0 LIMIT 100'),
                       'events': store.rows('SELECT * FROM events WHERE end>=? ORDER BY start LIMIT 100',
                                            (datetime.now(TZ).replace(tzinfo=None).isoformat(timespec='minutes'),))}
            if data.get('include_memory') is True:
                context['notes'] = store.rows('SELECT title,substr(body,1,3000) AS body FROM notes ORDER BY id DESC LIMIT 10')
            output = auth.respond(model, message, context, TOOLS)
            proposals, answer = [], []
            for item in output:
                if item.get('type') == 'message':
                    answer.extend(part['text'] for part in item.get('content', []) if part.get('type') == 'output_text')
                elif item.get('type') == 'function_call':
                    payload = json.loads(item['arguments'])
                    validate_action(item['name'], payload)
                    proposals.append((item['name'], payload))
            if len(proposals) > 10:
                raise ValueError('Te veel AI-acties in één verzoek')
            results = []
            for name, payload in proposals:
                id_ = store.write('INSERT INTO actions(name,payload,status) VALUES (?,?,?)', (name, json.dumps(payload), 'pending'))
                result = execute(id_) if store.setting('automatic', False) else None
                results.append({'id': id_, 'name': name, 'result': result})
            return jsonify(answer='\n'.join(answer) or 'Bekijk de voorgestelde acties hieronder.', actions=results)
        finally:
            ai_lock.release()

    return app
