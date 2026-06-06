import os
import re
import json
from datetime import date, timedelta
from database import get_db

# ── Try importing AI libraries ────────────────────────
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except:
    GROQ_AVAILABLE = False

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except:
    GEMINI_AVAILABLE = False

# ── Get API keys from DB ──────────────────────────────
def get_keys():
    with get_db() as db:
        rows = db.execute("SELECT key,value FROM settings WHERE key LIKE '%api_key%' OR key='ai_provider'").fetchall()
    return {r['key']: r['value'] for r in rows}

# ── Get Current Student Status (REAL DATA) ────────────
def get_student_status():
    """Fetch real student data from database"""
    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT * FROM settings").fetchall()}
        
        # Problem counts
        total = db.execute("SELECT COUNT(*) as c FROM problems").fetchone()['c']
        solved = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Solved'").fetchone()['c']
        pending = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Pending'").fetchone()['c']
        attempted = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Attempted'").fetchone()['c']
        skipped = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Skipped'").fetchone()['c']
        
        # Today's progress
        today = date.today().isoformat()
        today_log = db.execute("SELECT * FROM daily_log WHERE log_date=?", (today,)).fetchone()
        solved_today = today_log['problems_solved'] if today_log else 0
        
        # Weak topics (most skipped)
        weak_topics = db.execute(
            "SELECT topic, COUNT(*) as c FROM problems WHERE status='Skipped' AND topic != '' GROUP BY topic ORDER BY c DESC LIMIT 3"
        ).fetchall()
        
        # Streak
        goal = int(settings.get('daily_goal', 10))
        streak = 0
        check = date.today()
        while True:
            ds = check.isoformat()
            log = db.execute("SELECT problems_solved FROM daily_log WHERE log_date=?", (ds,)).fetchone()
            if not log or log['problems_solved'] < goal:
                break
            streak += 1
            check -= timedelta(days=1)
        
        # Days left
        deadline = settings.get('placement_deadline', '2026-10-01')
        days_left = (date.fromisoformat(deadline) - date.today()).days
        
        # Company target
        companies = settings.get('target_companies', 'Service Based')
        name = settings.get('name', 'Student')
        
        # Category breakdown
        cats = db.execute(
            "SELECT category, COUNT(*) as total, SUM(CASE WHEN status='Solved' THEN 1 ELSE 0 END) as solved FROM problems GROUP BY category"
        ).fetchall()
        
    weak_str = ', '.join([r['topic'] for r in weak_topics]) if weak_topics else 'none'
    
    return {
        'name': name,
        'total': total,
        'solved': solved,
        'pending': pending,
        'attempted': attempted,
        'skipped': skipped,
        'solved_today': solved_today,
        'daily_goal': goal,
        'streak': streak,
        'days_left': days_left,
        'weak_topics': weak_str,
        'target_companies': companies,
        'categories': [dict(c) for c in cats]
    }

# ── Main AI Call with Context ─────────────────────────
# Add this new function to get problems for a specific date
def get_problems_for_date(target_date=None):
    """Get problems scheduled for a specific date"""
    if target_date is None:
        target_date = date.today().isoformat()
    
    with get_db() as db:
        problems = db.execute(
            """SELECT name, category, topic, difficulty, problem_link 
               FROM problems 
               WHERE scheduled_date = ? AND status = 'Pending'
               ORDER BY difficulty
               LIMIT 10""",
            (target_date,)
        ).fetchall()
    return [dict(p) for p in problems]

# Replace the ask_ai function with this:
def ask_ai(prompt, system=None):
    # Get real student data
    status = get_student_status()
    
    # Get today's and tomorrow's problems
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    today_problems = get_problems_for_date(today)
    tomorrow_problems = get_problems_for_date(tomorrow)
    
    # Format problems for prompt
    today_list = "\n".join([f"  - {p['name']} ({p['category']})" for p in today_problems]) if today_problems else "  - No problems scheduled today"
    tomorrow_list = "\n".join([f"  - {p['name']} ({p['category']})" for p in tomorrow_problems]) if tomorrow_problems else "  - No problems scheduled tomorrow"
    
    # Build context-aware system message
    if system is None:
        system = f"""You are a brutally honest placement coach for {status['name']}.

⚠️ CRITICAL: Use the REAL data below. This is from the student's actual database.

📊 CURRENT STATUS:
- Days left to placement: {status['days_left']}
- Daily goal: {status['daily_goal']} problems
- Today: {status['solved_today']}/{status['daily_goal']} solved
- Overall: {status['solved']}/{status['total']} problems solved ({round(status['solved']/max(status['total'],1)*100)}%)
- Pending: {status['pending']}, Skipped: {status['skipped']}
- Streak: {status['streak']} days
- Weak topics: {status['weak_topics']}
- Target companies: {status['target_companies']}

📋 TODAY'S SCHEDULED PROBLEMS:
{today_list}

📋 TOMORROW'S SCHEDULED PROBLEMS:
{tomorrow_list}

RULES:
1. USE THE DATA ABOVE - these are REAL problems the student has to solve
2. When asked "what to study today" - list the actual problems from TODAY'S SCHEDULE
3. When asked "am I ready" - base it on solved/total percentage
4. Keep responses UNDER 80 words
5. Be direct, no fluff
6. Reference specific problem names from the schedule if applicable"""

    keys = get_keys()
    provider = keys.get('ai_provider', 'groq')

    # Try Groq
    if GROQ_AVAILABLE and keys.get('groq_api_key'):
        try:
            client = Groq(api_key=keys['groq_api_key'])
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.7
            )
            return response.choices[0].message.content, "groq"
        except Exception as e:
            print(f"Groq failed: {e}")

    # Try Gemini
    if GEMINI_AVAILABLE and keys.get('gemini_api_key'):
        try:
            genai.configure(api_key=keys['gemini_api_key'])
            model = genai.GenerativeModel('gemini-1.5-pro')
            response = model.generate_content(system + "\n\nUser: " + prompt)
            return response.text, "gemini"
        except Exception as e:
            print(f"Gemini failed: {e}")

    # Rule-based fallback (USES REAL DATA)
    return rule_based_advice_with_data(prompt, status, today_problems, tomorrow_problems), "rule-based"

def rule_based_advice_with_data(prompt, status, today_problems, tomorrow_problems):
    """Give advice based on actual database data"""
    prompt_lower = prompt.lower()
    
    if 'what to study today' in prompt_lower or 'study today' in prompt_lower:
        if today_problems:
            problems_list = ", ".join([p['name'] for p in today_problems[:5]])
            return f"Today: {problems_list}. {len(today_problems)} problems scheduled. Start with the easiest."
        else:
            return f"No problems scheduled for today. Check your Excel dates or add problems manually."
    
    if 'tomorrow' in prompt_lower:
        if tomorrow_problems:
            problems_list = ", ".join([p['name'] for p in tomorrow_problems[:5]])
            return f"Tomorrow: {problems_list}. {len(tomorrow_problems)} problems waiting."
        else:
            return f"No problems scheduled for tomorrow. Import Excel or add problems."
    
    if 'am i ready' in prompt_lower or 'on track' in prompt_lower:
        pct = round(status['solved'] / max(status['total'], 1) * 100)
        if pct == 0:
            return f"You've solved 0/{status['total']} problems. Not ready. Start with {today_problems[0]['name'] if today_problems else 'your first problem'} today."
        elif pct < 30:
            return f"Only {pct}% complete ({status['solved']}/{status['total']}). Need {status['days_left']} days. Not ready yet. Keep solving."
        else:
            return f"{pct}% complete. {status['solved']}/{status['total']} done. {status['pending']} pending. Getting there!"
    
    if 'easy problems' in prompt_lower:
        easy_problems = [p for p in today_problems if p.get('difficulty') == 'Easy']
        if easy_problems:
            return f"Easy problems today: {', '.join([p['name'] for p in easy_problems[:3]])}"
        return f"First easy problem: {today_problems[0]['name'] if today_problems else 'Two Sum on LeetCode'}"
    
    if 'weak areas' in prompt_lower:
        if status['weak_topics'] != 'none':
            return f"Your weak topics: {status['weak_topics']}. Focus on these in your scheduled problems."
        return f"Solve {status['pending']} pending problems first. Then review what you struggled with."
    
    # Default
    if today_problems:
        return f"{status['solved']}/{status['total']} solved. Today: {today_problems[0]['name']}. Start now."
    return f"{status['solved']}/{status['total']} solved. {status['pending']} pending. Import Excel or add problems to see daily schedule."
# ── Rule-Based Fallback (USES REAL DATA) ─────────────
def rule_based_feedback(prompt, status=None):
    if status is None:
        status = get_student_status()
    
    prompt_lower = prompt.lower()
    
    # "what should I do today" or "add to task"
    if 'add to task' in prompt_lower or 'what should i do today' in prompt_lower:
        remaining = status['daily_goal'] - status['solved_today']
        if remaining <= 0:
            return f"✅ You hit your goal of {status['daily_goal']}! Rest or do extra. {status['days_left']} days left."
        else:
            return f"Need {remaining} more problems today. Focus on {status['weak_topics'] or 'Arrays'}. Start with LeetCode Easy."
    
    # "am I on track" or "how am I doing"
    if 'on track' in prompt_lower or 'how am i doing' in prompt_lower or 'ready' in prompt_lower:
        pct = round(status['solved'] / max(status['total'], 1) * 100)
        needed = round((status['total'] - status['solved']) / max(status['days_left'], 1), 1)
        if status['streak'] >= 7:
            return f"{pct}% complete. {status['streak']} day streak! Need {needed}/day. Keep going."
        elif status['solved_today'] == 0:
            return f"{pct}% done. You've done 0/{status['daily_goal']} today. Start NOW. Need {needed}/day."
        else:
            return f"{pct}% complete. Need {needed} problems/day for {status['days_left']} days. Weak: {status['weak_topics'] or 'none identified'}."
    
    # "give me 5 easy problems"
    if '5 easy' in prompt_lower or 'easy problems' in prompt_lower:
        return "5 Easy LeetCode:\n1. Two Sum\n2. Valid Palindrome\n3. Reverse Linked List\n4. Balanced Parentheses\n5. Max Subarray\nStart with Two Sum."
    
    # Zoho specific
    if 'zoho' in prompt_lower:
        weak = status['weak_topics']
        if weak != 'none':
            return f"For Zoho: Focus on {weak}. Practice 10 medium Arrays problems. Know Zoho Creator. {status['days_left']} days left."
        return f"For Zoho: Arrays, Strings, OOP. You're at {round(status['solved']/max(status['total'],1)*100)}% completion. Need more practice."
    
    # Short greeting
    if prompt_lower in ['hi', 'hey', 'hello']:
        if status['solved_today'] == 0:
            return f"Hey {status['name']}. 0/{status['daily_goal']} done today. Start now."
        return f"Hey. {status['solved_today']}/{status['daily_goal']} done. Keep going."
    
    # Daily briefing
    if 'briefing' in prompt_lower or 'daily' in prompt_lower:
        return generate_daily_rule_feedback(status)
    
    # Default
    return f"{status['pending']} problems pending. Weak: {status['weak_topics'] or 'none'}. Solve 1 Easy problem now."

def generate_daily_rule_feedback(status=None):
    if status is None:
        status = get_student_status()
    
    remaining = status['daily_goal'] - status['solved_today']
    
    if status['solved_today'] >= status['daily_goal']:
        return f"✅ Done {status['solved_today']}/{status['daily_goal']}. {status['streak']} day streak! {status['days_left']} days left for placements."
    elif status['solved_today'] > 0:
        return f"📊 {status['solved_today']}/{status['daily_goal']} today. Need {remaining} more. Weak: {status['weak_topics'] or 'Arrays'}."
    else:
        return f"⚠️ 0/{status['daily_goal']} solved. {status['pending']} pending total. {status['days_left']} days left. Open LeetCode NOW."

# ── Generate Daily Plan ───────────────────────────────
def generate_daily_plan(today_str=None):
    if not today_str:
        today_str = date.today().isoformat()

    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT * FROM settings").fetchall()}
        goal = int(settings.get('daily_goal', 10))

        existing = db.execute("SELECT COUNT(*) as c FROM daily_plan WHERE plan_date=?", (today_str,)).fetchone()
        if existing['c'] > 0:
            return get_todays_plan(today_str)

        scheduled = db.execute(
            "SELECT * FROM problems WHERE scheduled_date=? AND status='Pending' ORDER BY CASE difficulty WHEN 'Easy' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END LIMIT ?",
            (today_str, goal)
        ).fetchall()

        plan_problems = list(scheduled)
        remaining = goal - len(plan_problems)
        
        if remaining > 0:
            scheduled_ids = [p['id'] for p in plan_problems]
            dist = [('DSA', 5), ('Aptitude', 2), ('Verbal', 1), ('Interview', 1), ('HR', 1)]
            for cat, count in dist:
                if remaining <= 0:
                    break
                take = min(count, remaining)
                exclude = scheduled_ids + [p['id'] for p in plan_problems]
                placeholders = ','.join('?' * len(exclude)) if exclude else '0'
                extra = db.execute(
                    f"SELECT * FROM problems WHERE category=? AND status='Pending' AND id NOT IN ({placeholders}) ORDER BY CASE difficulty WHEN 'Easy' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END LIMIT ?",
                    [cat] + exclude + [take]
                ).fetchall()
                plan_problems.extend(extra)
                remaining -= len(extra)

        for i, p in enumerate(plan_problems):
            db.execute(
                "INSERT INTO daily_plan (plan_date, problem_id, order_index, status) VALUES (?,?,?,?)",
                (today_str, p['id'], i, 'Pending')
            )

        db.execute(
            "INSERT OR IGNORE INTO daily_log (log_date, problems_target) VALUES (?,?)",
            (today_str, goal)
        )
        db.commit()

    return get_todays_plan(today_str)

def get_todays_plan(today_str=None):
    if not today_str:
        today_str = date.today().isoformat()
    with get_db() as db:
        plan = db.execute('''
            SELECT dp.id as plan_id, dp.status as plan_status, dp.order_index,
                   p.id, p.name, p.category, p.topic, p.difficulty, p.platform,
                   p.problem_link, p.resource_link, p.notes
            FROM daily_plan dp
            JOIN problems p ON dp.problem_id = p.id
            WHERE dp.plan_date = ?
            ORDER BY dp.order_index
        ''', (today_str,)).fetchall()
    return [dict(r) for r in plan]

# ── Generate AI Daily Briefing (WITH REAL DATA) ──────
def generate_daily_briefing():
    status = get_student_status()
    
    prompt = f"""Based on my real data:
- Solved {status['solved']}/{status['total']} total ({round(status['solved']/max(status['total'],1)*100)}%)
- Today: {status['solved_today']}/{status['daily_goal']}
- Streak: {status['streak']} days
- Days left: {status['days_left']}
- Weak topics: {status['weak_topics']}

Give me a 2-sentence brutally honest daily briefing. Use my actual numbers. Suggest ONE free resource."""
    
    feedback, model = ask_ai(prompt)
    
    # Store feedback
    today = date.today().isoformat()
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO ai_feedback (feedback_date, feedback_type, content, model_used) VALUES (?,?,?,?)",
            (today, 'daily', feedback, model)
        )
        db.commit()

    return feedback, model

# ── Column Mapping ─────────────────────────────────
def map_excel_columns(columns):
    cols_lower = {c.lower().strip(): c for c in columns}
    mapping = {}

    name_keys   = ['problem','task','name','title','question']
    topic_keys  = ['topic','subject','chapter']
    cat_keys    = ['category','cat','type']
    diff_keys   = ['difficulty','level']
    link_keys   = ['link','url','problem link']
    res_keys    = ['resource','resource link','reference']
    date_keys   = ['date','due','deadline','scheduled']
    platform_keys = ['platform','site']

    for keys, field in [
        (name_keys,'name'), (topic_keys,'topic'), (cat_keys,'category'),
        (diff_keys,'difficulty'), (link_keys,'problem_link'), (res_keys,'resource_link'),
        (date_keys,'date'), (platform_keys,'platform')
    ]:
        for k in keys:
            if k in cols_lower:
                mapping[field] = cols_lower[k]
                break

    return mapping

# ── Detect category ────────────────────────────────
def detect_category(sheet_name, columns):
    sheet_lower = sheet_name.lower()
    cat_map = {
        'dsa': 'DSA', 'leetcode': 'DSA', 'coding': 'DSA',
        'apti': 'Aptitude', 'aptitude': 'Aptitude', 'quant': 'Aptitude',
        'verbal': 'Verbal', 'english': 'Verbal',
        'interview': 'Interview', 'hr': 'HR'
    }
    for key, cat in cat_map.items():
        if key in sheet_lower:
            return cat
    return 'DSA'

# ── Assign goals ───────────────────────────────────
def assign_goals():
    with get_db() as db:
        today = date.today()
        week_start = (today - timedelta(days=today.weekday())).isoformat()
        week_end = (today + timedelta(days=6-today.weekday())).isoformat()
        db.execute(
            "INSERT OR IGNORE INTO weekly_goals (week_start, week_end) VALUES (?,?)",
            (week_start, week_end)
        )
        done_this_week = db.execute(
            "SELECT COUNT(*) as c FROM problems WHERE status='Solved' AND created_at >= ?",
            (week_start,)
        ).fetchone()['c']
        db.execute(
            "UPDATE weekly_goals SET done_problems=? WHERE week_start=?",
            (done_this_week, week_start)
        )

        month_start = today.replace(day=1).isoformat()
        db.execute(
            "INSERT OR IGNORE INTO monthly_goals (month, year) VALUES (?,?)",
            (today.strftime('%B'), today.year)
        )
        done_this_month = db.execute(
            "SELECT COUNT(*) as c FROM problems WHERE status='Solved' AND created_at >= ?",
            (month_start,)
        ).fetchone()['c']
        db.execute(
            "UPDATE monthly_goals SET done_problems=? WHERE month=? AND year=?",
            (done_this_month, today.strftime('%B'), today.year)
        )
        db.commit()

# ── NEW: Extract Topic Resources ───────────────────
def extract_topic_resources(topic):
    status = get_student_status()
    
    prompt = f"""For topic '{topic}' (targeting {status['target_companies']}), return ONLY JSON:
{{"youtube": "url", "article": "url", "practice": "url"}}
Use real working URLs. No explanation."""
    
    response, _ = ask_ai(prompt)
    
    try:
        clean = re.sub(r'```json\s*|\s*```', '', response)
        return json.loads(clean)
    except:
        # Fallback
        topic_lower = topic.lower()
        fallbacks = {
            "binary search": {"youtube": "https://youtu.be/GU7DpgHINWQ", "article": "https://www.geeksforgeeks.org/binary-search/", "practice": "https://leetcode.com/tag/binary-search/"},
            "array": {"youtube": "https://youtu.be/2ZLl8GAk1X4", "article": "https://www.geeksforgeeks.org/array-data-structure/", "practice": "https://leetcode.com/tag/array/"},
            "dynamic programming": {"youtube": "https://youtu.be/oBt53YbR9Kk", "article": "https://www.geeksforgeeks.org/dynamic-programming/", "practice": "https://leetcode.com/tag/dynamic-programming/"},
        }
        for key, val in fallbacks.items():
            if key in topic_lower:
                return val
        return {"youtube": f"https://youtube.com/results?search_query={topic.replace(' ', '+')}", "article": f"https://www.geeksforgeeks.org/search/?q={topic.replace(' ', '+')}", "practice": "https://leetcode.com/problemset/all/"}

# ── NEW: Calculate Readiness Score ─────────────────
def calculate_readiness_score():
    with get_db() as db:
        cats = db.execute(
            "SELECT category, COUNT(*) as total, SUM(CASE WHEN status='Solved' THEN 1 ELSE 0 END) as solved FROM problems GROUP BY category"
        ).fetchall()
        
        courses_total = db.execute("SELECT SUM(total_topics) as t FROM courses").fetchone()['t'] or 1
        courses_done = db.execute("SELECT COUNT(*) as c FROM course_topics WHERE status='Done'").fetchone()['c']
        projects_total = db.execute("SELECT COUNT(*) as c FROM milestones").fetchone()['c'] or 1
        projects_done = db.execute("SELECT COUNT(*) as c FROM milestones WHERE status='Done'").fetchone()['c']
        
        settings = {r['key']: r['value'] for r in db.execute("SELECT * FROM settings").fetchall()}
        goal = int(settings.get('daily_goal', 10))
        streak = 0
        check = date.today()
        while True:
            ds = check.isoformat()
            log = db.execute("SELECT problems_solved FROM daily_log WHERE log_date=?", (ds,)).fetchone()
            if not log or log['problems_solved'] < goal:
                break
            streak += 1
            check -= timedelta(days=1)
    
    dsa = next((c for c in cats if c['category'] == 'DSA'), None)
    apt = next((c for c in cats if c['category'] == 'Aptitude'), None)
    verb = next((c for c in cats if c['category'] == 'Verbal'), None)
    hr = next((c for c in cats if c['category'] == 'HR'), None)
    
    dsa_pct = (dsa['solved'] / dsa['total'] * 100) if dsa and dsa['total'] else 0
    apt_pct = (apt['solved'] / apt['total'] * 100) if apt and apt['total'] else 0
    verb_pct = (verb['solved'] / verb['total'] * 100) if verb and verb['total'] else 0
    hr_pct = (hr['solved'] / hr['total'] * 100) if hr and hr['total'] else 0
    course_pct = (courses_done / courses_total * 100) if courses_total else 0
    project_pct = (projects_done / projects_total * 100) if projects_total else 0
    
    score = dsa_pct * 0.30 + apt_pct * 0.20 + course_pct * 0.20 + project_pct * 0.15 + verb_pct * 0.10 + hr_pct * 0.05 + min(streak * 2, 10)
    return min(100, int(score))