import os
import sys
import json
import re
from datetime import date, timedelta, datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
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

# ─── LOGIN DECORATOR ──────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def row_to_dict(row):
    return dict(row) if row else None

def rows_to_list(rows):
    return [dict(r) for r in rows]

def get_setting(db, key, default='', user_id=None):
    if user_id is None:
        user_id = session.get('user_id')
    row = db.execute("SELECT value FROM settings WHERE key=? AND user_id=?", (key, user_id)).fetchone()
    return row['value'] if row else default

def local_today():
    return date.today().isoformat()

# ─── INIT ─────────────────────────────────────────────────────────────────────
init_db()

# ─── AUTH ROUTES ──────────────────────────────────────────────────────────────
@app.route('/signup')
def signup_page():
    return render_template('signup.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.get_json()
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not username or not email or not password:
        return jsonify({'error': 'All fields are required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    hashed = generate_password_hash(password)
    with get_db() as db:
        existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            return jsonify({'error': 'Email already registered'}), 400

        cur = db.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?,?,?)",
            (username, email, hashed)
        )
        user_id = cur.lastrowid

        # Migrate any existing data (user_id NULL) to this user
        tables = ['problems', 'daily_log', 'daily_plan', 'projects', 'imports', 'ai_feedback', 'weekly_goals', 'monthly_goals']
        for table in tables:
            db.execute(f"UPDATE {table} SET user_id=? WHERE user_id IS NULL", (user_id,))

        defaults = {
            'name': username,
            'daily_goal': '10',
            'placement_deadline': '2026-10-01',
            'study_hours': '4',
            'target_companies': 'Service Based,Product Based',
            'groq_api_key': '',
            'gemini_api_key': '',
            'openrouter_api_key': '',
            'ai_provider': 'groq',
            'dark_mode': 'false',
            'reminder_time': '09:00',
            'onboarded': 'false'
        }
        for k, v in defaults.items():
            db.execute("INSERT OR IGNORE INTO settings (user_id, key, value) VALUES (?,?,?)", (user_id, k, v))

        db.commit()

    session['user_id'] = user_id
    session['username'] = username
    return jsonify({'ok': True})

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    with get_db() as db:
        user = db.execute("SELECT id, username, password_hash FROM users WHERE email=?", (email,)).fetchone()
        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401
        if not check_password_hash(user['password_hash'], password):
            return jsonify({'error': 'Invalid email or password'}), 401

        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({'ok': True})

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ─── MAIN PAGE ────────────────────────────────────────────────────────────────
@app.route('/')
@login_required
def index():
    return render_template('index.html')

# ─── DASHBOARD ────────────────────────────────────────────────────────────────
@app.route('/api/dashboard', methods=['GET'])
@login_required
def dashboard():
    user_id = session['user_id']
    today = local_today()
    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT key,value FROM settings WHERE user_id=?", (user_id,)).fetchall()}
        daily_goal = int(settings.get('daily_goal', 10))
        placement_deadline = settings.get('placement_deadline', '2026-10-01')
        days_left = max(0, (date.fromisoformat(placement_deadline) - date.today()).days)

        total     = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=?", (user_id,)).fetchone()['c']
        solved    = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=? AND status='Solved'", (user_id,)).fetchone()['c']
        attempted = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=? AND status='Attempted'", (user_id,)).fetchone()['c']
        pending   = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=? AND status='Pending'", (user_id,)).fetchone()['c']
        skipped   = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=? AND status='Skipped'", (user_id,)).fetchone()['c']

        streak = 0
        check = date.today() - timedelta(days=1)
        for _ in range(365):
            row = db.execute("SELECT problems_solved FROM daily_log WHERE user_id=? AND log_date=?", (user_id, check.isoformat())).fetchone()
            if row and row['problems_solved'] >= 1:
                streak += 1
                check -= timedelta(days=1)
            else:
                break

        today_plan_solved = db.execute(
            "SELECT COUNT(*) as c FROM daily_plan WHERE user_id=? AND plan_date=? AND status='Solved'",
            (user_id, today)
        ).fetchone()['c']
        today_pct = min(100, round(today_plan_solved / daily_goal * 100)) if daily_goal else 0

        import calendar
        week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        week_end   = (date.today() + timedelta(days=6 - date.today().weekday())).isoformat()
        week_plan_solved = db.execute(
            "SELECT COUNT(*) as c FROM daily_plan WHERE user_id=? AND plan_date>=? AND plan_date<=? AND status='Solved'",
            (user_id, week_start, week_end)
        ).fetchone()['c']

        month_start = date.today().replace(day=1).isoformat()
        last_day = calendar.monthrange(date.today().year, date.today().month)[1]
        month_end = date.today().replace(day=last_day).isoformat()
        month_plan_solved = db.execute(
            "SELECT COUNT(*) as c FROM daily_plan WHERE user_id=? AND plan_date>=? AND plan_date<=? AND status='Solved'",
            (user_id, month_start, month_end)
        ).fetchone()['c']

        ai_row = db.execute(
            "SELECT content, model_used FROM ai_feedback WHERE user_id=? AND feedback_date=? AND feedback_type='daily'",
            (user_id, today)
        ).fetchone()
        ai_briefing = ai_row['content'] if ai_row else None
        ai_model    = ai_row['model_used'] if ai_row else None

    # Get full today's plan (no limit)
    today_plan = get_todays_plan(today, user_id)

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
@login_required
def get_problems():
    user_id = session['user_id']
    cat    = request.args.get('category', '').strip()
    status = request.args.get('status', '').strip()
    diff   = request.args.get('difficulty', '').strip()
    search = request.args.get('search', '').strip()

    query = "SELECT * FROM problems WHERE user_id=? AND 1=1"
    params = [user_id]
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
        query += " AND (LOWER(name) LIKE LOWER(?) OR LOWER(topic) LIKE LOWER(?) OR LOWER(category) LIKE LOWER(?))"
        params += [f'%{search}%', f'%{search}%', f'%{search}%']
    query += " ORDER BY category, topic, CASE difficulty WHEN 'Easy' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END"

    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return jsonify(rows_to_list(rows))

@app.route('/api/problems', methods=['POST'])
@login_required
def add_problem():
    user_id = session['user_id']
    data = request.get_json()
    with get_db() as db:
        db.execute(
            "INSERT INTO problems (user_id, name,category,topic,difficulty,platform,problem_link,resource_link,status,scheduled_date) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (user_id, data.get('name',''), data.get('category','DSA'), data.get('topic',''),
             data.get('difficulty','Medium'), data.get('platform','Custom'),
             data.get('problem_link',''), data.get('resource_link',''),
             data.get('status','Pending'), data.get('scheduled_date',''))
        )
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/problems/<int:pid>', methods=['PUT'])
@login_required
def update_problem(pid):
    user_id = session['user_id']
    data = request.get_json()
    new_status = data.get('status', 'Pending')
    plan_date  = data.get('plan_date', local_today())

    with get_db() as db:
        problem = db.execute("SELECT id FROM problems WHERE id=? AND user_id=?", (pid, user_id)).fetchone()
        if not problem:
            return jsonify({'error': 'Not found'}), 404
        db.execute("UPDATE problems SET status=? WHERE id=?", (new_status, pid))
        db.execute(
            "UPDATE daily_plan SET status=? WHERE problem_id=? AND plan_date=? AND user_id=?",
            (new_status, pid, plan_date, user_id)
        )
        today_solved = db.execute(
            "SELECT COUNT(*) as c FROM daily_plan WHERE user_id=? AND plan_date=? AND status='Solved'",
            (user_id, plan_date)
        ).fetchone()['c']
        goal = int(get_setting(db, 'daily_goal', '10', user_id))
        db.execute(
            "INSERT OR REPLACE INTO daily_log (user_id, log_date, problems_solved, problems_target) VALUES (?,?,?,?)",
            (user_id, plan_date, today_solved, goal)
        )
        db.commit()

    return jsonify({'ok': True, 'status': new_status})

@app.route('/api/problems/<int:pid>', methods=['DELETE'])
@login_required
def delete_problem(pid):
    user_id = session['user_id']
    with get_db() as db:
        db.execute("DELETE FROM daily_plan WHERE problem_id=? AND user_id=?", (pid, user_id))
        db.execute("DELETE FROM problems WHERE id=? AND user_id=?", (pid, user_id))
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/problems/delete-batch', methods=['POST'])
@login_required
def delete_problem_batch():
    user_id = session['user_id']
    data = request.get_json() or {}
    with get_db() as db:
        if 'batch' in data and data['batch']:
            batch_val = data['batch']
            protected_row = db.execute(
                "SELECT protected FROM imports WHERE user_id=? AND (filename || '_' || import_date) = ? OR filename = ?",
                (user_id, batch_val, batch_val.rsplit('_', 1)[0] if '_' in batch_val else batch_val)
            ).fetchone()
            if protected_row and protected_row['protected']:
                return jsonify({'ok': False, 'error': 'This import batch is protected. Unprotect it in Import History first.'}), 403
            db.execute("DELETE FROM daily_plan WHERE user_id=? AND problem_id IN (SELECT id FROM problems WHERE user_id=? AND import_batch=?)", (user_id, user_id, batch_val))
            db.execute("DELETE FROM problems WHERE user_id=? AND import_batch=?", (user_id, batch_val))
            db.execute("DELETE FROM imports WHERE user_id=? AND (filename || '_' || import_date) = ?", (user_id, batch_val))
        elif 'category' in data and data['category']:
            db.execute("DELETE FROM daily_plan WHERE user_id=? AND problem_id IN (SELECT id FROM problems WHERE user_id=? AND LOWER(category)=LOWER(?))", (user_id, user_id, data['category']))
            db.execute("DELETE FROM problems WHERE user_id=? AND LOWER(category)=LOWER(?)", (user_id, data['category']))
        elif 'date_range' in data and data['date_range']:
            from_d, to_d = data['date_range'][0], data['date_range'][1]
            db.execute("DELETE FROM daily_plan WHERE user_id=? AND problem_id IN (SELECT id FROM problems WHERE user_id=? AND scheduled_date BETWEEN ? AND ?)", (user_id, user_id, from_d, to_d))
            db.execute("DELETE FROM problems WHERE user_id=? AND scheduled_date BETWEEN ? AND ?", (user_id, from_d, to_d))
        db.commit()
    return jsonify({'ok': True})

# ─── CATEGORIES ───────────────────────────────────────────────────────────────
@app.route('/api/categories', methods=['GET'])
@login_required
def get_categories():
    user_id = session['user_id']
    with get_db() as db:
        rows = db.execute(
            "SELECT DISTINCT category, COUNT(*) as total, SUM(CASE WHEN status='Solved' THEN 1 ELSE 0 END) as solved FROM problems WHERE user_id=? AND category!='' GROUP BY category ORDER BY total DESC",
            (user_id,)
        ).fetchall()
    return jsonify(rows_to_list(rows))

# ─── DAILY PLAN ───────────────────────────────────────────────────────────────
@app.route('/api/daily-plan', methods=['GET'])
@login_required
def get_daily_plan():
    user_id = session['user_id']
    dt = request.args.get('date', local_today())
    # Check if plan exists for this date, if not generate it (based on scheduled_date)
    with get_db() as db:
        exists = db.execute("SELECT COUNT(*) as c FROM daily_plan WHERE user_id=? AND plan_date=?", (user_id, dt)).fetchone()['c']
    if not exists:
        generate_daily_plan(dt, user_id)
    with get_db() as db:
        plan = db.execute('''
            SELECT dp.id as plan_id, dp.problem_id as id, dp.status as plan_status, dp.order_index,
                   p.name, p.category, p.topic, p.difficulty, p.platform,
                   p.problem_link, p.resource_link, p.notes
            FROM daily_plan dp JOIN problems p ON dp.problem_id = p.id
            WHERE dp.user_id=? AND dp.plan_date = ? ORDER BY dp.order_index
        ''', (user_id, dt)).fetchall()
    return jsonify(rows_to_list(plan))

@app.route('/api/daily-plan/refresh', methods=['POST'])
@login_required
def refresh_daily_plan():
    user_id = session['user_id']
    data = request.get_json() or {}
    dt = data.get('date', local_today())
    with get_db() as db:
        db.execute("DELETE FROM daily_plan WHERE user_id=? AND plan_date=?", (user_id, dt))
        db.commit()
    generate_daily_plan(dt, user_id)
    return jsonify({'ok': True})

@app.route('/api/daily-plan/<int:plan_id>', methods=['PUT'])
@login_required
def update_plan_item(plan_id):
    user_id = session['user_id']
    data = request.get_json()
    new_status = data.get('status', 'Pending')
    with get_db() as db:
        row = db.execute("SELECT problem_id, plan_date FROM daily_plan WHERE id=? AND user_id=?", (plan_id, user_id)).fetchone()
        if not row:
            return jsonify({'ok': False, 'error': 'Plan item not found'}), 404

        db.execute("UPDATE daily_plan SET status=? WHERE id=? AND user_id=?", (new_status, plan_id, user_id))
        db.execute("UPDATE problems SET status=? WHERE id=? AND user_id=?", (new_status, row['problem_id'], user_id))

        today_solved = db.execute(
            "SELECT COUNT(*) as c FROM daily_plan WHERE user_id=? AND plan_date=? AND status='Solved'",
            (user_id, row['plan_date'])
        ).fetchone()['c']
        goal = int(get_setting(db, 'daily_goal', '10', user_id))
        db.execute(
            "INSERT OR REPLACE INTO daily_log (user_id, log_date, problems_solved, problems_target) VALUES (?,?,?,?)",
            (user_id, row['plan_date'], today_solved, goal)
        )
        db.commit()

    return jsonify({'ok': True, 'new_status': new_status, 'today_solved': today_solved, 'goal': goal})

# ─── TOPIC ────────────────────────────────────────────────────────────────────
@app.route('/api/topics', methods=['GET'])
@login_required
def get_topics():
    user_id = session['user_id']
    with get_db() as db:
        rows = db.execute("SELECT DISTINCT topic FROM problems WHERE user_id=? AND topic!='' ORDER BY topic", (user_id,)).fetchall()
    return jsonify([r['topic'] for r in rows])

@app.route('/api/topic', methods=['GET'])
@login_required
def get_topic_problems():
    user_id = session['user_id']
    topic = request.args.get('name', '').strip()
    if not topic:
        return jsonify({'error': 'name required'}), 400
    with get_db() as db:
        problems = db.execute(
            """SELECT * FROM problems WHERE user_id=?
               AND (LOWER(topic) LIKE LOWER(?) OR LOWER(category) LIKE LOWER(?) OR LOWER(name) LIKE LOWER(?))
               ORDER BY CASE difficulty WHEN 'Easy' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END""",
            (user_id, f'%{topic}%', f'%{topic}%', f'%{topic}%')
        ).fetchall()
        total = len(problems)
        solved = sum(1 for p in problems if p['status'] == 'Solved')
        algo = db.execute(
            "SELECT * FROM algorithms WHERE LOWER(name) LIKE LOWER(?) OR LOWER(pattern) LIKE LOWER(?)",
            (f'%{topic}%', f'%{topic}%')
        ).fetchone()

    resource_prompt = f"For the topic '{topic}' in DSA/placement preparation, give exactly 3 free resources: 1 YouTube video URL, 1 article URL (GFG or NeetCode), 1 practice page URL. Format as JSON with keys: youtube, article, practice. Only URLs, no explanation."
    ai_resources, _ = ask_ai(resource_prompt, user_id=user_id)

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
@login_required
def ai_briefing():
    user_id = session['user_id']
    feedback, model = generate_daily_briefing(user_id)
    return jsonify({'content': feedback, 'model': model})

@app.route('/api/ai/coach', methods=['POST'])
@login_required
def ai_coach():
    user_id = session['user_id']
    data = request.get_json() or {}
    prompt = data.get('message', 'Give me a placement preparation status update.')
    feedback, model = ask_ai(prompt, user_id=user_id)
    return jsonify({'content': feedback, 'model': model})

@app.route('/api/ai/coach-feedback', methods=['GET'])
@login_required
def ai_coach_feedback():
    user_id = session['user_id']
    today = local_today()
    force = request.args.get('force', 'false') == 'true'
    with get_db() as db:
        cached = db.execute(
            "SELECT content, model_used FROM ai_feedback WHERE user_id=? AND feedback_date=? AND feedback_type='coach'",
            (user_id, today)
        ).fetchone()
    if cached and not force:
        return jsonify({'content': cached['content'], 'model': cached['model_used'], 'cached': True})

    feedback, model = ask_ai("Give me my full placement readiness status report for today.", user_id=user_id)
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO ai_feedback (user_id, feedback_date, feedback_type, content, model_used) VALUES (?,?,?,?,?)",
            (user_id, today, 'coach', feedback, model)
        )
        db.commit()
    return jsonify({'content': feedback, 'model': model, 'cached': False})

# ─── NEWS ─────────────────────────────────────────────────────────────────────
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
@login_required
def get_settings():
    user_id = session['user_id']
    with get_db() as db:
        rows = db.execute("SELECT key,value FROM settings WHERE user_id=?", (user_id,)).fetchall()
    return jsonify({r['key']: r['value'] for r in rows})

@app.route('/api/settings', methods=['POST'])
@login_required
def save_settings():
    user_id = session['user_id']
    data = request.get_json()
    with get_db() as db:
        for k, v in data.items():
            db.execute("INSERT OR REPLACE INTO settings (user_id, key, value) VALUES (?,?,?)", (user_id, k, str(v)))
        db.commit()
        rows = db.execute("SELECT key,value FROM settings WHERE user_id=?", (user_id,)).fetchall()
    return jsonify({'ok': True, 'settings': {r['key']: r['value'] for r in rows}})

# ─── UPLOAD EXCEL ─────────────────────────────────────────────────────────────
@app.route('/api/upload', methods=['POST'])
@login_required
def upload_excel():
    user_id = session['user_id']
    files = request.files.getlist('file')
    if not files or all(not f.filename for f in files):
        return jsonify({'error': 'No file(s) uploaded'}), 400

    all_tasks, all_sheets, all_filenames = [], [], []

    import pandas as pd

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

    return jsonify({
        'ok': True, 'tasks': all_tasks, 'count': len(all_tasks),
        'sheets': all_sheets, 'filenames': all_filenames,
    })

@app.route('/api/import-history', methods=['GET'])
@login_required
def import_history():
    user_id = session['user_id']
    with get_db() as db:
        rows = db.execute("SELECT * FROM imports WHERE user_id=? ORDER BY id DESC LIMIT 50", (user_id,)).fetchall()
    return jsonify(rows_to_list(rows))

@app.route('/api/imports/<int:import_id>/protect', methods=['POST'])
@login_required
def toggle_import_protection(import_id):
    user_id = session['user_id']
    with get_db() as db:
        row = db.execute("SELECT protected FROM imports WHERE id=? AND user_id=?", (import_id, user_id)).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        new_val = 0 if row['protected'] else 1
        db.execute("UPDATE imports SET protected=? WHERE id=? AND user_id=?", (new_val, import_id, user_id))
        db.commit()
    return jsonify({'ok': True, 'protected': bool(new_val)})

@app.route('/api/imports/clear', methods=['DELETE'])
@login_required
def clear_imports():
    user_id = session['user_id']
    with get_db() as db:
        db.execute("DELETE FROM daily_plan WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM daily_log WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM problems WHERE user_id=? AND import_batch NOT IN (SELECT (filename || '_' || import_date) FROM imports WHERE user_id=? AND protected=1)", (user_id, user_id))
        db.execute("DELETE FROM imports WHERE user_id=? AND protected=0", (user_id,))
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

@app.route('/api/algorithms/<int:aid>', methods=['PUT'])
@login_required
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
@login_required
def get_projects():
    user_id = session['user_id']
    with get_db() as db:
        rows = db.execute("SELECT * FROM projects WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()
    return jsonify(rows_to_list(rows))

@app.route('/api/projects', methods=['POST'])
@login_required
def add_project():
    user_id = session['user_id']
    data = request.get_json()
    with get_db() as db:
        db.execute(
            "INSERT INTO projects (user_id, name,description,tech_stack,target_date,status,github_link,completion_pct) VALUES (?,?,?,?,?,?,?,?)",
            (user_id, data.get('name',''), data.get('description',''), data.get('tech_stack',''),
             data.get('target_date',''), data.get('status','In Progress'),
             data.get('github_link',''), data.get('completion_pct',0))
        )
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/projects/<int:pid>', methods=['PUT'])
@login_required
def update_project(pid):
    user_id = session['user_id']
    data = request.get_json()
    with get_db() as db:
        db.execute(
            "UPDATE projects SET name=?,description=?,tech_stack=?,target_date=?,status=?,github_link=?,completion_pct=? WHERE id=? AND user_id=?",
            (data.get('name',''), data.get('description',''), data.get('tech_stack',''),
             data.get('target_date',''), data.get('status','In Progress'),
             data.get('github_link',''), data.get('completion_pct',0), pid, user_id)
        )
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/projects/<int:pid>', methods=['DELETE'])
@login_required
def delete_project(pid):
    user_id = session['user_id']
    with get_db() as db:
        db.execute("DELETE FROM projects WHERE id=? AND user_id=?", (pid, user_id))
        db.commit()
    return jsonify({'ok': True})

# ─── PROGRESS ─────────────────────────────────────────────────────────────────
@app.route('/api/progress', methods=['GET'])
@login_required
def get_progress():
    user_id = session['user_id']
    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT key,value FROM settings WHERE user_id=?", (user_id,)).fetchall()}
        daily_goal = int(settings.get('daily_goal', 10))
        deadline = settings.get('placement_deadline', '2026-10-01')
        days_left = max(0, (date.fromisoformat(deadline) - date.today()).days)
        total   = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=?", (user_id,)).fetchone()['c']
        solved  = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=? AND status='Solved'", (user_id,)).fetchone()['c']
        pending = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=? AND status='Pending'", (user_id,)).fetchone()['c']
        skipped = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=? AND status='Skipped'", (user_id,)).fetchone()['c']
        cats = db.execute("SELECT category, COUNT(*) as total, SUM(CASE WHEN status='Solved' THEN 1 ELSE 0 END) as solved FROM problems WHERE user_id=? GROUP BY category ORDER BY total DESC", (user_id,)).fetchall()
        logs = db.execute("SELECT * FROM daily_log WHERE user_id=? ORDER BY log_date DESC LIMIT 14", (user_id,)).fetchall()
    return jsonify({
        'total': total, 'solved': solved, 'pending': pending, 'skipped': skipped,
        'days_left': days_left, 'daily_goal': daily_goal,
        'categories': rows_to_list(cats), 'daily_logs': rows_to_list(logs),
    })

@app.route('/api/log-activity', methods=['POST'])
@login_required
def log_activity():
    user_id = session['user_id']
    data = request.get_json()
    log_date = data.get('date', local_today())
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO daily_log (user_id, log_date, problems_solved, problems_attempted, problems_skipped, study_hours, mood, notes, problems_target) VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, log_date, data.get('problems_solved', 0), data.get('problems_attempted', 0),
             data.get('problems_skipped', 0), data.get('study_hours', 0),
             data.get('mood', ''), data.get('notes', ''),
             int(get_setting(db, 'daily_goal', '10', user_id)))
        )
        db.commit()
    return jsonify({'ok': True})

# ─── STATS ────────────────────────────────────────────────────────────────────
@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    user_id = session['user_id']
    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT key,value FROM settings WHERE user_id=?", (user_id,)).fetchall()}
        daily_goal = int(settings.get('daily_goal', 10))
        deadline = settings.get('placement_deadline', '2026-10-01')
        days_left = max(0, (date.fromisoformat(deadline) - date.today()).days)

        total    = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=?", (user_id,)).fetchone()['c']
        solved   = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=? AND status='Solved'", (user_id,)).fetchone()['c']
        pending  = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=? AND status='Pending'", (user_id,)).fetchone()['c']
        skipped  = db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=? AND status='Skipped'", (user_id,)).fetchone()['c']
        attempted= db.execute("SELECT COUNT(*) as c FROM problems WHERE user_id=? AND status='Attempted'", (user_id,)).fetchone()['c']

        streak = 0
        check = date.today() - timedelta(days=1)
        for _ in range(365):
            row = db.execute("SELECT problems_solved FROM daily_log WHERE user_id=? AND log_date=?", (user_id, check.isoformat())).fetchone()
            if row and row['problems_solved'] >= 1:
                streak += 1
                check -= timedelta(days=1)
            else:
                break

        solved_pct = round(solved / total * 100) if total else 0
        cats = db.execute("SELECT category, COUNT(*) as total, SUM(CASE WHEN status='Solved' THEN 1 ELSE 0 END) as solved FROM problems WHERE user_id=? GROUP BY category", (user_id,)).fetchall()
        cats_with_solved = sum(1 for c in cats if c['solved'] > 0)
        cats_total = len(cats) if cats else 1
        cat_coverage_pct = round(cats_with_solved / cats_total * 100) if cats_total else 0
        readiness = min(100, round(solved_pct * 0.60 + cat_coverage_pct * 0.20 + min(streak, 20)))

        remaining = pending + attempted
        needed_per_day = round(remaining / days_left, 1) if days_left > 0 else remaining

        daily_data = []
        for i in range(29, -1, -1):
            d_str = (date.today() - timedelta(days=i)).isoformat()
            row = db.execute("SELECT problems_solved, problems_target FROM daily_log WHERE user_id=? AND log_date=?", (user_id, d_str)).fetchone()
            label = (date.today() - timedelta(days=i)).strftime('%d %b')
            daily_data.append({
                'date': d_str, 'label': label,
                'solved': row['problems_solved'] if row else 0,
                'target': row['problems_target'] if row else daily_goal,
            })

        ai_row = db.execute("SELECT content FROM ai_feedback WHERE user_id=? AND feedback_date=? AND feedback_type='weekly'", (user_id, local_today())).fetchone()
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
@login_required
def get_milestones(pid):
    user_id = session['user_id']
    with get_db() as db:
        rows = db.execute("SELECT * FROM milestones WHERE project_id=? AND project_id IN (SELECT id FROM projects WHERE user_id=?) ORDER BY order_index, id", (pid, user_id)).fetchall()
    return jsonify(rows_to_list(rows))

@app.route('/api/projects/<int:pid>/milestones', methods=['POST'])
@login_required
def add_milestone(pid):
    user_id = session['user_id']
    data = request.get_json()
    with get_db() as db:
        proj = db.execute("SELECT id FROM projects WHERE id=? AND user_id=?", (pid, user_id)).fetchone()
        if not proj:
            return jsonify({'error': 'Project not found'}), 404
        db.execute(
            "INSERT INTO milestones (project_id, name, description, deadline, status, order_index) VALUES (?,?,?,?,?,?)",
            (pid, data.get('name',''), data.get('description',''), data.get('deadline',''), data.get('status','Pending'), data.get('order_index', 0))
        )
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/milestones/<int:mid>', methods=['PUT'])
@login_required
def update_milestone(mid):
    user_id = session['user_id']
    data = request.get_json()
    with get_db() as db:
        row = db.execute("SELECT project_id FROM milestones WHERE id=?", (mid,)).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        proj = db.execute("SELECT id FROM projects WHERE id=? AND user_id=?", (row['project_id'], user_id)).fetchone()
        if not proj:
            return jsonify({'error': 'Access denied'}), 403
        db.execute(
            "UPDATE milestones SET status=?, name=?, deadline=? WHERE id=?",
            (data.get('status','Pending'), data.get('name',''), data.get('deadline',''), mid)
        )
        pid = row['project_id']
        total_ms = db.execute("SELECT COUNT(*) as c FROM milestones WHERE project_id=?", (pid,)).fetchone()['c']
        done_ms  = db.execute("SELECT COUNT(*) as c FROM milestones WHERE project_id=? AND status='Done'", (pid,)).fetchone()['c']
        pct = round(done_ms / total_ms * 100) if total_ms else 0
        db.execute("UPDATE projects SET completion_pct=? WHERE id=? AND user_id=?", (pct, pid, user_id))
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/milestones/<int:mid>', methods=['DELETE'])
@login_required
def delete_milestone(mid):
    user_id = session['user_id']
    with get_db() as db:
        row = db.execute("SELECT project_id FROM milestones WHERE id=?", (mid,)).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
        proj = db.execute("SELECT id FROM projects WHERE id=? AND user_id=?", (row['project_id'], user_id)).fetchone()
        if not proj:
            return jsonify({'error': 'Access denied'}), 403
        db.execute("DELETE FROM milestones WHERE id=?", (mid,))
        pid = row['project_id']
        total_ms = db.execute("SELECT COUNT(*) as c FROM milestones WHERE project_id=?", (pid,)).fetchone()['c']
        done_ms  = db.execute("SELECT COUNT(*) as c FROM milestones WHERE project_id=? AND status='Done'", (pid,)).fetchone()['c']
        pct = round(done_ms / total_ms * 100) if total_ms else 0
        db.execute("UPDATE projects SET completion_pct=? WHERE id=? AND user_id=?", (pct, pid, user_id))
        db.commit()
    return jsonify({'ok': True})

# ─── IMPORT ───────────────────────────────────────────────────────────────────
@app.route('/api/import', methods=['POST'])
@login_required
def import_problems():
    user_id = session['user_id']
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
            db.execute("DELETE FROM daily_plan WHERE user_id=? AND problem_id IN (SELECT id FROM problems WHERE user_id=? AND import_batch NOT IN (SELECT (filename || '_' || import_date) FROM imports WHERE user_id=? AND protected=1))", (user_id, user_id, user_id))
            db.execute("DELETE FROM problems WHERE user_id=? AND import_batch NOT IN (SELECT (filename || '_' || import_date) FROM imports WHERE user_id=? AND protected=1)", (user_id, user_id))

        for task in tasks:
            name = task.get('name', '').strip()
            if not name:
                continue
            # Check duplicate by name AND topic
            existing = db.execute(
                "SELECT id FROM problems WHERE user_id=? AND name=? AND topic=?",
                (user_id, name, task.get('topic', ''))
            ).fetchone()
            if existing and mode != 'replace':
                skipped_dupes += 1
                continue
            db.execute(
                "INSERT INTO problems (user_id, name,category,topic,difficulty,platform,problem_link,resource_link,status,scheduled_date,import_batch) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, name, task.get('category','DSA'), task.get('topic',''), task.get('difficulty','Medium'),
                 task.get('platform','Custom'), task.get('problem_link',''), task.get('resource_link',''),
                 'Pending', task.get('scheduled_date',''), batch_id)
            )
            imported += 1

        for fname in (filenames if filenames else [filename]):
            db.execute("INSERT INTO imports (user_id, filename, import_date, total_imported, category) VALUES (?,?,?,?,?)",
                       (user_id, fname, local_today(), imported, ''))
        db.commit()

    return jsonify({'ok': True, 'imported': imported, 'skipped': skipped_dupes, 'batch': batch_id})

# ─── STATIC ───────────────────────────────────────────────────────────────────
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)