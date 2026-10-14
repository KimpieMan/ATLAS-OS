from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Amsterdam')


def local_datetime(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(TZ).replace(tzinfo=None)
    return dt


def plan(store, now=None):
    """Replace only generated future blocks; never overlap appointments or deadlines."""
    now = now or datetime.now(TZ).replace(tzinfo=None)
    now = now.replace(second=0, microsecond=0)
    end_window = now + timedelta(days=7)
    day_start = int(store.setting('study_start', 16))
    day_end = int(store.setting('study_end', 20))
    with store.connection() as db:
        db.execute('DELETE FROM events WHERE generated=1 AND start>=?', (now.isoformat(timespec='minutes'),))
        busy = [(local_datetime(e['start']), local_datetime(e['end'])) for e in db.execute('SELECT * FROM events')]
        tasks = list(db.execute('SELECT * FROM tasks WHERE done=0 ORDER BY due,id'))
        blocks, unplanned = [], []
        for task in tasks:
            due = local_datetime(task['due'])
            remaining = task['minutes']
            # Preserve already-started study blocks and account for their duration.
            for e in db.execute('SELECT * FROM events WHERE generated=1 AND task_id=?', (task['id'],)):
                remaining -= int((local_datetime(e['end']) - local_datetime(e['start'])).total_seconds() / 60)
            cursor = now
            while remaining > 0 and cursor < min(due, end_window):
                start = max(cursor, datetime.combine(cursor.date(), time(day_start)))
                boundary = min(datetime.combine(cursor.date(), time(day_end)), due, end_window)
                collision = sorted((a, b) for a, b in busy if b > start and a < boundary)
                for a, b in collision:
                    if a <= start:
                        start = max(start, b)
                    else:
                        boundary = min(boundary, a)
                        break
                available = int((boundary - start).total_seconds() / 60)
                if available >= min(15, remaining):
                    duration = min(45, remaining, available)
                    end = start + timedelta(minutes=duration)
                    values = (f"Studie: {task['title']}", start.isoformat(timespec='minutes'), end.isoformat(timespec='minutes'), task['id'])
                    db.execute('INSERT INTO events(title,start,end,task_id,generated) VALUES (?,?,?,?,1)', values)
                    blocks.append({'title': values[0], 'start': values[1], 'end': values[2]})
                    busy.append((start, end))
                    remaining -= duration
                    cursor = end + timedelta(minutes=10)
                elif collision and start < datetime.combine(cursor.date(), time(day_end)):
                    cursor = max(start + timedelta(minutes=1), collision[0][1])
                else:
                    cursor = datetime.combine(cursor.date() + timedelta(days=1), time(day_start))
            if remaining > 0:
                unplanned.append({'title': task['title'], 'minutes': remaining})
    return {'blocks': blocks, 'unplanned': unplanned}
