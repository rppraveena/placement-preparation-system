import sqlite3
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = os.path.join(os.path.dirname(__file__), 'minetracker.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db():
    with get_db() as db:
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

        db.execute('''CREATE TABLE IF NOT EXISTS daily_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT NOT NULL UNIQUE,
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

        db.execute('''CREATE TABLE IF NOT EXISTS daily_plan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_date TEXT NOT NULL,
            problem_id INTEGER,
            order_index INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Pending',
            plan_type TEXT DEFAULT 'problem',
            FOREIGN KEY (problem_id) REFERENCES problems(id)
        )''')

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

        cur = db.execute("PRAGMA table_info(projects)")
        columns = [c[1] for c in cur.fetchall()]
        if 'status' not in columns:
            db.execute("ALTER TABLE projects ADD COLUMN status TEXT DEFAULT 'In Progress'")

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

        db.execute('''CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            import_date TEXT DEFAULT (date('now')),
            total_imported INTEGER DEFAULT 0,
            category TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            protected INTEGER DEFAULT 0
        )''')

        cur = db.execute("PRAGMA table_info(imports)")
        imp_cols = [c[1] for c in cur.fetchall()]
        if 'protected' not in imp_cols:
            db.execute("ALTER TABLE imports ADD COLUMN protected INTEGER DEFAULT 0")

        db.execute('''CREATE TABLE IF NOT EXISTS ai_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_date TEXT DEFAULT (date('now')),
            feedback_type TEXT DEFAULT 'daily',
            content TEXT DEFAULT '',
            model_used TEXT DEFAULT ''
        )''')

        db.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')

        # News cache table - stores fetched articles with daily expiry
        db.execute('''CREATE TABLE IF NOT EXISTS news_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cache_date TEXT NOT NULL,
            articles_json TEXT DEFAULT '[]'
        )''')

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

        db.execute('''CREATE TABLE IF NOT EXISTS monthly_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,
            year INTEGER NOT NULL,
            target_problems INTEGER DEFAULT 300,
            done_problems INTEGER DEFAULT 0,
            topics_covered TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        )''')

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

        default_courses = [
            ('Python', 'Py', 'Master Python from basics to advanced ML libraries'),
            ('Machine Learning & AI', 'ML', 'Numpy, Pandas, Sklearn, Deep Learning'),
            ('Data Visualization', 'DV', 'Matplotlib, Seaborn, Plotly, Tableau'),
            ('SQL', 'SQL', 'Basics to advanced Window Functions & Optimization'),
            ('DevOps', 'DO', 'Git, Docker, CI/CD, Linux basics'),
            ('MLOps', 'MO', 'Model deployment, APIs, Monitoring'),
            ('HTML/CSS/JS', 'WB', 'Frontend basics to responsive design'),
            ('DSA Patterns', 'DS', 'All coding patterns for placement interviews'),
        ]
        for name, icon, desc in default_courses:
            existing = db.execute("SELECT id FROM courses WHERE name=?", (name,)).fetchone()
            if not existing:
                db.execute("INSERT INTO courses (name,icon,description) VALUES (?,?,?)", (name, icon, desc))

        default_algos = [
            ('Two Pointers', 'Array/String', 'Use two indices to solve problems in O(n)', 'Sorted arrays, pair sum, palindrome check', 'https://youtu.be/On03HWe2tZM', 'https://leetcode.com/tag/two-pointers/'),
            ('Sliding Window', 'Array/String', 'Maintain a window of elements as you move through array', 'Max sum subarray of size k, longest substring without repeat', 'https://youtu.be/MK-NZ4hN7rs', 'https://leetcode.com/tag/sliding-window/'),
            ('Binary Search', 'Search', 'Eliminate half the search space each step — O(log n)', 'Sorted array search, find first/last occurrence, peak element', 'https://youtu.be/GU7DpgHINWQ', 'https://www.geeksforgeeks.org/binary-search/'),
            ('Backtracking', 'Recursion', 'Explore all possibilities recursively, backtrack on failure', 'Permutations, combinations, N-Queens, Sudoku solver', 'https://youtu.be/DKCbsiDBN6c', 'https://leetcode.com/tag/backtracking/'),
            ('BFS (Graph)', 'Graph', 'Level-by-level traversal using a queue — O(V+E)', 'Shortest path, connected components, word ladder', 'https://youtu.be/pcKY4hjDrxk', 'https://www.geeksforgeeks.org/breadth-first-search-or-bfs-for-a-graph/'),
            ('DFS (Graph)', 'Graph', 'Depth-first traversal using stack or recursion — O(V+E)', 'Cycle detection, topological sort, number of islands', 'https://youtu.be/7fujbpJ0LB4', 'https://www.geeksforgeeks.org/depth-first-search-or-dfs-for-a-graph/'),
            ('Dynamic Programming Basics', 'Dynamic Programming', 'Memoize or tabulate subproblem results to avoid recomputation', 'Climbing stairs, knapsack, coin change, longest common subsequence', 'https://youtu.be/oBt53YbR9Kk', 'https://leetcode.com/tag/dynamic-programming/'),
            ('Dutch National Flag', 'Sorting', 'Sort array of 0,1,2 in one pass using 3 pointers', 'Sort colors, segregate 0s and 1s', 'https://youtu.be/4xbWSRZHqac', 'https://leetcode.com/problems/sort-colors/'),
            ('Fast & Slow Pointers', 'Linked List', 'Floyd cycle detection — slow moves 1 step, fast moves 2', 'Cycle detection, middle of linked list, happy number', 'https://youtu.be/gBTe7lFR3vc', 'https://leetcode.com/tag/linked-list/'),
            ('Greedy Algorithms', 'Greedy', 'Make locally optimal choice at each step', 'Activity selection, fractional knapsack, jump game', 'https://youtu.be/HzeK7g8cD0Y', 'https://leetcode.com/tag/greedy/'),
            ('Hash Map', 'Hashing', 'O(1) average lookup using key-value pairs', 'Two sum, anagram check, frequency counter, first unique character', 'https://youtu.be/7_nF7vCxVBM', 'https://leetcode.com/tag/hash-table/'),
            ('Kadane Algorithm', 'Dynamic Programming', 'Track max subarray sum ending at each index — O(n)', 'Maximum subarray sum, best time to buy/sell stock', 'https://youtu.be/5WZl3MMT0Eg', 'https://leetcode.com/problems/maximum-subarray/'),
            ('Merge Intervals', 'Array', 'Sort intervals then merge overlapping ones', 'Meeting rooms, calendar overlap, non-overlapping intervals', 'https://youtu.be/44H3cEC2fFM', 'https://leetcode.com/tag/intervals/'),
            ('Merge Sort', 'Sorting', 'Divide array, sort halves, merge — O(n log n) stable sort', 'Inversion count, sort linked list, external sorting', 'https://youtu.be/4VqmGXwarmY', 'https://www.geeksforgeeks.org/merge-sort/'),
            ('Monotonic Stack', 'Stack', 'Stack that maintains increasing or decreasing order', 'Next greater element, daily temperatures, trapping rain water', 'https://youtu.be/85LWui3FlVk', 'https://leetcode.com/tag/stack/'),
            ('Quick Sort', 'Sorting', 'Partition around pivot, divide and conquer — avg O(n log n)', 'General sorting, kth largest element (quick select)', 'https://youtu.be/Hoixgm4-P4M', 'https://www.geeksforgeeks.org/quick-sort/'),
            ('Reverse Linked List', 'Linked List', 'Reverse singly linked list iteratively or recursively', 'Palindrome linked list, reverse groups of K', 'https://youtu.be/G0_I-ZF0S38', 'https://leetcode.com/problems/reverse-linked-list/'),
            ('Top K Elements (Heap)', 'Heap', 'Use min/max heap to maintain K elements efficiently', 'Top K frequent, K largest, K closest points to origin', 'https://youtu.be/YPTqKIgVk-k', 'https://leetcode.com/tag/heap-priority-queue/'),
            ('Trie', 'Tree', 'Prefix tree for efficient string prefix operations O(m)', 'Autocomplete, word search, longest common prefix', 'https://youtu.be/oobqoCJlHA0', 'https://leetcode.com/tag/trie/'),
        ]
        for algo in default_algos:
            existing = db.execute("SELECT id FROM algorithms WHERE name=?", (algo[0],)).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO algorithms (name,pattern,description,when_to_use,youtube_link,article_link,mastery) VALUES (?,?,?,?,?,?,?)",
                    (algo[0], algo[1], algo[2], algo[3], algo[4], algo[5], 'Not Started')
                )

        db.commit()
