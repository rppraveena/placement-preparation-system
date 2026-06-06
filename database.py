import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'minetracker.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db() as db:

        # ── Problems (DSA, Apti, Verbal, Interview, HR) ──────────
        db.execute('''CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT DEFAULT 'DSA',
            topic TEXT DEFAULT '',
            subtopic TEXT DEFAULT '',
            difficulty TEXT DEFAULT 'Medium',
            platform TEXT DEFAULT 'LeetCode',
            problem_link TEXT DEFAULT '',
            resource_link TEXT DEFAULT '',
            status TEXT DEFAULT 'Pending',
            attempts INTEGER DEFAULT 0,
            scheduled_date TEXT DEFAULT '',
            week_number INTEGER DEFAULT 0,
            month_number INTEGER DEFAULT 0,
            import_batch TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (date('now'))
        )''')

        # ── Courses ───────────────────────────────────────────────
        db.execute('''CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            icon TEXT DEFAULT '📚',
            description TEXT DEFAULT '',
            total_topics INTEGER DEFAULT 0,
            completed_topics INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            last_studied TEXT DEFAULT '',
            created_at TEXT DEFAULT (date('now'))
        )''')

        # ── Course Topics ─────────────────────────────────────────
        db.execute('''CREATE TABLE IF NOT EXISTS course_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER,
            topic_name TEXT NOT NULL,
            description TEXT DEFAULT '',
            youtube_link TEXT DEFAULT '',
            article_link TEXT DEFAULT '',
            practice_link TEXT DEFAULT '',
            status TEXT DEFAULT 'Not Started',
            order_index INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            completed_at TEXT DEFAULT '',
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )''')

        # ── Algorithms & Patterns ─────────────────────────────────
        db.execute('''CREATE TABLE IF NOT EXISTS algorithms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            pattern TEXT DEFAULT '',
            description TEXT DEFAULT '',
            when_to_use TEXT DEFAULT '',
            youtube_link TEXT DEFAULT '',
            article_link TEXT DEFAULT '',
            mastery TEXT DEFAULT 'Not Started',
            total_problems INTEGER DEFAULT 0,
            solved_problems INTEGER DEFAULT 0
        )''')

        # ── Daily Log ─────────────────────────────────────────────
        db.execute('''CREATE TABLE IF NOT EXISTS daily_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT NOT NULL,
            problems_solved INTEGER DEFAULT 0,
            problems_attempted INTEGER DEFAULT 0,
            problems_skipped INTEGER DEFAULT 0,
            problems_target INTEGER DEFAULT 10,
            topic_studied TEXT DEFAULT '',
            course_studied TEXT DEFAULT '',
            study_hours REAL DEFAULT 0,
            mood TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        )''')

        # ── Daily Plan (AI generated checklist) ──────────────────
        db.execute('''CREATE TABLE IF NOT EXISTS daily_plan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_date TEXT NOT NULL,
            problem_id INTEGER,
            order_index INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Pending',
            plan_type TEXT DEFAULT 'problem',
            FOREIGN KEY (problem_id) REFERENCES problems(id)
        )''')

        # ── Projects ──────────────────────────────────────────────
        db.execute('''CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            tech_stack TEXT DEFAULT '',
            start_date TEXT DEFAULT (date('now')),
            target_date TEXT DEFAULT '',
            status TEXT DEFAULT 'In Progress',
            github_link TEXT DEFAULT '',
            completion_pct INTEGER DEFAULT 0
        )''')

        # ── Milestones ────────────────────────────────────────────
        db.execute('''CREATE TABLE IF NOT EXISTS milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            deadline TEXT DEFAULT '',
            status TEXT DEFAULT 'Pending',
            order_index INTEGER DEFAULT 0,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )''')

        # ── Imports tracker ───────────────────────────────────────
        db.execute('''CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            import_date TEXT DEFAULT (date('now')),
            total_imported INTEGER DEFAULT 0,
            category TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        )''')

        # ── AI Feedback log ───────────────────────────────────────
        db.execute('''CREATE TABLE IF NOT EXISTS ai_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_date TEXT DEFAULT (date('now')),
            feedback_type TEXT DEFAULT 'daily',
            content TEXT DEFAULT '',
            model_used TEXT DEFAULT ''
        )''')

        # ── Settings ──────────────────────────────────────────────
        db.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')

        # ── Weekly Goals ──────────────────────────────────────────
        db.execute('''CREATE TABLE IF NOT EXISTS weekly_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            target_problems INTEGER DEFAULT 70,
            done_problems INTEGER DEFAULT 0,
            target_courses INTEGER DEFAULT 2,
            done_courses INTEGER DEFAULT 0,
            notes TEXT DEFAULT ''
        )''')

        # ── Monthly Goals ─────────────────────────────────────────
        db.execute('''CREATE TABLE IF NOT EXISTS monthly_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,
            year INTEGER NOT NULL,
            target_problems INTEGER DEFAULT 300,
            done_problems INTEGER DEFAULT 0,
            topics_covered TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        )''')

        # Default settings
        defaults = {
            'name': 'Student',
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
            db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))

        # Default courses
        default_courses = [
            ('Python', '🐍', 'Master Python from basics to advanced ML libraries'),
            ('Machine Learning & AI', '🤖', 'Numpy, Pandas, Sklearn, Deep Learning'),
            ('Data Visualization', '📊', 'Matplotlib, Seaborn, Plotly, Tableau'),
            ('SQL', '🗄️', 'Basics to advanced Window Functions & Optimization'),
            ('DevOps', '⚙️', 'Git, Docker, CI/CD, Linux basics'),
            ('MLOps', '🔧', 'Model deployment, APIs, Monitoring'),
            ('HTML/CSS/JS', '🌐', 'Frontend basics to responsive design'),
            ('DSA Patterns', '🧠', 'All coding patterns for placement interviews'),
        ]
        for name, icon, desc in default_courses:
            existing = db.execute("SELECT id FROM courses WHERE name=?", (name,)).fetchone()
            if not existing:
                db.execute("INSERT INTO courses (name,icon,description) VALUES (?,?,?)", (name, icon, desc))

        # Default algorithms
        default_algos = [
            ('Sliding Window', 'Array/String', 'Used for subarrays/substrings of fixed or variable size', 'When you need max/min/count in a contiguous subarray', 'https://youtube.com/watch?v=MK-NZ4hN7rs', 'https://leetcode.com/tag/sliding-window/'),
            ('Two Pointers', 'Array/String', 'Two indices moving toward each other or same direction', 'Sorted arrays, pair sum, palindrome check', 'https://youtube.com/watch?v=On03HWe2tZM', 'https://leetcode.com/tag/two-pointers/'),
            ('Binary Search', 'Search', 'Divide search space in half each iteration', 'Sorted array, find element, minimize/maximize', 'https://youtube.com/watch?v=GU7DpgHINWQ', 'https://leetcode.com/tag/binary-search/'),
            ('Fast & Slow Pointers', 'LinkedList', 'Two pointers at different speeds to detect cycles', 'Cycle detection, middle of linked list', 'https://youtube.com/watch?v=gBTe7lFR3vc', 'https://leetcode.com/tag/linked-list/'),
            ('Dynamic Programming', 'DP', 'Break problem into subproblems, store results', 'Optimization, counting, decision problems', 'https://youtube.com/watch?v=oBt53YbR9Kk', 'https://leetcode.com/tag/dynamic-programming/'),
            ('Graph BFS/DFS', 'Graph', 'Traverse graph level by level or depth first', 'Shortest path, connected components, cycle detection', 'https://youtube.com/watch?v=pcKY4hjDrxk', 'https://leetcode.com/tag/graph/'),
            ('Backtracking', 'Recursion', 'Try all possibilities and backtrack on failure', 'Permutations, combinations, N-Queens, Sudoku', 'https://youtube.com/watch?v=DKCbsiDBN6c', 'https://leetcode.com/tag/backtracking/'),
            ('Merge Intervals', 'Array', 'Merge overlapping intervals after sorting', 'Scheduling, calendar problems', 'https://youtube.com/watch?v=44H3cEC2fFM', 'https://leetcode.com/tag/intervals/'),
            ('Top K Elements', 'Heap', 'Use heap to find K largest/smallest elements', 'Top K frequent, K closest points', 'https://youtube.com/watch?v=YPTqKIgVk-k', 'https://leetcode.com/tag/heap-priority-queue/'),
            ('Trie', 'Tree', 'Prefix tree for string problems', 'Autocomplete, word search, prefix matching', 'https://youtube.com/watch?v=oobqoCJlHA0', 'https://leetcode.com/tag/trie/'),
        ]
        for algo in default_algos:
            existing = db.execute("SELECT id FROM algorithms WHERE name=?", (algo[0],)).fetchone()
            if not existing:
                db.execute("INSERT INTO algorithms (name,pattern,description,when_to_use,youtube_link,article_link) VALUES (?,?,?,?,?,?)", algo)

        db.commit()
    print("✅ Database initialized successfully")

if __name__ == '__main__':
    init_db()
