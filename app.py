from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import os, json, re
from datetime import date, timedelta
import pandas as pd
from database import get_db, init_db
from ai_service import (
    generate_daily_plan, get_todays_plan, generate_daily_briefing,
    map_excel_columns, detect_category, assign_goals, ask_ai
)

app = Flask(__name__)
CORS(app)
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
init_db()

TODAY = date.today().isoformat()

# ══════════════════════════════════════════════════════
# PAGES
# ══════════════════════════════════════════════════════
@app.route('/')
def index():
    return render_template('index.html')

# ══════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════
@app.route('/api/settings', methods=['GET'])
def get_settings():
    with get_db() as db:
        rows = db.execute("SELECT * FROM settings").fetchall()
    return jsonify({r['key']: r['value'] for r in rows})

@app.route('/api/settings', methods=['POST'])
def save_settings():
    data = request.json
    with get_db() as db:
        for k, v in data.items():
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (k, str(v)))
        db.commit()
    return jsonify({'ok': True})

# ══════════════════════════════════════════════════════
# DASHBOARD / DAILY HUB
# ══════════════════════════════════════════════════════
@app.route('/api/dashboard', methods=['GET'])
def get_dashboard():
    today = date.today().isoformat()
    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT * FROM settings").fetchall()}
        total    = db.execute("SELECT COUNT(*) as c FROM problems").fetchone()['c']
        solved   = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Solved'").fetchone()['c']
        pending  = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Pending'").fetchone()['c']
        skipped  = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Skipped'").fetchone()['c']
        attempted= db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Attempted'").fetchone()['c']

        # Streak
        streak = 0
        check = date.today()
        while True:
            ds = check.isoformat()
            log = db.execute("SELECT problems_solved FROM daily_log WHERE log_date=?", (ds,)).fetchone()
            goal = int(settings.get('daily_goal', 10))
            if not log or log['problems_solved'] < goal:
                break
            streak += 1
            check -= timedelta(days=1)

        # Days left
        deadline = settings.get('placement_deadline', '2026-10-01')
        days_left = (date.fromisoformat(deadline) - date.today()).days

        # Today's log
        today_log = db.execute("SELECT * FROM daily_log WHERE log_date=?", (today,)).fetchone()

        # Weekly goal
        week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        weekly = db.execute("SELECT * FROM weekly_goals WHERE week_start=?", (week_start,)).fetchone()

        # Monthly goal
        monthly = db.execute(
            "SELECT * FROM monthly_goals WHERE month=? AND year=?",
            (date.today().strftime('%B'), date.today().year)
        ).fetchone()

        # Cached AI feedback
        cached_ai = db.execute(
            "SELECT content, model_used FROM ai_feedback WHERE feedback_date=? AND feedback_type='daily'",
            (today,)
        ).fetchone()

        # Course progress
        courses = db.execute(
            "SELECT id, name, icon, total_topics, completed_topics, streak FROM courses ORDER BY id"
        ).fetchall()

    assign_goals()
    plan = generate_daily_plan(today)

    today_solved  = today_log['problems_solved'] if today_log else 0
    today_target  = int(settings.get('daily_goal', 10))
    today_pct     = round(today_solved / today_target * 100) if today_target else 0

    return jsonify({
        'stats': {
            'total': total, 'solved': solved, 'pending': pending,
            'skipped': skipped, 'attempted': attempted,
            'streak': streak, 'days_left': days_left,
            'today_solved': today_solved, 'today_target': today_target,
            'today_pct': today_pct
        },
        'weekly': dict(weekly) if weekly else {'target_problems': 70, 'done_problems': 0},
        'monthly': dict(monthly) if monthly else {'target_problems': 300, 'done_problems': 0},
        'today_plan': plan,
        'ai_briefing': cached_ai['content'] if cached_ai else None,
        'ai_model': cached_ai['model_used'] if cached_ai else None,
        'courses': [dict(c) for c in courses],
        'settings': settings
    })

@app.route('/api/ai/briefing', methods=['POST'])
def refresh_briefing():
    content, model = generate_daily_briefing()
    return jsonify({'content': content, 'model': model})

@app.route('/api/ai/chat', methods=['POST'])
def ai_chat():
    msg = request.json.get('message', '')
    if not msg:
        return jsonify({'error': 'No message'}), 400
    response, model = ask_ai(msg)
    return jsonify({'response': response, 'model': model})

# ══════════════════════════════════════════════════════
# PROBLEMS
# ══════════════════════════════════════════════════════
@app.route('/api/problems', methods=['GET'])
def get_problems():
    cat    = request.args.get('category', '')
    status = request.args.get('status', '')
    topic  = request.args.get('topic', '')
    diff   = request.args.get('difficulty', '')
    search = request.args.get('search', '')
    batch  = request.args.get('batch', '')

    query = "SELECT * FROM problems WHERE 1=1"
    params = []
    if cat:    query += " AND category=?";    params.append(cat)
    if status: query += " AND status=?";      params.append(status)
    if topic:  query += " AND topic LIKE ?";  params.append(f'%{topic}%')
    if diff:   query += " AND difficulty=?";  params.append(diff)
    if search: query += " AND name LIKE ?";   params.append(f'%{search}%')
    if batch:  query += " AND import_batch=?"; params.append(batch)
    query += " ORDER BY CASE status WHEN 'Pending' THEN 1 WHEN 'Attempted' THEN 2 WHEN 'Solved' THEN 3 ELSE 4 END, CASE difficulty WHEN 'Easy' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END"

    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/problems', methods=['POST'])
def add_problem():
    d = request.json
    if not d.get('name'):
        return jsonify({'error': 'name required'}), 400
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO problems (name,category,topic,subtopic,difficulty,platform,problem_link,resource_link,status,scheduled_date,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (d.get('name',''), d.get('category','DSA'), d.get('topic',''), d.get('subtopic',''),
             d.get('difficulty','Medium'), d.get('platform','LeetCode'),
             d.get('problem_link',''), d.get('resource_link',''),
             d.get('status','Pending'), d.get('scheduled_date',''), d.get('notes',''))
        )
        db.commit()
        row = db.execute("SELECT * FROM problems WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/problems/<int:pid>', methods=['PUT'])
def update_problem(pid):
    d = request.json
    fields, vals = [], []
    allowed = ['name','category','topic','difficulty','platform','problem_link','resource_link','status','scheduled_date','notes']
    for f in allowed:
        if f in d:
            fields.append(f"{f}=?")
            vals.append(d[f])
    if not fields:
        return jsonify({'error': 'nothing to update'}), 400
    vals.append(pid)
    with get_db() as db:
        db.execute(f"UPDATE problems SET {','.join(fields)} WHERE id=?", vals)
        # Update daily log if status changed to Solved
        if d.get('status') == 'Solved':
            today = date.today().isoformat()
            db.execute("INSERT OR IGNORE INTO daily_log (log_date) VALUES (?)", (today,))
            db.execute("UPDATE daily_log SET problems_solved = problems_solved + 1 WHERE log_date=?", (today,))
            db.execute("UPDATE daily_plan SET status='Solved' WHERE problem_id=? AND plan_date=?", (pid, today))
        elif d.get('status') == 'Attempted':
            today = date.today().isoformat()
            db.execute("INSERT OR IGNORE INTO daily_log (log_date) VALUES (?)", (today,))
            db.execute("UPDATE daily_log SET problems_attempted = problems_attempted + 1 WHERE log_date=?", (today,))
            db.execute("UPDATE daily_plan SET status='Attempted' WHERE problem_id=? AND plan_date=?", (pid, today))
        elif d.get('status') == 'Skipped':
            today = date.today().isoformat()
            db.execute("UPDATE daily_plan SET status='Skipped' WHERE problem_id=? AND plan_date=?", (pid, today))
        db.commit()
        row = db.execute("SELECT * FROM problems WHERE id=?", (pid,)).fetchone()
    assign_goals()
    return jsonify(dict(row))

@app.route('/api/problems/<int:pid>', methods=['DELETE'])
def delete_problem(pid):
    with get_db() as db:
        db.execute("DELETE FROM daily_plan WHERE problem_id=?", (pid,))
        db.execute("DELETE FROM problems WHERE id=?", (pid,))
        db.commit()
    return jsonify({'deleted': pid})

@app.route('/api/problems/delete-batch', methods=['POST'])
def delete_batch():
    d = request.json
    batch = d.get('batch')
    category = d.get('category')
    date_range = d.get('date_range')

    with get_db() as db:
        if batch:
            db.execute("DELETE FROM problems WHERE import_batch=?", (batch,))
        elif category:
            db.execute("DELETE FROM problems WHERE category=?", (category,))
        elif date_range:
            db.execute("DELETE FROM problems WHERE scheduled_date BETWEEN ? AND ?",
                      (date_range[0], date_range[1]))
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/problems/clear', methods=['DELETE'])
def clear_problems():
    with get_db() as db:
        db.execute("DELETE FROM problems")
        db.execute("DELETE FROM daily_plan")
        db.commit()
    return jsonify({'ok': True})

@app.route('/api/topics', methods=['GET'])
def get_topics():
    with get_db() as db:
        rows = db.execute("SELECT DISTINCT topic FROM problems WHERE topic!='' ORDER BY topic").fetchall()
    return jsonify([r['topic'] for r in rows])

@app.route('/api/imports', methods=['GET'])
def get_imports():
    with get_db() as db:
        rows = db.execute("SELECT * FROM imports ORDER BY import_date DESC").fetchall()
    return jsonify([dict(r) for r in rows])

# ══════════════════════════════════════════════════════
# EXCEL UPLOAD & IMPORT
# ══════════════════════════════════════════════════════
def detect_platform(link):
    if not link: return 'Custom'
    link = link.lower()
    if 'leetcode' in link: return 'LeetCode'
    if 'geeksforgeeks' in link or 'gfg' in link: return 'GFG'
    if 'hackerrank' in link: return 'HackerRank'
    if 'indiabix' in link: return 'IndiaBix'
    if 'youtube' in link or 'youtu.be' in link: return 'YouTube'
    if 'codechef' in link: return 'CodeChef'
    if 'codeforces' in link: return 'Codeforces'
    return 'Custom'

@app.route('/api/upload', methods=['POST'])
def upload_excel():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No filename'}), 400

    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    
    try:
        # Save file
        file.save(filepath)
        
        all_sheets = {}
        if file.filename.endswith('.csv'):
            df = pd.read_csv(filepath)
            df.columns = df.columns.str.strip()
            all_sheets['Sheet1'] = df
        else:
            xl = pd.ExcelFile(filepath)
            for sheet in xl.sheet_names:
                df = xl.parse(sheet)
                df.columns = df.columns.str.strip()
                all_sheets[sheet] = df

        preview_data = []
        total_count = 0

        for sheet_name, df in all_sheets.items():
            if df.empty:
                continue
            cols = df.columns.tolist()
            mapping = map_excel_columns(cols)
            category = detect_category(sheet_name, cols)

            if 'name' not in mapping:
                continue

            for _, row in df.iterrows():
                name = str(row.get(mapping['name'], '')).strip()
                if not name or name.lower() in ('nan', 'none', ''):
                    continue

                # Parse date
                raw_date = row.get(mapping.get('date', '__x__'), None)
                task_date = ''
                if raw_date is not None and str(raw_date).lower() not in ('nan', 'none', ''):
                    try:
                        if hasattr(raw_date, 'date'):
                            task_date = raw_date.date().isoformat()
                        else:
                            task_date = pd.to_datetime(str(raw_date)).date().isoformat()
                    except:
                        task_date = ''

                # Get other fields
                topic = str(row.get(mapping.get('topic', '__x__'), '')).strip()
                if topic.lower() in ('nan', 'none'): topic = ''

                diff = str(row.get(mapping.get('difficulty', '__x__'), 'Medium')).strip()
                if diff.lower() in ('nan', 'none', ''): diff = 'Medium'
                if diff.lower() == 'easy': diff = 'Easy'
                elif diff.lower() == 'hard': diff = 'Hard'
                else: diff = 'Medium'

                plink = str(row.get(mapping.get('problem_link', '__x__'), '')).strip()
                if plink.lower() in ('nan', 'none'): plink = ''

                rlink = str(row.get(mapping.get('resource_link', '__x__'), '')).strip()
                if rlink.lower() in ('nan', 'none'): rlink = ''

                platform = str(row.get(mapping.get('platform', '__x__'), '')).strip()
                if platform.lower() in ('nan', 'none', ''): platform = detect_platform(plink)

                cat = str(row.get(mapping.get('category', '__x__'), category)).strip()
                if cat.lower() in ('nan', 'none', ''): cat = category

                preview_data.append({
                    'name': name, 'category': cat, 'topic': topic,
                    'difficulty': diff, 'platform': platform,
                    'problem_link': plink, 'resource_link': rlink,
                    'scheduled_date': task_date, 'status': 'Pending',
                    'sheet': sheet_name
                })
                total_count += 1

        # Check overload dates
        from collections import Counter
        date_counts = Counter(p['scheduled_date'] for p in preview_data if p['scheduled_date'])
        with get_db() as db:
            settings = {r['key']: r['value'] for r in db.execute("SELECT * FROM settings").fetchall()}
        daily_goal = int(settings.get('daily_goal', 10))
        overload_dates = [d for d, c in date_counts.items() if c > daily_goal]

        return jsonify({
            'tasks': preview_data,
            'count': total_count,
            'sheets': list(all_sheets.keys()),
            'overload_dates': overload_dates,
            'filename': file.filename
        })

    except Exception as e:
        return jsonify({'error': f'Could not parse file: {str(e)}'}), 400
    finally:
        # Close any open file handles before removing
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except PermissionError:
            import time
            time.sleep(0.5)
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except:
                pass

@app.route('/api/import', methods=['POST'])
def import_problems():
    data = request.json
    problems = data.get('tasks', [])
    mode = data.get('mode', 'add')  # add, replace, merge
    filename = data.get('filename', 'import')
    batch_id = f"{filename}_{date.today().isoformat()}"

    imported = 0
    skipped_dupes = 0

    with get_db() as db:
        if mode == 'replace':
            db.execute("DELETE FROM problems")
            db.execute("DELETE FROM daily_plan")

        for p in problems:
            name = p.get('name', '').strip()
            if not name: continue

            if mode == 'merge':
                existing = db.execute(
                    "SELECT id FROM problems WHERE name=? AND category=?",
                    (name, p.get('category', 'DSA'))
                ).fetchone()
                if existing:
                    skipped_dupes += 1
                    continue

            db.execute('''INSERT INTO problems
                (name,category,topic,difficulty,platform,problem_link,resource_link,
                 scheduled_date,status,import_batch)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (name, p.get('category','DSA'), p.get('topic',''),
                 p.get('difficulty','Medium'), p.get('platform','Custom'),
                 p.get('problem_link',''), p.get('resource_link',''),
                 p.get('scheduled_date',''), 'Pending', batch_id)
            )
            imported += 1

        db.execute(
            "INSERT INTO imports (filename, total_imported, category) VALUES (?,?,?)",
            (filename, imported, 'Mixed')
        )
        db.commit()

    assign_goals()
    # Reset today's plan so it regenerates with new problems
    with get_db() as db:
        db.execute("DELETE FROM daily_plan WHERE plan_date=?", (date.today().isoformat(),))
        db.commit()

    return jsonify({'imported': imported, 'skipped': skipped_dupes, 'batch': batch_id})

# ══════════════════════════════════════════════════════
# COURSES
# ══════════════════════════════════════════════════════
@app.route('/api/courses', methods=['GET'])
def get_courses():
    with get_db() as db:
        courses = db.execute("SELECT * FROM courses ORDER BY id").fetchall()
        result = []
        for c in courses:
            topics = db.execute(
                "SELECT COUNT(*) as total, SUM(CASE WHEN status='Done' THEN 1 ELSE 0 END) as done FROM course_topics WHERE course_id=?",
                (c['id'],)
            ).fetchone()
            total = topics['total'] or 0
            done  = topics['done'] or 0
            result.append({**dict(c), 'total_topics': total, 'completed_topics': done})
    return jsonify(result)

@app.route('/api/courses/<int:cid>/topics', methods=['GET'])
def get_course_topics(cid):
    with get_db() as db:
        topics = db.execute(
            "SELECT * FROM course_topics WHERE course_id=? ORDER BY order_index",
            (cid,)
        ).fetchall()
    return jsonify([dict(t) for t in topics])

@app.route('/api/courses/<int:cid>/topics', methods=['POST'])
def add_course_topic(cid):
    d = request.json
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO course_topics (course_id,topic_name,description,youtube_link,article_link,practice_link,order_index) VALUES (?,?,?,?,?,?,?)",
            (cid, d.get('topic_name',''), d.get('description',''),
             d.get('youtube_link',''), d.get('article_link',''),
             d.get('practice_link',''), d.get('order_index',0))
        )
        db.commit()
        row = db.execute("SELECT * FROM course_topics WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/courses/topics/<int:tid>', methods=['PUT'])
def update_course_topic(tid):
    d = request.json
    with get_db() as db:
        if d.get('status') == 'Done':
            db.execute(
                "UPDATE course_topics SET status='Done', completed_at=? WHERE id=?",
                (date.today().isoformat(), tid)
            )
            # Update course streak
            topic = db.execute("SELECT course_id FROM course_topics WHERE id=?", (tid,)).fetchone()
            if topic:
                db.execute(
                    "UPDATE courses SET streak=streak+1, last_studied=? WHERE id=?",
                    (date.today().isoformat(), topic['course_id'])
                )
        else:
            db.execute("UPDATE course_topics SET status=? WHERE id=?", (d.get('status','Not Started'), tid))
        db.commit()
        row = db.execute("SELECT * FROM course_topics WHERE id=?", (tid,)).fetchone()
    return jsonify(dict(row))

# ══════════════════════════════════════════════════════
# ALGORITHMS
# ══════════════════════════════════════════════════════
@app.route('/api/algorithms', methods=['GET'])
def get_algorithms():
    with get_db() as db:
        rows = db.execute("SELECT * FROM algorithms ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/algorithms/<int:aid>', methods=['PUT'])
def update_algorithm(aid):
    d = request.json
    with get_db() as db:
        db.execute(
            "UPDATE algorithms SET mastery=? WHERE id=?",
            (d.get('mastery', 'Not Started'), aid)
        )
        db.commit()
        row = db.execute("SELECT * FROM algorithms WHERE id=?", (aid,)).fetchone()
    return jsonify(dict(row))

# ══════════════════════════════════════════════════════
# PROJECTS
# ══════════════════════════════════════════════════════
@app.route('/api/projects', methods=['GET'])
def get_projects():
    with get_db() as db:
        projects = db.execute("SELECT * FROM projects ORDER BY id").fetchall()
        result = []
        for p in projects:
            milestones = db.execute(
                "SELECT COUNT(*) as total, SUM(CASE WHEN status='Done' THEN 1 ELSE 0 END) as done FROM milestones WHERE project_id=?",
                (p['id'],)
            ).fetchone()
            total = milestones['total'] or 0
            done  = milestones['done'] or 0
            pct   = round(done/total*100) if total else 0
            result.append({**dict(p), 'completion_pct': pct, 'milestone_total': total, 'milestone_done': done})
    return jsonify(result)

@app.route('/api/projects', methods=['POST'])
def add_project():
    d = request.json
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO projects (name,description,tech_stack,target_date,github_link) VALUES (?,?,?,?,?)",
            (d.get('name',''), d.get('description',''), d.get('tech_stack',''), d.get('target_date',''), d.get('github_link',''))
        )
        db.commit()
        row = db.execute("SELECT * FROM projects WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/projects/<int:pid>/milestones', methods=['GET'])
def get_milestones(pid):
    with get_db() as db:
        rows = db.execute("SELECT * FROM milestones WHERE project_id=? ORDER BY order_index", (pid,)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/projects/<int:pid>/milestones', methods=['POST'])
def add_milestone(pid):
    d = request.json
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO milestones (project_id,name,description,deadline,order_index) VALUES (?,?,?,?,?)",
            (pid, d.get('name',''), d.get('description',''), d.get('deadline',''), d.get('order_index',0))
        )
        db.commit()
        row = db.execute("SELECT * FROM milestones WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/milestones/<int:mid>', methods=['PUT'])
def update_milestone(mid):
    d = request.json
    with get_db() as db:
        db.execute("UPDATE milestones SET status=? WHERE id=?", (d.get('status','Pending'), mid))
        db.commit()
        row = db.execute("SELECT * FROM milestones WHERE id=?", (mid,)).fetchone()
    return jsonify(dict(row))

# ══════════════════════════════════════════════════════
# STATS / PROGRESS
# ══════════════════════════════════════════════════════
@app.route('/api/stats', methods=['GET'])
def get_stats():
    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT * FROM settings").fetchall()}
        total   = db.execute("SELECT COUNT(*) as c FROM problems").fetchone()['c']
        solved  = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Solved'").fetchone()['c']
        pending = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Pending'").fetchone()['c']
        skipped = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Skipped'").fetchone()['c']
        attempted=db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Attempted'").fetchone()['c']

        # By category
        cats = db.execute(
            "SELECT category, COUNT(*) as total, SUM(CASE WHEN status='Solved' THEN 1 ELSE 0 END) as solved FROM problems GROUP BY category"
        ).fetchall()

        # Last 30 days
        thirty_days = [(date.today() - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
        daily_data = []
        for ds in thirty_days:
            log = db.execute("SELECT * FROM daily_log WHERE log_date=?", (ds,)).fetchone()
            daily_data.append({
                'date': ds,
                'label': ds[5:],
                'solved': log['problems_solved'] if log else 0,
                'target': log['problems_target'] if log else int(settings.get('daily_goal', 10))
            })

        # Weekly goals
        weekly_goals = db.execute("SELECT * FROM weekly_goals ORDER BY week_start DESC LIMIT 8").fetchall()

        # Monthly goals
        monthly_goals = db.execute("SELECT * FROM monthly_goals ORDER BY year DESC, id DESC LIMIT 6").fetchall()

        # Streak
        streak = 0
        check = date.today()
        goal = int(settings.get('daily_goal', 10))
        while True:
            ds = check.isoformat()
            log = db.execute("SELECT problems_solved FROM daily_log WHERE log_date=?", (ds,)).fetchone()
            if not log or log['problems_solved'] < goal:
                break
            streak += 1
            check -= timedelta(days=1)

        # Placement readiness
        dsa_cat = next((c for c in cats if c['category']=='DSA'), None)
        apt_cat = next((c for c in cats if c['category']=='Aptitude'), None)
        dsa_pct = round(dsa_cat['solved']/dsa_cat['total']*100) if dsa_cat and dsa_cat['total'] else 0
        apt_pct = round(apt_cat['solved']/apt_cat['total']*100) if apt_cat and apt_cat['total'] else 0

        courses_total = db.execute("SELECT SUM(total_topics) as t FROM courses").fetchone()['t'] or 1
        courses_done  = db.execute(
            "SELECT COUNT(*) as c FROM course_topics WHERE status='Done'"
        ).fetchone()['c']
        course_pct = round(courses_done/courses_total*100) if courses_total else 0

        projects_total = db.execute("SELECT COUNT(*) as c FROM milestones").fetchone()['c'] or 1
        projects_done  = db.execute("SELECT COUNT(*) as c FROM milestones WHERE status='Done'").fetchone()['c']
        project_pct = round(projects_done/projects_total*100) if projects_total else 0

        readiness = round(
            dsa_pct * 0.30 +
            apt_pct * 0.20 +
            course_pct * 0.20 +
            project_pct * 0.15 +
            min(streak * 2, 15)
        )

        deadline = settings.get('placement_deadline', '2026-10-01')
        days_left = (date.fromisoformat(deadline) - date.today()).days
        needed_per_day = round((pending + attempted) / days_left, 1) if days_left > 0 else 0

        # AI weekly report
        weekly_prompt = f"""
Week summary for placement student:
- Problems solved this week: {sum(d['solved'] for d in daily_data[-7:])}
- Weekly target: {goal * 7}
- Total solved ever: {solved}/{total}
- Readiness score: {readiness}/100
- Days left: {days_left}
- Needed per day to finish: {needed_per_day}
Give a 3-4 sentence honest weekly assessment. Be specific with numbers. Suggest what to focus on next week.
"""
        weekly_ai, _ = ask_ai(weekly_prompt)

    return jsonify({
        'total': total, 'solved': solved, 'pending': pending,
        'skipped': skipped, 'attempted': attempted,
        'streak': streak, 'readiness': readiness,
        'days_left': days_left, 'needed_per_day': needed_per_day,
        'categories': [dict(c) for c in cats],
        'daily_data': daily_data,
        'weekly_goals': [dict(w) for w in weekly_goals],
        'monthly_goals': [dict(m) for m in monthly_goals],
        'weekly_ai_report': weekly_ai
    })

# ══════════════════════════════════════════════════════
# TOPIC PLANNER
# ══════════════════════════════════════════════════════
@app.route('/api/topic/<topic>', methods=['GET'])
def get_topic_problems(topic):
    with get_db() as db:
        problems = db.execute(
            "SELECT * FROM problems WHERE topic LIKE ? ORDER BY CASE difficulty WHEN 'Easy' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END",
            (f'%{topic}%',)
        ).fetchall()
        total = len(problems)
        solved = sum(1 for p in problems if p['status'] == 'Solved')
        algo = db.execute("SELECT * FROM algorithms WHERE name LIKE ? OR pattern LIKE ?", (f'%{topic}%', f'%{topic}%')).fetchone()

    # AI resource suggestion
    resource_prompt = f"For the topic '{topic}' in DSA/placement preparation, give exactly 3 free resources: 1 YouTube video URL, 1 article URL (GFG/NeetCode), 1 practice page URL. Format as JSON with keys: youtube, article, practice. Only URLs, no explanation."
    ai_resources, _ = ask_ai(resource_prompt)

    return jsonify({
        'topic': topic,
        'problems': [dict(p) for p in problems],
        'total': total,
        'solved': solved,
        'algorithm': dict(algo) if algo else None,
        'ai_resources': ai_resources
    })
# ========== NEW: Topic Resources API ==========
@app.route('/api/topic/<topic>/resources', methods=['GET'])
def get_topic_resources(topic):
    from ai_service import extract_topic_resources
    resources = extract_topic_resources(topic)
    return jsonify(resources)

# ========== NEW: Readiness Score API ==========
@app.route('/api/readiness-score', methods=['GET'])
def get_readiness_score():
    from ai_service import calculate_readiness_score
    score = calculate_readiness_score()
    
    if score >= 70:
        level = "🟢 On Track"
    elif score >= 40:
        level = "🟡 Needs Work"
    else:
        level = "🔴 Behind Schedule"
    
    return jsonify({'score': score, 'level': level})

# ========== NEW: Company Advice API ==========
@app.route('/api/company-advice', methods=['GET'])
def get_company_advice_route():
    from ai_service import get_company_advice
    company = request.args.get('company', None)
    advice = get_company_advice(company)
    return jsonify(advice)

# ========== NEW: Tech Radar API ==========
@app.route('/api/tech-radar', methods=['GET'])
def get_tech_radar_route():
    from ai_service import get_tech_radar
    radar = get_tech_radar()
    return jsonify(radar)

if __name__ == '__main__':
    print("\n🪐 MineTracker is starting...")
    print("➜  Open http://localhost:5000\n")
    app.run(debug=True, port=5000, use_reloader=False)