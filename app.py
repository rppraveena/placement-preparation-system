import os
import sys
import json
import re
from datetime import date, timedelta, datetime
from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(__file__))
from database import get_db, init_db, DB_PATH
from ai_service import (ask_ai, generate_daily_plan, get_todays_plan,
                        generate_daily_briefing, smart_parse_sheet,
                        detect_category, fetch_tech_news)

app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ.get('SESSION_SECRET', 'minetracker-secret-2026')
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def row_to_dict(row):
    return dict(row) if row else None

def rows_to_list(rows):
    return [dict(r) for r in rows]

def get_setting(db, key, default=''):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row['value'] if row else default

def local_today():
    return date.today().isoformat()

# ─── INIT ─────────────────────────────────────────────────────────────────────
init_db()

# ─── MAIN PAGE ────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

# ─── DASHBOARD ────────────────────────────────────────────────────────────────
@app.route('/api/dashboard', methods=['GET'])
def dashboard():
    today = local_today()
    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT key,value FROM settings").fetchall()}
        daily_goal = int(settings.get('daily_goal', 10))
        placement_deadline = settings.get('placement_deadline', '2026-10-01')
        days_left = max(0, (date.fromisoformat(placement_deadline) - date.today()).days)

        total     = db.execute("SELECT COUNT(*) as c FROM problems").fetchone()['c']
        solved    = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Solved'").fetchone()['c']
        attempted = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Attempted'").fetchone()['c']
        pending   = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Pending'").fetchone()['c']
        skipped   = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Skipped'").fetchone()['c']

        streak = 0
        check = date.today() - timedelta(days=1)
        for _ in range(365):
            row = db.execute("SELECT problems_solved FROM daily_log WHERE log_date=?", (check.isoformat(),)).fetchone()
            if row and row['problems_solved'] >= 1:
                streak += 1
                check -= timedelta(days=1)
            else:
                break

        today_plan_solved = db.execute(
            "SELECT COUNT(*) as c FROM daily_plan WHERE plan_date=? AND status='Solved'", (today,)
        ).fetchone()['c']
        today_pct = min(100, round(today_plan_solved / daily_goal * 100)) if daily_goal else 0

        import calendar
        week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        week_end   = (date.today() + timedelta(days=6 - date.today().weekday())).isoformat()
        week_plan_solved = db.execute(
            "SELECT COUNT(*) as c FROM daily_plan WHERE plan_date>=? AND plan_date<=? AND status='Solved'",
            (week_start, week_end)
        ).fetchone()['c']

        month_start = date.today().replace(day=1).isoformat()
        last_day = calendar.monthrange(date.today().year, date.today().month)[1]
        month_end = date.today().replace(day=last_day).isoformat()
        month_plan_solved = db.execute(
            "SELECT COUNT(*) as c FROM daily_plan WHERE plan_date>=? AND plan_date<=? AND status='Solved'",
            (month_start, month_end)
        ).fetchone()['c']

        ai_row = db.execute(
            "SELECT content, model_used FROM ai_feedback WHERE feedback_date=? AND feedback_type='daily'", (today,)
        ).fetchone()
        ai_briefing = ai_row['content'] if ai_row else None
        ai_model    = ai_row['model_used'] if ai_row else None

    today_plan = generate_daily_plan(today)

    return jsonify({
        'stats': {
            'total': total, 'solved': solved, 'attempted': attempted,
            'pending': pending, 'skipped': skipped, 'streak': streak,
            'days_left': days_left, 'today_solved': today_plan_solved,
            'today_target': daily_goal, 'today_pct': today_pct,
        },
        'weekly': {'done_problems': week_plan_solved, 'target_problems': daily_goal * 7},
        'monthly': {'done_problems': month_plan_solved, 'target_problems': daily_goal * last_day},
        'today_plan': today_plan,
        'ai_briefing': ai_briefing,
        'ai_model': ai_model,
        'settings': settings,
    })

# ─── PROBLEMS ─────────────────────────────────────────────────────────────────
@app.route('/api/problems', methods=['GET'])
def get_problems():
    cat    = request.args.get('category', '').strip()
    status = request.args.get('status', '').strip()
    diff   = request.args.get('difficulty', '').strip()
    search = request.args.get('search', '').strip()

    query = "SELECT * FROM problems WHERE 1=1"
    params = []
    if cat:
        query += " AND LOWER(category)=LOWER(?)"
        params.append(cat)
    if status:
        query += " AND status=?"
        params.append(status)
    if diff:
        query += " AND LOWER(difficulty)=LOWER(?)"
        params.append(diff)
    if search:
        # FIX: search across name, topic, AND category
        query += " AND (LOWER(name) LIKE LOWER(?) OR LOWER(topic) LIKE LOWER(?) OR LOWER(category) LIKE LOWER(?))"
        params += [f'%{search}%', f'%{search}%', f'%{search}%']
    query += " ORDER BY category, topic, CASE difficulty WHEN 'Easy' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END"

    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return jsonify(rows_to_list(rows))

@app.route('/api/problems', methods=['POST'])
def add_problem():
    data = request.get_json()
    with get_db() as db:
        db.execute(
            "INSERT INTO problems (name,category,topic,difficulty,platform,problem_link,resource_link,status,scheduled_date) VALUES (?,?,?,?,?,?,?,?,?)",
            (data.get('name',''), data.get('category','DSA'), data.get('topic',''),
             data.get('difficulty','Medium'), data.get('platform','Custom'),
             data.get('problem_link',''), data.get('resource_link',''),
             data.get('status','Pending'), data.get('scheduled_date',''))
        )
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/problems/<int:pid>', methods=['PUT'])
def update_problem(pid):
    data = request.get_json()
    new_status = data.get('status', 'Pending')
    plan_date  = data.get('plan_date', local_today())

    with get_db() as db:
        db.execute("UPDATE problems SET status=? WHERE id=?", (new_status, pid))
        # Update all daily_plan entries for this problem on that date
        db.execute(
            "UPDATE daily_plan SET status=? WHERE problem_id=? AND plan_date=?",
            (new_status, pid, plan_date)
        )
        today_solved = db.execute(
            "SELECT COUNT(*) as c FROM daily_plan WHERE plan_date=? AND status='Solved'", (plan_date,)
        ).fetchone()['c']
        goal = int(get_setting(db, 'daily_goal', '10'))
        db.execute(
            "INSERT OR REPLACE INTO daily_log (log_date, problems_solved, problems_target) VALUES (?,?,?)",
            (plan_date, today_solved, goal)
        )
        db.commit()

    return jsonify({'ok': True, 'status': new_status})

@app.route('/api/problems/<int:pid>', methods=['DELETE'])
def delete_problem(pid):
    with get_db() as db:
        db.execute("DELETE FROM daily_plan WHERE problem_id=?", (pid,))
        db.execute("DELETE FROM problems WHERE id=?", (pid,))
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/problems/delete-batch', methods=['POST'])
def delete_problem_batch():
    data = request.get_json() or {}
    with get_db() as db:
        if 'batch' in data and data['batch']:
            batch_val = data['batch']
            protected_row = db.execute(
                "SELECT protected FROM imports WHERE (filename || '_' || import_date) = ? OR filename = ?",
                (batch_val, batch_val.rsplit('_', 1)[0] if '_' in batch_val else batch_val)
            ).fetchone()
            if protected_row and protected_row['protected']:
                return jsonify({'ok': False, 'error': 'This import batch is protected. Unprotect it in Import History first.'}), 403
            db.execute("DELETE FROM daily_plan WHERE problem_id IN (SELECT id FROM problems WHERE import_batch=?)", (batch_val,))
            db.execute("DELETE FROM problems WHERE import_batch=?", (batch_val,))
            db.execute("DELETE FROM imports WHERE (filename || '_' || import_date) = ?", (batch_val,))
        elif 'category' in data and data['category']:
            db.execute("DELETE FROM daily_plan WHERE problem_id IN (SELECT id FROM problems WHERE LOWER(category)=LOWER(?))", (data['category'],))
            db.execute("DELETE FROM problems WHERE LOWER(category)=LOWER(?)", (data['category'],))
        elif 'date_range' in data and data['date_range']:
            from_d, to_d = data['date_range'][0], data['date_range'][1]
            db.execute("DELETE FROM daily_plan WHERE problem_id IN (SELECT id FROM problems WHERE scheduled_date BETWEEN ? AND ?)", (from_d, to_d))
            db.execute("DELETE FROM problems WHERE scheduled_date BETWEEN ? AND ?", (from_d, to_d))
        db.commit()
    return jsonify({'ok': True})

# ─── CATEGORIES ───────────────────────────────────────────────────────────────
@app.route('/api/categories', methods=['GET'])
def get_categories():
    with get_db() as db:
        rows = db.execute(
            "SELECT DISTINCT category, COUNT(*) as total, SUM(CASE WHEN status='Solved' THEN 1 ELSE 0 END) as solved FROM problems WHERE category!='' GROUP BY category ORDER BY total DESC"
        ).fetchall()
    return jsonify(rows_to_list(rows))

# ─── DAILY PLAN ───────────────────────────────────────────────────────────────
@app.route('/api/daily-plan', methods=['GET'])
def get_daily_plan():
    dt = request.args.get('date', local_today())
    with get_db() as db:
        plan = db.execute('''
            SELECT dp.id as plan_id, dp.problem_id as id, dp.status as plan_status, dp.order_index,
                   p.name, p.category, p.topic, p.difficulty, p.platform,
                   p.problem_link, p.resource_link, p.notes
            FROM daily_plan dp JOIN problems p ON dp.problem_id = p.id
            WHERE dp.plan_date = ? ORDER BY dp.order_index
        ''', (dt,)).fetchall()

    if not plan and dt == local_today():
        generate_daily_plan(dt)
        with get_db() as db:
            plan = db.execute('''
                SELECT dp.id as plan_id, dp.problem_id as id, dp.status as plan_status, dp.order_index,
                       p.name, p.category, p.topic, p.difficulty, p.platform,
                       p.problem_link, p.resource_link, p.notes
                FROM daily_plan dp JOIN problems p ON dp.problem_id = p.id
                WHERE dp.plan_date = ? ORDER BY dp.order_index
            ''', (dt,)).fetchall()

    return jsonify(rows_to_list(plan))

@app.route('/api/daily-plan/refresh', methods=['POST'])
def refresh_daily_plan():
    data = request.get_json() or {}
    dt = data.get('date', local_today())
    with get_db() as db:
        db.execute("DELETE FROM daily_plan WHERE plan_date=?", (dt,))
        db.commit()
    plan = generate_daily_plan(dt)
    return jsonify({'ok': True, 'plan': plan})

# FIX: update_plan_item — returns full updated counts so UI can update without reload
@app.route('/api/daily-plan/<int:plan_id>', methods=['PUT'])
def update_plan_item(plan_id):
    data = request.get_json()
    new_status = data.get('status', 'Pending')
    with get_db() as db:
        row = db.execute("SELECT problem_id, plan_date FROM daily_plan WHERE id=?", (plan_id,)).fetchone()
        if not row:
            return jsonify({'ok': False, 'error': 'Plan item not found'}), 404

        db.execute("UPDATE daily_plan SET status=? WHERE id=?", (new_status, plan_id))
        db.execute("UPDATE problems SET status=? WHERE id=?", (new_status, row['problem_id']))

        today_solved = db.execute(
            "SELECT COUNT(*) as c FROM daily_plan WHERE plan_date=? AND status='Solved'", (row['plan_date'],)
        ).fetchone()['c']
        goal = int(get_setting(db, 'daily_goal', '10'))
        db.execute(
            "INSERT OR REPLACE INTO daily_log (log_date, problems_solved, problems_target) VALUES (?,?,?)",
            (row['plan_date'], today_solved, goal)
        )
        db.commit()

    return jsonify({'ok': True, 'new_status': new_status, 'today_solved': today_solved, 'goal': goal})

# ─── TOPIC ────────────────────────────────────────────────────────────────────
@app.route('/api/topics', methods=['GET'])
def get_topics():
    with get_db() as db:
        rows = db.execute("SELECT DISTINCT topic FROM problems WHERE topic!='' ORDER BY topic").fetchall()
    return jsonify([r['topic'] for r in rows])

@app.route('/api/topic', methods=['GET'])
def get_topic_problems():
    topic = request.args.get('name', '').strip()
    if not topic:
        return jsonify({'error': 'name required'}), 400
    with get_db() as db:
        problems = db.execute(
            """SELECT * FROM problems
               WHERE LOWER(topic) LIKE LOWER(?) OR LOWER(category) LIKE LOWER(?) OR LOWER(name) LIKE LOWER(?)
               ORDER BY CASE difficulty WHEN 'Easy' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END""",
            (f'%{topic}%', f'%{topic}%', f'%{topic}%')
        ).fetchall()
        total = len(problems)
        solved = sum(1 for p in problems if p['status'] == 'Solved')
        algo = db.execute(
            "SELECT * FROM algorithms WHERE LOWER(name) LIKE LOWER(?) OR LOWER(pattern) LIKE LOWER(?)",
            (f'%{topic}%', f'%{topic}%')
        ).fetchone()

    resource_prompt = f"For the topic '{topic}' in DSA/placement preparation, give exactly 3 free resources: 1 YouTube video URL, 1 article URL (GFG or NeetCode), 1 practice page URL. Format as JSON with keys: youtube, article, practice. Only URLs, no explanation."
    ai_resources, _ = ask_ai(resource_prompt)

    try:
        m = re.search(r'\{.*?\}', ai_resources, re.DOTALL)
        resources = json.loads(m.group()) if m else {}
    except Exception:
        resources = {}

    return jsonify({
        'problems': rows_to_list(problems),
        'total': total, 'solved': solved,
        'algorithm': row_to_dict(algo),
        'resources': resources,
    })

# ─── AI ───────────────────────────────────────────────────────────────────────
@app.route('/api/ai/briefing', methods=['POST'])
def ai_briefing():
    feedback, model = generate_daily_briefing()
    return jsonify({'content': feedback, 'model': model})

@app.route('/api/ai/coach', methods=['POST'])
def ai_coach():
    data = request.get_json() or {}
    prompt = data.get('message', 'Give me a placement preparation status update.')
    feedback, model = ask_ai(prompt)
    return jsonify({'content': feedback, 'model': model})

@app.route('/api/ai/coach-feedback', methods=['GET'])
def ai_coach_feedback():
    today = local_today()
    force = request.args.get('force', 'false') == 'true'
    with get_db() as db:
        cached = db.execute(
            "SELECT content, model_used FROM ai_feedback WHERE feedback_date=? AND feedback_type='coach'", (today,)
        ).fetchone()
    if cached and not force:
        return jsonify({'content': cached['content'], 'model': cached['model_used'], 'cached': True})

    feedback, model = ask_ai("Give me my full placement readiness status report for today.")
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO ai_feedback (feedback_date, feedback_type, content, model_used) VALUES (?,?,?,?)",
            (today, 'coach', feedback, model)
        )
        db.commit()
    return jsonify({'content': feedback, 'model': model, 'cached': False})

# ─── NEWS (daily cached, placement+tech only) ──────────────────────────────────
@app.route('/api/news', methods=['GET'])
def get_news():
    force = request.args.get('force', 'false') == 'true'
    try:
        if force:
            with get_db() as db:
                db.execute("DELETE FROM news_cache")
                db.commit()
        articles = fetch_tech_news(limit=9)
        return jsonify({'ok': True, 'articles': articles})
    except Exception as e:
        return jsonify({'ok': False, 'articles': [], 'error': str(e)})

# ─── SETTINGS ─────────────────────────────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
def get_settings():
    with get_db() as db:
        rows = db.execute("SELECT key,value FROM settings").fetchall()
    return jsonify({r['key']: r['value'] for r in rows})

@app.route('/api/settings', methods=['POST'])
def save_settings():
    data = request.get_json()
    with get_db() as db:
        for k, v in data.items():
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (k, str(v)))
        db.commit()
        rows = db.execute("SELECT key,value FROM settings").fetchall()
    return jsonify({'ok': True, 'settings': {r['key']: r['value'] for r in rows}})

# ─── UPLOAD EXCEL ─────────────────────────────────────────────────────────────
@app.route('/api/upload', methods=['POST'])
def upload_excel():
    files = request.files.getlist('file')
    if not files or all(not f.filename for f in files):
        return jsonify({'error': 'No file(s) uploaded'}), 400

    all_tasks, all_sheets, all_filenames = [], [], []

    with get_db() as db:
        daily_goal = int(get_setting(db, 'daily_goal', '10'))

    import pandas as pd
    from collections import Counter

    for f in files:
        if not f.filename:
            continue
        filename = secure_filename(f.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        f.save(filepath)
        try:
            xl = pd.ExcelFile(filepath)
            file_sheets = xl.sheet_names
            all_filenames.append(filename)
            all_sheets.extend([f"{filename}::{s}" for s in file_sheets])
            for sheet_name in file_sheets:
                try:
                    df = xl.parse(sheet_name)
                    df.columns = [str(c).strip() for c in df.columns]
                    if df.empty:
                        continue
                    rows = smart_parse_sheet(df, sheet_name)
                    for row in rows:
                        row['sheet'] = sheet_name
                        row['source_file'] = filename
                        all_tasks.append(row)
                except Exception as e:
                    print(f"Sheet '{sheet_name}' error: {e}")
        except Exception as e:
            return jsonify({'error': f"Failed to read {filename}: {str(e)}"}), 500
        finally:
            import time
            for _ in range(3):
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    break
                except PermissionError:
                    time.sleep(0.3)

    date_counts = Counter(task.get('scheduled_date', '') for task in all_tasks if task.get('scheduled_date'))
    overload_dates = [d for d, c in date_counts.items() if c > daily_goal]

    return jsonify({
        'ok': True, 'tasks': all_tasks, 'count': len(all_tasks),
        'sheets': all_sheets, 'filenames': all_filenames, 'overload_dates': overload_dates
    })

@app.route('/api/import-history', methods=['GET'])
def import_history():
    with get_db() as db:
        rows = db.execute("SELECT * FROM imports ORDER BY id DESC LIMIT 50").fetchall()
    return jsonify(rows_to_list(rows))

@app.route('/api/imports/<int:import_id>/protect', methods=['POST'])
def toggle_import_protection(import_id):
    with get_db() as db:
        row = db.execute("SELECT protected FROM imports WHERE id=?", (import_id,)).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        new_val = 0 if row['protected'] else 1
        db.execute("UPDATE imports SET protected=? WHERE id=?", (new_val, import_id))
        db.commit()
    return jsonify({'ok': True, 'protected': bool(new_val)})

@app.route('/api/imports/clear', methods=['DELETE'])
def clear_imports():
    with get_db() as db:
        db.execute("DELETE FROM daily_plan")
        db.execute("DELETE FROM daily_log")
        db.execute("DELETE FROM problems WHERE import_batch NOT IN (SELECT (filename || '_' || import_date) FROM imports WHERE protected=1)")
        db.execute("DELETE FROM imports WHERE protected=0")
        db.commit()
    for f in os.listdir(UPLOAD_FOLDER):
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, f))
        except Exception:
            pass
    return jsonify({'ok': True})

# ─── ALGORITHMS ───────────────────────────────────────────────────────────────
@app.route('/api/algorithms', methods=['GET'])
def get_algorithms():
    search = request.args.get('search', '').strip()
    query = "SELECT * FROM algorithms WHERE 1=1"
    params = []
    if search:
        query += " AND (LOWER(name) LIKE LOWER(?) OR LOWER(pattern) LIKE LOWER(?) OR LOWER(description) LIKE LOWER(?))"
        params += [f'%{search}%', f'%{search}%', f'%{search}%']
    query += " ORDER BY name"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return jsonify(rows_to_list(rows))

@app.route('/api/algorithms', methods=['POST'])
def add_algorithm():
    data = request.get_json()
    with get_db() as db:
        db.execute(
            "INSERT INTO algorithms (name,pattern,description,when_to_use,youtube_link,article_link) VALUES (?,?,?,?,?,?)",
            (data.get('name',''), data.get('pattern',''), data.get('description',''),
             data.get('when_to_use',''), data.get('youtube_link',''), data.get('article_link',''))
        )
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/algorithms/<int:aid>', methods=['PUT'])
def update_algorithm(aid):
    data = request.get_json()
    with get_db() as db:
        db.execute(
            "UPDATE algorithms SET mastery=?, solved_problems=? WHERE id=?",
            (data.get('mastery','Not Started'), data.get('solved_problems',0), aid)
        )
        db.commit()
    return jsonify({'ok': True})

# ─── PROJECTS ─────────────────────────────────────────────────────────────────
@app.route('/api/projects', methods=['GET'])
def get_projects():
    with get_db() as db:
        rows = db.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    return jsonify(rows_to_list(rows))

@app.route('/api/projects', methods=['POST'])
def add_project():
    data = request.get_json()
    with get_db() as db:
        db.execute(
            "INSERT INTO projects (name,description,tech_stack,target_date,status,github_link,completion_pct) VALUES (?,?,?,?,?,?,?)",
            (data.get('name',''), data.get('description',''), data.get('tech_stack',''),
             data.get('target_date',''), data.get('status','In Progress'),
             data.get('github_link',''), data.get('completion_pct',0))
        )
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/projects/<int:pid>', methods=['PUT'])
def update_project(pid):
    data = request.get_json()
    with get_db() as db:
        db.execute(
            "UPDATE projects SET name=?,description=?,tech_stack=?,target_date=?,status=?,github_link=?,completion_pct=? WHERE id=?",
            (data.get('name',''), data.get('description',''), data.get('tech_stack',''),
             data.get('target_date',''), data.get('status','In Progress'),
             data.get('github_link',''), data.get('completion_pct',0), pid)
        )
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/projects/<int:pid>', methods=['DELETE'])
def delete_project(pid):
    with get_db() as db:
        db.execute("DELETE FROM projects WHERE id=?", (pid,))
        db.commit()
    return jsonify({'ok': True})

# ─── PROGRESS ─────────────────────────────────────────────────────────────────
@app.route('/api/progress', methods=['GET'])
def get_progress():
    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT key,value FROM settings").fetchall()}
        daily_goal = int(settings.get('daily_goal', 10))
        deadline = settings.get('placement_deadline', '2026-10-01')
        days_left = max(0, (date.fromisoformat(deadline) - date.today()).days)
        total   = db.execute("SELECT COUNT(*) as c FROM problems").fetchone()['c']
        solved  = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Solved'").fetchone()['c']
        pending = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Pending'").fetchone()['c']
        skipped = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Skipped'").fetchone()['c']
        cats = db.execute("SELECT category, COUNT(*) as total, SUM(CASE WHEN status='Solved' THEN 1 ELSE 0 END) as solved FROM problems GROUP BY category ORDER BY total DESC").fetchall()
        logs = db.execute("SELECT * FROM daily_log ORDER BY log_date DESC LIMIT 14").fetchall()
    return jsonify({
        'total': total, 'solved': solved, 'pending': pending, 'skipped': skipped,
        'days_left': days_left, 'daily_goal': daily_goal,
        'categories': rows_to_list(cats), 'daily_logs': rows_to_list(logs),
    })

@app.route('/api/log-activity', methods=['POST'])
def log_activity():
    data = request.get_json()
    log_date = data.get('date', local_today())
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO daily_log (log_date, problems_solved, problems_attempted, problems_skipped, study_hours, mood, notes, problems_target) VALUES (?,?,?,?,?,?,?,?)",
            (log_date, data.get('problems_solved', 0), data.get('problems_attempted', 0),
             data.get('problems_skipped', 0), data.get('study_hours', 0),
             data.get('mood', ''), data.get('notes', ''),
             int(get_setting(db, 'daily_goal', '10')))
        )
        db.commit()
    return jsonify({'ok': True})

# ─── COURSES ──────────────────────────────────────────────────────────────────
@app.route('/api/courses', methods=['GET'])
def get_courses():
    with get_db() as db:
        rows = db.execute("SELECT * FROM courses ORDER BY id").fetchall()
    return jsonify(rows_to_list(rows))

@app.route('/api/courses/<int:cid>/topics', methods=['GET'])
def get_course_topics(cid):
    with get_db() as db:
        rows = db.execute("SELECT * FROM course_topics WHERE course_id=? ORDER BY order_index, id", (cid,)).fetchall()
    return jsonify(rows_to_list(rows))

@app.route('/api/courses/<int:cid>/topics/<int:tid>', methods=['PUT'])
def update_course_topic(cid, tid):
    data = request.get_json()
    with get_db() as db:
        db.execute(
            "UPDATE course_topics SET status=?, completed_at=? WHERE id=? AND course_id=?",
            (data.get('status','Not Started'),
             local_today() if data.get('status') == 'Completed' else '', tid, cid)
        )
        completed = db.execute("SELECT COUNT(*) as c FROM course_topics WHERE course_id=? AND status='Completed'", (cid,)).fetchone()['c']
        total_topics = db.execute("SELECT COUNT(*) as c FROM course_topics WHERE course_id=?", (cid,)).fetchone()['c']
        db.execute("UPDATE courses SET completed_topics=?, total_topics=? WHERE id=?", (completed, total_topics, cid))
        db.commit()
    return jsonify({'ok': True})

# ─── STATS ────────────────────────────────────────────────────────────────────
@app.route('/api/stats', methods=['GET'])
def get_stats():
    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT key,value FROM settings").fetchall()}
        daily_goal = int(settings.get('daily_goal', 10))
        deadline = settings.get('placement_deadline', '2026-10-01')
        days_left = max(0, (date.fromisoformat(deadline) - date.today()).days)

        total    = db.execute("SELECT COUNT(*) as c FROM problems").fetchone()['c']
        solved   = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Solved'").fetchone()['c']
        pending  = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Pending'").fetchone()['c']
        skipped  = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Skipped'").fetchone()['c']
        attempted= db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Attempted'").fetchone()['c']

        streak = 0
        check = date.today() - timedelta(days=1)
        for _ in range(365):
            row = db.execute("SELECT problems_solved FROM daily_log WHERE log_date=?", (check.isoformat(),)).fetchone()
            if row and row['problems_solved'] >= 1:
                streak += 1
                check -= timedelta(days=1)
            else:
                break

        solved_pct = round(solved / total * 100) if total else 0
        cats = db.execute("SELECT category, COUNT(*) as total, SUM(CASE WHEN status='Solved' THEN 1 ELSE 0 END) as solved FROM problems GROUP BY category").fetchall()
        cats_with_solved = sum(1 for c in cats if c['solved'] > 0)
        cats_total = len(cats) if cats else 1
        cat_coverage_pct = round(cats_with_solved / cats_total * 100) if cats_total else 0
        readiness = min(100, round(solved_pct * 0.60 + cat_coverage_pct * 0.20 + min(streak, 20)))

        remaining = pending + attempted
        needed_per_day = round(remaining / days_left, 1) if days_left > 0 else remaining

        daily_data = []
        for i in range(29, -1, -1):
            d_str = (date.today() - timedelta(days=i)).isoformat()
            row = db.execute("SELECT problems_solved, problems_target FROM daily_log WHERE log_date=?", (d_str,)).fetchone()
            label = (date.today() - timedelta(days=i)).strftime('%d %b')
            daily_data.append({
                'date': d_str, 'label': label,
                'solved': row['problems_solved'] if row else 0,
                'target': row['problems_target'] if row else daily_goal,
            })

        ai_row = db.execute("SELECT content FROM ai_feedback WHERE feedback_date=? AND feedback_type='weekly'", (local_today(),)).fetchone()
        weekly_ai_report = ai_row['content'] if ai_row else None

    return jsonify({
        'total': total, 'solved': solved, 'pending': pending,
        'skipped': skipped, 'attempted': attempted, 'streak': streak,
        'readiness': readiness, 'days_left': days_left, 'needed_per_day': needed_per_day,
        'daily_goal': daily_goal, 'categories': rows_to_list(cats),
        'daily_data': daily_data, 'weekly_ai_report': weekly_ai_report,
    })

# ─── MILESTONES ───────────────────────────────────────────────────────────────
@app.route('/api/projects/<int:pid>/milestones', methods=['GET'])
def get_milestones(pid):
    with get_db() as db:
        rows = db.execute("SELECT * FROM milestones WHERE project_id=? ORDER BY order_index, id", (pid,)).fetchall()
    return jsonify(rows_to_list(rows))

@app.route('/api/projects/<int:pid>/milestones', methods=['POST'])
def add_milestone(pid):
    data = request.get_json()
    with get_db() as db:
        db.execute(
            "INSERT INTO milestones (project_id, name, description, deadline, status, order_index) VALUES (?,?,?,?,?,?)",
            (pid, data.get('name',''), data.get('description',''), data.get('deadline',''), data.get('status','Pending'), data.get('order_index', 0))
        )
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/milestones/<int:mid>', methods=['PUT'])
def update_milestone(mid):
    data = request.get_json()
    with get_db() as db:
        db.execute(
            "UPDATE milestones SET status=?, name=?, deadline=? WHERE id=?",
            (data.get('status','Pending'), data.get('name',''), data.get('deadline',''), mid)
        )
        row = db.execute("SELECT project_id FROM milestones WHERE id=?", (mid,)).fetchone()
        if row:
            pid = row['project_id']
            total_ms = db.execute("SELECT COUNT(*) as c FROM milestones WHERE project_id=?", (pid,)).fetchone()['c']
            done_ms  = db.execute("SELECT COUNT(*) as c FROM milestones WHERE project_id=? AND status='Done'", (pid,)).fetchone()['c']
            pct = round(done_ms / total_ms * 100) if total_ms else 0
            db.execute("UPDATE projects SET completion_pct=? WHERE id=?", (pct, pid))
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/milestones/<int:mid>', methods=['DELETE'])
def delete_milestone(mid):
    with get_db() as db:
        row = db.execute("SELECT project_id FROM milestones WHERE id=?", (mid,)).fetchone()
        db.execute("DELETE FROM milestones WHERE id=?", (mid,))
        if row:
            pid = row['project_id']
            total_ms = db.execute("SELECT COUNT(*) as c FROM milestones WHERE project_id=?", (pid,)).fetchone()['c']
            done_ms  = db.execute("SELECT COUNT(*) as c FROM milestones WHERE project_id=? AND status='Done'", (pid,)).fetchone()['c']
            pct = round(done_ms / total_ms * 100) if total_ms else 0
            db.execute("UPDATE projects SET completion_pct=? WHERE id=?", (pct, pid))
        db.commit()
    return jsonify({'ok': True})

# ─── IMPORT ───────────────────────────────────────────────────────────────────
@app.route('/api/import', methods=['POST'])
def import_problems():
    data = request.get_json()
    tasks = data.get('tasks', [])
    mode = data.get('mode', 'add')
    filename = data.get('filename', 'import')
    filenames = data.get('filenames', [filename])
    batch_id = f"{filename}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    imported = 0
    skipped_dupes = 0

    with get_db() as db:
        if mode == 'replace':
            db.execute("DELETE FROM daily_plan WHERE problem_id IN (SELECT id FROM problems WHERE import_batch NOT IN (SELECT (filename || '_' || import_date) FROM imports WHERE protected=1))")
            db.execute("DELETE FROM problems WHERE import_batch NOT IN (SELECT (filename || '_' || import_date) FROM imports WHERE protected=1)")

        for task in tasks:
            name = task.get('name', '').strip()
            if not name:
                continue
            existing = db.execute("SELECT id FROM problems WHERE name=? AND category=?", (name, task.get('category','DSA'))).fetchone()
            if existing and mode != 'replace':
                skipped_dupes += 1
                continue
            db.execute(
                "INSERT INTO problems (name,category,topic,difficulty,platform,problem_link,resource_link,status,scheduled_date,import_batch) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (name, task.get('category','DSA'), task.get('topic',''), task.get('difficulty','Medium'),
                 task.get('platform','Custom'), task.get('problem_link',''), task.get('resource_link',''),
                 'Pending', task.get('scheduled_date',''), batch_id)
            )
            imported += 1

        for fname in (filenames if filenames else [filename]):
            db.execute("INSERT INTO imports (filename, import_date, total_imported, category) VALUES (?,?,?,?)",
                       (fname, local_today(), imported, ''))
        db.commit()

    return jsonify({'ok': True, 'imported': imported, 'skipped': skipped_dupes, 'batch': batch_id})

# ─── STATIC ───────────────────────────────────────────────────────────────────
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
