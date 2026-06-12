import os
import re
import json
import requests
from datetime import date, timedelta, datetime
from database import get_db

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except Exception:
    GROQ_AVAILABLE = False

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except Exception:
    GEMINI_AVAILABLE = False

try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

# ─── WEB SEARCH FOR RESOURCES ─────────────────────────────────────────────────
FALLBACK_RESOURCES = {
    'array': ['https://takeuforward.org/arrays/', 'https://www.geeksforgeeks.org/array-data-structure/', 'https://leetcode.com/tag/array/'],
    'binary search': ['https://takeuforward.org/binary-search/', 'https://www.geeksforgeeks.org/binary-search/', 'https://leetcode.com/tag/binary-search/'],
    'dp': ['https://takeuforward.org/dynamic-programming/', 'https://www.geeksforgeeks.org/dynamic-programming/', 'https://leetcode.com/tag/dynamic-programming/'],
    'dynamic programming': ['https://takeuforward.org/dynamic-programming/', 'https://www.geeksforgeeks.org/dynamic-programming/', 'https://leetcode.com/tag/dynamic-programming/'],
    'graph': ['https://takeuforward.org/graph/', 'https://www.geeksforgeeks.org/graph-data-structure/', 'https://leetcode.com/tag/graph/'],
    'sql': ['https://www.geeksforgeeks.org/sql-tutorial/', 'https://leetcode.com/studyplan/sql-50/', 'https://www.w3schools.com/sql/'],
    'oops': ['https://www.geeksforgeeks.org/object-oriented-programming-oops-concept-in-java/', 'https://takeuforward.org/oops/', 'https://www.youtube.com/watch?v=BSVKUk48Kqc'],
    'two pointers': ['https://leetcode.com/tag/two-pointers/', 'https://takeuforward.org/', 'https://www.geeksforgeeks.org/two-pointers-technique/'],
    'sliding window': ['https://leetcode.com/tag/sliding-window/', 'https://www.geeksforgeeks.org/window-sliding-technique/', 'https://takeuforward.org/'],
    'stack': ['https://leetcode.com/tag/stack/', 'https://www.geeksforgeeks.org/stack-data-structure/', 'https://takeuforward.org/'],
    'tree': ['https://leetcode.com/tag/tree/', 'https://www.geeksforgeeks.org/binary-tree-data-structure/', 'https://takeuforward.org/'],
    'sorting': ['https://www.geeksforgeeks.org/sorting-algorithms/', 'https://leetcode.com/tag/sorting/', 'https://visualgo.net/en/sorting'],
    'aptitude': ['https://www.indiabix.com/', 'https://www.geeksforgeeks.org/aptitude-questions-and-answers/', 'https://www.freshersworld.com/aptitude'],
    'linked list': ['https://leetcode.com/tag/linked-list/', 'https://www.geeksforgeeks.org/data-structures/linked-list/', 'https://takeuforward.org/'],
    'heap': ['https://leetcode.com/tag/heap-priority-queue/', 'https://www.geeksforgeeks.org/heap-data-structure/', 'https://takeuforward.org/'],
    'backtracking': ['https://leetcode.com/tag/backtracking/', 'https://www.geeksforgeeks.org/backtracking-algorithms/', 'https://takeuforward.org/'],
}

def search_web_for_resources(topic, max_results=4):
    urls = []
    if DDGS_AVAILABLE:
        try:
            with DDGS() as ddgs:
                query = f"{topic} tutorial site:youtube.com OR site:geeksforgeeks.org OR site:takeuforward.org OR site:neetcode.io OR site:leetcode.com"
                results = list(ddgs.text(query, max_results=max_results + 3))
                for r in results:
                    url = r.get('href', '')
                    if url and any(d in url for d in ['youtube.com', 'youtu.be', 'geeksforgeeks.org', 'takeuforward.org', 'neetcode.io', 'leetcode.com']):
                        urls.append(url)
        except Exception as e:
            print(f"DDGS search failed: {e}")

    if not urls:
        topic_lower = topic.lower()
        for key, fall in FALLBACK_RESOURCES.items():
            if key in topic_lower:
                urls = fall[:]
                break
        if not urls:
            urls = [
                f'https://www.geeksforgeeks.org/search/?q={topic.replace(" ", "+")}',
                f'https://leetcode.com/search/?q={topic.replace(" ", "+")}',
                f'https://www.youtube.com/results?search_query={topic.replace(" ", "+")}+tutorial',
            ]

    return urls[:max_results]


# ─── EXCEL COLUMN MAPPING ─────────────────────────────────────────────────────
def map_excel_columns(columns):
    cols_lower = {c.lower().strip(): c for c in columns}
    mapping = {}
    name_keys   = ['problem','task','name','title','question','work','activity','item',
                   'problem name','task name','question name','dsa task','dsa task 1',
                   'dsa task 2','dsa task 3','exercise','subtopic','problem title']
    topic_keys  = ['topic','subject','chapter','area','concept','tag','category name']
    cat_keys    = ['category','cat','type','section','domain']
    diff_keys   = ['difficulty','level','hard','easy','medium','diff','priority']
    link_keys   = ['link','url','problem link','leetcode','gfg','solution','problem url',
                   'lc link','lc','question link','coding link','practice link','solve link',
                   'problem_link','leetcode link','leetcode url','lc url','question url',
                   'hackerrank','codechef','codeforces','interviewbit','coding url','prob link',
                   'prob url','ques link','ques url']
    res_keys    = ['resource','resource link','reference','ref','article','video','youtube',
                   'notes link','resource url','tutorial','study link','explanation',
                   'resource_link','notes','material','study material']
    date_keys   = ['date','due','deadline','scheduled','day','due date','schedule date',
                   'planned date','day no','day number']
    platform_keys = ['platform','site','source','website']
    for keys, field in [
        (name_keys,'name'),(topic_keys,'topic'),(cat_keys,'category'),
        (diff_keys,'difficulty'),(link_keys,'problem_link'),(res_keys,'resource_link'),
        (date_keys,'date'),(platform_keys,'platform')
    ]:
        for k in keys:
            if k in cols_lower:
                mapping[field] = cols_lower[k]
                break
    return mapping

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
    if 'neetcode' in link: return 'NeetCode'
    if 'interviewbit' in link: return 'InterviewBit'
    if 'w3schools' in link: return 'W3Schools'
    if 'visualgo' in link: return 'VisuAlgo'
    return 'Custom'

def detect_category(sheet_name, columns):
    sheet_lower = sheet_name.lower()
    cat_map = {
        'dsa':'DSA','leetcode':'DSA','coding':'DSA','data structure':'DSA','algorithm':'DSA','algo':'DSA',
        'apti':'Aptitude','aptitude':'Aptitude','quant':'Aptitude','math':'Aptitude',
        'verbal':'Verbal','english':'Verbal','communication':'Verbal',
        'interview':'Interview','hr':'HR','behavioral':'HR',
        'sql':'Interview','dbms':'Interview','database':'Interview',
        'oops':'Interview','oop':'Interview','object':'Interview',
        'network':'Interview','cn':'Interview',
        'linux':'Interview','os':'Interview','operating':'Interview',
        'system_design':'Interview','system design':'Interview','roadmap':'Interview',
    }
    for key, cat in cat_map.items():
        if key in sheet_lower:
            return cat
    for col in columns:
        col_lower = col.lower()
        if 'aptitude' in col_lower or 'indiabix' in col_lower: return 'Aptitude'
        if 'verbal' in col_lower or 'hr' in col_lower: return 'Verbal'
    return 'DSA'

def smart_parse_sheet(df, sheet_name):
    rows_out = []
    if df.empty:
        return rows_out
    cols = [c.strip() for c in df.columns]
    cols_lower = [c.lower() for c in cols]
    category = detect_category(sheet_name, cols)
    mapping = map_excel_columns(cols)

    if 'name' in mapping:
        for _, row in df.iterrows():
            name = str(row.get(mapping['name'], '')).strip()
            if not name or name.lower() in ('nan','none',''): continue
            task_date = ''
            raw_date = row.get(mapping.get('date','__x__'), None)
            if raw_date is not None and str(raw_date).lower() not in ('nan','none',''):
                try:
                    import pandas as pd
                    if hasattr(raw_date, 'date'):
                        task_date = raw_date.date().isoformat()
                    else:
                        task_date = pd.to_datetime(str(raw_date)).date().isoformat()
                except Exception:
                    pass
            def clean(val):
                v = str(row.get(mapping.get(val,'__x__'), '')).strip()
                return '' if v.lower() in ('nan','none') else v
            topic = clean('topic')
            diff  = clean('difficulty')
            plink = clean('problem_link')
            rlink = clean('resource_link')
            platform = clean('platform')
            diff_val = diff.capitalize() if diff.lower() in ('easy','medium','hard') else \
                       'High' if diff.lower() in ('must','high','critical') else \
                       'Medium' if diff.lower() in ('good','medium','moderate') else 'Medium'
            if plink and not plink.startswith('http') and '.' in plink:
                plink = 'https://' + plink.lstrip('/')
            if rlink and not rlink.startswith('http') and '.' in rlink:
                rlink = 'https://' + rlink.lstrip('/')
            if not platform:
                platform = detect_platform(plink)
            rows_out.append({
                'name': name, 'category': category, 'topic': topic,
                'difficulty': diff_val, 'platform': platform,
                'problem_link': plink, 'resource_link': rlink,
                'scheduled_date': task_date, 'status': 'Pending'
            })
        return rows_out

    topic_col = next((cols[i] for i,c in enumerate(cols_lower) if c in ['topic','subject']), None)
    res_col   = next((cols[i] for i,c in enumerate(cols_lower) if c in ['resource','resource link','ref','link','url']), None)
    pri_col   = next((cols[i] for i,c in enumerate(cols_lower) if c in ['priority','difficulty','level','status']), None)
    if topic_col:
        for _, row in df.iterrows():
            name = str(row.get(topic_col, '')).strip()
            if not name or name.lower() in ('nan','none',''): continue
            rlink = str(row.get(res_col, '')).strip() if res_col else ''
            if rlink.lower() in ('nan','none'): rlink = ''
            if rlink and not rlink.startswith('http') and '.' in rlink:
                rlink = 'https://' + rlink.lstrip('/')
            pri = str(row.get(pri_col, '')).strip() if pri_col else ''
            diff_val = 'High' if pri.lower() in ('must','high','critical') else \
                       'Low' if pri.lower() in ('optional','low') else 'Medium'
            rows_out.append({
                'name': name, 'category': category, 'topic': name,
                'difficulty': diff_val, 'platform': detect_platform(rlink),
                'problem_link': rlink, 'resource_link': rlink,
                'scheduled_date': '', 'status': 'Pending'
            })
        return rows_out

    day_col = next((cols[i] for i,cl in enumerate(cols_lower) if cl=='day' or cl.startswith('day ')), None)
    if day_col:
        task_cols = [c for c in cols if c != day_col]
        for _, row in df.iterrows():
            day_val = str(row.get(day_col, '')).strip()
            if day_val.lower() in ('nan','none',''): continue
            for tcol in task_cols:
                val = str(row.get(tcol, '')).strip()
                if not val or val.lower() in ('nan','none',''): continue
                col_lower = tcol.lower()
                if 'dsa' in col_lower: col_cat = 'DSA'
                elif 'apti' in col_lower: col_cat = 'Aptitude'
                elif 'verbal' in col_lower or 'hr' in col_lower: col_cat = 'Verbal'
                elif any(k in col_lower for k in ['interview','system','oops','sql','network','linux']): col_cat = 'Interview'
                else: col_cat = detect_category(tcol, [])
                rows_out.append({
                    'name': val, 'category': col_cat, 'topic': tcol,
                    'difficulty': 'Medium', 'platform': 'Custom',
                    'problem_link': '', 'resource_link': '',
                    'scheduled_date': '', 'status': 'Pending'
                })
        return rows_out

    for _, row in df.iterrows():
        values = [str(v).strip() for v in row.values if str(v).strip().lower() not in ('nan','none','')]
        if not values: continue
        name = values[0]
        rlink = next((v for v in values if v.startswith('http')), '')
        rows_out.append({
            'name': name, 'category': category,
            'topic': values[1] if len(values) > 1 else '',
            'difficulty': 'Medium', 'platform': detect_platform(rlink),
            'problem_link': rlink, 'resource_link': rlink,
            'scheduled_date': '', 'status': 'Pending'
        })
    return rows_out


# ─── NEWS (placement + tech/AI, daily cached) ─────────────────────────────────
PLACEMENT_KEYWORDS = [
    'placement', 'interview', 'hiring', 'internship', 'job', 'career', 'campus',
    'ai', 'artificial intelligence', 'machine learning', 'deep learning', 'llm', 'gpt',
    'python', 'javascript', 'rust', 'go lang', 'programming', 'software', 'developer',
    'data science', 'algorithm', 'coding', 'leetcode', 'tech', 'startup', 'layoff',
    'cloud', 'open source', 'github', 'framework', 'api', 'neural', 'model',
    'gpu', 'chip', 'quantum', 'security', 'blockchain', 'database', 'devops',
]

def _is_relevant(title):
    tl = title.lower()
    return any(kw in tl for kw in PLACEMENT_KEYWORDS)

def _classify_tag(title):
    t = title.lower()
    if any(k in t for k in ['ai','llm','gpt','claude','gemini','neural','model','deep learning','machine learning','data science','hugging face']):
        return 'AI/ML'
    if any(k in t for k in ['placement','interview','hiring','campus','internship','job offer','salary','package']):
        return 'Career'
    if any(k in t for k in ['javascript','typescript','react','vue','node','frontend','css','html','web']):
        return 'Web Dev'
    if any(k in t for k in ['python','rust','go','java','kotlin','swift','c++','programming','compiler']):
        return 'Languages'
    if any(k in t for k in ['cloud','aws','azure','gcp','kubernetes','docker','devops','infra','server']):
        return 'Cloud/DevOps'
    if any(k in t for k in ['security','hack','vulnerability','breach','crypto','encryption']):
        return 'Security'
    if any(k in t for k in ['startup','funding','ipo','acquisition','layoff']):
        return 'Industry'
    if any(k in t for k in ['chip','gpu','nvidia','intel','amd','hardware','quantum','semiconductor']):
        return 'Hardware'
    if any(k in t for k in ['open source','github','git','linux','android','ios']):
        return 'Open Source'
    return 'Tech'

def fetch_tech_news(limit=9):
    today_str = date.today().isoformat()
    with get_db() as db:
        cached = db.execute("SELECT articles_json FROM news_cache WHERE cache_date=?", (today_str,)).fetchone()
        if cached:
            try:
                arts = json.loads(cached['articles_json'])
                if arts:
                    return arts[:limit]
            except Exception:
                pass

    articles = []

    # Source 1: Hacker News top stories (only placement/tech relevant)
    try:
        hn_ids = requests.get('https://hacker-news.firebaseio.com/v1/topstories.json', timeout=6).json()
        if hn_ids and isinstance(hn_ids, list):
            for sid in hn_ids[:30]:
                if len(articles) >= 12:
                    break
                try:
                    story = requests.get(f'https://hacker-news.firebaseio.com/v1/item/{sid}.json', timeout=3).json()
                    if story and story.get('url') and story.get('score', 0) > 20:
                        title = story.get('title', '')
                        if _is_relevant(title):
                            articles.append({
                                'title': title[:120],
                                'url': story['url'],
                                'source': 'Hacker News',
                                'score': story.get('score', 0),
                                'tag': _classify_tag(title)
                            })
                except Exception:
                    continue
    except Exception as e:
        print(f"HN error: {e}")

    # Source 2: Dev.to placement/tech articles
    try:
        for tag in ['career', 'programming', 'python', 'ai', 'javascript']:
            resp = requests.get(f'https://dev.to/api/articles?tag={tag}&per_page=5&top=1',
                                headers={'User-Agent': 'MineTracker/2.0'}, timeout=5).json()
            for a in resp:
                title = a.get('title', '')
                url = a.get('url', '')
                if title and url and _is_relevant(title):
                    articles.append({
                        'title': title[:120],
                        'url': url,
                        'source': 'Dev.to',
                        'tag': a.get('tag_list', ['Tech'])[0].upper() if a.get('tag_list') else _classify_tag(title),
                        'score': a.get('public_reactions_count', 0)
                    })
            if len(articles) >= 14:
                break
    except Exception as e:
        print(f"Dev.to error: {e}")

    # Source 3: The Verge AI feed
    try:
        import feedparser
        feed = feedparser.parse('https://www.theverge.com/rss/ai-artificial-intelligence/index.xml')
        for entry in feed.entries[:5]:
            title = entry.get('title', '')
            link = entry.get('link', '')
            if title and link:
                articles.append({'title': title[:120], 'url': link, 'source': 'The Verge', 'tag': 'AI/ML', 'score': 0})
    except Exception as e:
        print(f"The Verge error: {e}")

    # Source 4: GitHub Trending via RSS
    try:
        import feedparser
        feed = feedparser.parse('https://github.com/trending.rss')
        for entry in feed.entries[:4]:
            title = entry.get('title', '')
            link = entry.get('link', '')
            if title and link:
                articles.append({'title': title[:120], 'url': link, 'source': 'GitHub Trending', 'tag': 'Open Source', 'score': 0})
    except Exception as e:
        print(f"GitHub RSS error: {e}")

    # Source 5: GeeksForGeeks jobs/placement RSS
    try:
        import feedparser
        gfg = feedparser.parse('https://www.geeksforgeeks.org/feed/')
        for entry in gfg.entries[:6]:
            title = entry.get('title', '')
            link = entry.get('link', '')
            if title and link and _is_relevant(title):
                articles.append({'title': title[:120], 'url': link, 'source': 'GeeksForGeeks', 'tag': _classify_tag(title), 'score': 0})
    except Exception as e:
        print(f"GFG RSS error: {e}")

    # Deduplicate
    seen = set()
    unique = []
    for a in articles:
        key = a['title'][:50].lower()
        if key not in seen:
            seen.add(key)
            unique.append(a)

    unique.sort(key=lambda x: x.get('score', 0), reverse=True)

    if not unique:
        unique = [
            {'title': 'Top 10 Coding Interview Questions for 2026 Placements', 'url': 'https://www.geeksforgeeks.org/top-10-algorithms-in-interview-questions/', 'source': 'GeeksForGeeks', 'tag': 'Career', 'score': 100},
            {'title': 'How to Crack TCS NQT 2026 – Complete Preparation Guide', 'url': 'https://www.geeksforgeeks.org/tcs-nqt-interview-preparation/', 'source': 'GeeksForGeeks', 'tag': 'Career', 'score': 95},
            {'title': 'DSA Roadmap for Placement – Must-Do Topics', 'url': 'https://takeuforward.org/interviews/strivers-sde-sheet-top-coding-interview-problems/', 'source': 'TakeUForward', 'tag': 'Career', 'score': 90},
            {'title': 'Google launches Gemini 2.5 – What it means for developers', 'url': 'https://blog.google/technology/ai/', 'source': 'Google Blog', 'tag': 'AI/ML', 'score': 88},
            {'title': 'Python 3.13 Released – New Features Every Dev Should Know', 'url': 'https://www.python.org/downloads/', 'source': 'Python.org', 'tag': 'Languages', 'score': 80},
            {'title': 'Top 50 SQL Interview Questions for Freshers 2026', 'url': 'https://www.interviewbit.com/sql-interview-questions/', 'source': 'InterviewBit', 'tag': 'Career', 'score': 78},
            {'title': 'System Design Basics Every CS Student Must Know', 'url': 'https://www.geeksforgeeks.org/system-design-tutorial/', 'source': 'GeeksForGeeks', 'tag': 'Career', 'score': 75},
            {'title': 'Open Source AI Tools Reshaping the Job Market in 2026', 'url': 'https://github.com/trending', 'source': 'GitHub', 'tag': 'Open Source', 'score': 70},
            {'title': 'Infosys, Wipro & TCS Hiring Trends for 2026 Batch', 'url': 'https://www.geeksforgeeks.org/companies-placement/', 'source': 'GeeksForGeeks', 'tag': 'Career', 'score': 68},
        ]

    result = unique[:limit]

    with get_db() as db:
        db.execute("DELETE FROM news_cache WHERE cache_date != ?", (today_str,))
        db.execute("INSERT OR REPLACE INTO news_cache (cache_date, articles_json) VALUES (?,?)",
                   (today_str, json.dumps(result)))
        db.commit()

    return result


# ─── RAG: USER STATUS CONTEXT ────────────────────────────────────────────────
def get_user_status_context():
    try:
        with get_db() as db:
            settings = {r['key']: r['value'] for r in db.execute("SELECT key,value FROM settings").fetchall()}
            total     = db.execute("SELECT COUNT(*) as c FROM problems").fetchone()['c']
            solved    = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Solved'").fetchone()['c']
            pending   = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Pending'").fetchone()['c']
            skipped   = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Skipped'").fetchone()['c']
            attempted = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Attempted'").fetchone()['c']

            cats = db.execute(
                "SELECT category, COUNT(*) as total, SUM(CASE WHEN status='Solved' THEN 1 ELSE 0 END) as solved FROM problems GROUP BY category"
            ).fetchall()
            cat_breakdown = ", ".join([f"{c['category']}: {c['solved']}/{c['total']}" for c in cats]) or "None"

            streak = 0
            check = date.today() - timedelta(days=1)
            for _ in range(365):
                log = db.execute("SELECT problems_solved FROM daily_log WHERE log_date=?", (check.isoformat(),)).fetchone()
                if not log or log['problems_solved'] < 1:
                    break
                streak += 1
                check -= timedelta(days=1)

            today = date.today().isoformat()
            today_log = db.execute("SELECT * FROM daily_log WHERE log_date=?", (today,)).fetchone()
            solved_today = today_log['problems_solved'] if today_log else 0

            solved_pct = round(solved / total * 100) if total else 0
            cats_with_solved = sum(1 for c in cats if c['solved'] > 0)
            cats_total = len(cats) if cats else 1
            cat_coverage_pct = round(cats_with_solved / cats_total * 100) if cats_total else 0
            readiness = min(100, round(solved_pct * 0.60 + cat_coverage_pct * 0.20 + min(streak, 20)))

            deadline = settings.get('placement_deadline', '2026-10-01')
            days_left = max(0, (date.fromisoformat(deadline) - date.today()).days)
            remaining = pending + attempted
            needed_per_day = round(remaining / days_left, 1) if days_left > 0 else remaining

            plan_rows = db.execute('''
                SELECT p.name, p.category, p.difficulty, p.platform, dp.status
                FROM daily_plan dp JOIN problems p ON dp.problem_id = p.id
                WHERE dp.plan_date = ? ORDER BY dp.order_index
            ''', (today,)).fetchall()

            plan_str = "\n".join([
                f"  {i+1}. {r['name']} [{r['category']} - {r['difficulty']}] on {r['platform']} — {r['status']}"
                for i, r in enumerate(plan_rows)
            ]) or "  No tasks scheduled for today yet."

            name = settings.get('name', 'Student')
            daily_goal = int(settings.get('daily_goal', 10))

            return f"""
[USER CURRENT STATUS — RAG DATA]
Student: {name}
Placement Deadline: {deadline} ({days_left} days left)
Daily Goal: {daily_goal} problems/day
Today's Progress: {solved_today}/{daily_goal} solved
Streak: {streak} days
Readiness Score: {readiness}/100

Problem Bank:
- Total: {total} | Solved: {solved} ({solved_pct}%) | Pending: {pending} | Attempted: {attempted} | Skipped: {skipped}

Category Breakdown: {cat_breakdown}
Target Pace: Need {needed_per_day} problems/day to finish remaining {remaining} problems.

Today's Plan:
{plan_str}
"""
    except Exception as e:
        return f"[USER CURRENT STATUS — Could not load: {e}]"


# ─── API KEY HELPER ───────────────────────────────────────────────────────────
def get_keys():
    try:
        with get_db() as db:
            rows = db.execute("SELECT key,value FROM settings WHERE key LIKE '%api_key%' OR key='ai_provider'").fetchall()
        return {r['key']: r['value'] for r in rows}
    except Exception:
        return {}


# ─── SMART CONTEXT DETECTION ─────────────────────────────────────────────────
# Words that mean the user is asking about THEMSELVES / their own data
_PERSONAL_SIGNALS = [
    'my progress', 'my plan', 'my data', 'my status', 'my streak', 'my score',
    'my weak', 'my strong', 'my performance', 'my problems', 'my solved',
    'how am i', 'how i am', 'how many have i', 'am i ready', 'am i on track',
    'what should i', 'what do i', 'what have i', 'where am i',
    'today\'s plan', 'today\'s task', 'today\'s focus', 'my today',
    'my readiness', 'my deadline', 'my goal', 'my target', 'my pace',
    'give me my', 'show me my', 'tell me my', 'update me', 'status report',
    'placement readiness', 'how ready', 'daily briefing', 'my schedule',
    'i have solved', 'i solved', 'i skipped', 'i attempted',
    'my category', 'my topic', 'my algorithm', 'my course', 'my project',
]

def _needs_personal_context(user_message: str) -> bool:
    """Return True only if the user is asking about their own data."""
    low = user_message.lower()
    return any(signal in low for signal in _PERSONAL_SIGNALS)


# ─── MAIN AI CALL (smart RAG + WEB SEARCH) ────────────────────────────────────
def ask_ai(prompt, system=None):
    user_query = prompt  # keep original for signal detection

    if system is None:
        if _needs_personal_context(user_query):
            # ── PERSONAL mode: inject RAG context, act as placement coach ──
            system = """You are an elite, brutally honest placement coach for a CSE student targeting 2026 placements.

The [USER CURRENT STATUS] block below contains the student's LIVE data from their tracker. You MUST:
1. Quote their exact numbers (solved, pending, streak, readiness score, etc.).
2. Answer specifically about their situation — no generic advice.
3. If they ask "what should I do today?", list only problems from their Today's Plan.
4. Use well-structured Markdown (headings, bullets, links).
5. Be direct, honest, motivating. Under 350 words.

Tone: Mentor, not cheerleader. Use their real data to drive every point."""

            if "[USER CURRENT STATUS" not in prompt:
                status_context = get_user_status_context()
                prompt = f"{status_context}\n\n---\n**USER QUERY:**\n{user_query}"

        else:
            # ── GENERAL mode: act like ChatGPT/Claude for CS questions ──
            system = """You are an expert computer science teacher and placement mentor. You know DSA, system design, SQL, OOPs, aptitude, core CS subjects, and interview preparation deeply.

Answer the user's question clearly and helpfully — like a senior engineer or professor would. Rules:
1. Give complete, accurate explanations with examples, code snippets, or step-by-step breakdowns when useful.
2. If the user asks for resources or links, provide real URLs (LeetCode, GeeksForGeeks, YouTube, NeetCode, etc.).
3. Use clean Markdown (headings, code blocks, bullets).
4. If the topic has common interview angles, mention them briefly.
5. No word limits — give as much detail as needed to actually help.

Tone: Knowledgeable, clear, friendly. Like the best Stack Overflow answer + a senior mentor."""

    # Inject online resources if the query is asking for links/tutorials
    resource_keywords = ['resource', 'tutorial', 'video', 'article', 'practice', 'learn',
                         'how to', 'study', 'material', 'give me', 'explain', 'teach',
                         'where to', 'link', 'reference', 'website', 'site']
    if any(kw in user_query.lower() for kw in resource_keywords):
        # Use only the user's actual question as the search topic
        words = user_query.split()
        topic = ' '.join(words[:12]) if len(words) > 12 else user_query
        fetched_urls = search_web_for_resources(topic, max_results=4)
        if fetched_urls:
            url_block = "\n".join([f"- {url}" for url in fetched_urls])
            prompt += f"\n\n[ONLINE RESOURCES — include these links in your answer]:\n{url_block}"

    keys = get_keys()
    provider = keys.get('ai_provider', 'groq')

    order = []
    if provider == 'openrouter': order = ['openrouter', 'groq', 'gemini']
    elif provider == 'gemini':   order = ['gemini', 'groq', 'openrouter']
    else:                        order = ['groq', 'gemini', 'openrouter']

    for p in order:
        if p == 'openrouter' and keys.get('openrouter_api_key'):
            try:
                headers = {"Authorization": f"Bearer {keys['openrouter_api_key']}", "Content-Type": "application/json"}
                payload = {"model": "google/gemini-2.5-flash", "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ], "max_tokens": 1600}
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=20)
                if res.status_code == 200:
                    return res.json()['choices'][0]['message']['content'], "openrouter"
            except Exception as e:
                print(f"OpenRouter failed: {e}")

        elif p == 'groq' and GROQ_AVAILABLE and keys.get('groq_api_key'):
            try:
                client = Groq(api_key=keys['groq_api_key'])
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                    max_tokens=1200, temperature=0.6
                )
                return response.choices[0].message.content, "groq"
            except Exception as e:
                print(f"Groq failed: {e}")

        elif p == 'gemini' and GEMINI_AVAILABLE and keys.get('gemini_api_key'):
            try:
                genai.configure(api_key=keys['gemini_api_key'])
                model = genai.GenerativeModel('gemini-1.5-flash')
                response = model.generate_content(
                    system + "\n\n" + prompt,
                    generation_config=genai.types.GenerationConfig(max_output_tokens=1200)
                )
                return response.text, "gemini"
            except Exception as e:
                print(f"Gemini failed: {e}")

    return rule_based_feedback(prompt), "rule-based"


# ─── RULE-BASED FALLBACK ──────────────────────────────────────────────────────
def rule_based_feedback(prompt):
    pl = prompt.lower()
    if 'news' in pl: return generate_news_response()
    if 'weekly' in pl or 'week' in pl: return generate_weekly_rule_feedback()
    if 'daily' in pl or 'today' in pl: return generate_daily_rule_feedback()
    if 'suggest' in pl or 'what should' in pl or 'plan' in pl: return generate_suggestion()
    return """### Trainer Directive
Keep working consistently. Focus on your weakest areas first.
- **Priority**: DSA → Aptitude → Core CS (SQL/OOPs/CN).
- **Practice daily on**: [NeetCode](https://neetcode.io) | [takeUforward](https://takeuforward.org) | [IndiaBix](https://www.indiabix.com)
"""

def generate_news_response():
    articles = fetch_tech_news(limit=6)
    output = "### Live Tech & Placement News\n\n"
    for a in articles:
        output += f"- **[{a['title']}]({a['url']})** — *{a['source']}* `{a.get('tag','Tech')}`\n"
    return output

def generate_daily_rule_feedback():
    today = date.today().isoformat()
    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT key,value FROM settings").fetchall()}
        today_log = db.execute("SELECT * FROM daily_log WHERE log_date=?", (today,)).fetchone()
        pending_count = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Pending'").fetchone()['c']
        solved_count  = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Solved'").fetchone()['c']
        goal = int(settings.get('daily_goal', 10))
        deadline = settings.get('placement_deadline', '2026-10-01')
        days_left = (date.fromisoformat(deadline) - date.today()).days
        plan_rows = db.execute('''
            SELECT p.name, p.category, p.difficulty, dp.status
            FROM daily_plan dp JOIN problems p ON dp.problem_id = p.id
            WHERE dp.plan_date = ? ORDER BY dp.order_index
        ''', (today,)).fetchall()

    solved_today = today_log['problems_solved'] if today_log else 0
    out = f"""### Your Numbers for Today
- **Solved overall:** {solved_count} | **Pending:** {pending_count} | **Days left:** {days_left}
- **Today:** {solved_today}/{goal} done

### Reality Check
"""
    if solved_today == 0:
        out += f"🚨 You have solved **0/{goal}** problems today. Every hour you delay costs you. Start now.\n"
    elif solved_today < goal:
        out += f"⚠️ **{solved_today}/{goal}** done. You need **{goal - solved_today}** more to hit your daily goal.\n"
    else:
        out += f"🏆 Daily goal of {goal} achieved! Strong consistency builds placements.\n"

    out += "\n### Today's Tasks\n"
    if plan_rows:
        for r in plan_rows:
            icon = "✅" if r['status'] == 'Solved' else ("⏭️" if r['status'] == 'Skipped' else "🔲")
            out += f"{icon} **{r['name']}** [{r['category']} – {r['difficulty']}]\n"
    else:
        out += "- No tasks scheduled. Import an Excel sheet to get started.\n"

    out += "\n### Resources\n[NeetCode](https://neetcode.io) | [takeUforward](https://takeuforward.org) | [IndiaBix](https://www.indiabix.com)\n"
    return out

def generate_weekly_rule_feedback():
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    with get_db() as db:
        logs = db.execute("SELECT * FROM daily_log WHERE log_date >= ?", (week_start,)).fetchall()
        settings = {r['key']: r['value'] for r in db.execute("SELECT key,value FROM settings").fetchall()}
        total_p = db.execute("SELECT COUNT(*) as c FROM problems").fetchone()['c']
        solved_p = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Solved'").fetchone()['c']
    total_solved = sum(l['problems_solved'] for l in logs)
    goal = int(settings.get('daily_goal', 10)) * 7
    days_studied = len([l for l in logs if l['problems_solved'] > 0])
    out = f"""### Weekly Performance
- **Solved this week:** {total_solved}/{goal} | **Days studied:** {days_studied}/7 | **Overall:** {solved_p}/{total_p}

### Reality Check\n"""
    if days_studied < 5:
        out += f"⚠️ Only {days_studied}/7 days studied. Aim for 6 minimum.\n"
    else:
        out += f"✅ Good consistency — {days_studied}/7 days studied.\n"
    if total_solved < goal * 0.5:
        out += f"❌ Behind target: {total_solved}/{goal}. Increase volume.\n"
    elif total_solved >= goal:
        out += f"🏆 Target smashed! {total_solved}/{goal}.\n"
    else:
        out += f"👍 Decent: {total_solved}/{goal}. Push harder next week.\n"
    out += "\n### Next Week Directives\n1. Tackle skipped problems first.\n2. [NeetCode Roadmap](https://neetcode.io) for DSA structure.\n3. [IndiaBix](https://www.indiabix.com) for Aptitude + Verbal.\n"
    return out

def generate_suggestion():
    with get_db() as db:
        skipped = db.execute(
            "SELECT topic, COUNT(*) as c FROM problems WHERE status='Skipped' AND topic!='' GROUP BY topic ORDER BY c DESC LIMIT 3"
        ).fetchall()
        settings = {r['key']: r['value'] for r in db.execute("SELECT key,value FROM settings").fetchall()}
        deadline = settings.get('placement_deadline', '2026-10-01')
        days_left = (date.fromisoformat(deadline) - date.today()).days
        total = db.execute("SELECT COUNT(*) as c FROM problems").fetchone()['c']
        solved = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Solved'").fetchone()['c']

    pct = round(solved/total*100, 1) if total else 0
    out = f"""### Priority Study Directives
- **Time left:** {days_left} days | **Solved:** {solved}/{total} ({pct}%)

### Weak Areas\n"""
    if skipped:
        out += "🚨 Topics you keep skipping: " + ", ".join([f"**{r['topic']}** ({r['c']} skipped)" for r in skipped]) + "\nSpend 2 focused days on these.\n"
    else:
        out += "✅ No heavy skipping pattern. Keep tackling harder problems.\n"
    out += """\n### Recommended Resources
- **DSA:** [NeetCode](https://neetcode.io) | [takeUforward](https://takeuforward.org)
- **Aptitude & Verbal:** [IndiaBix](https://www.indiabix.com)
- **SQL:** [SQLZoo](https://sqlzoo.net) | [LeetCode SQL 50](https://leetcode.com/studyplan/sql-50/)
- **System Design:** [ByteByteGo](https://www.youtube.com/@ByteByteGo)
"""
    return out


# ─── DAILY PLAN GENERATION ───────────────────────────────────────────────────
def generate_daily_plan(today_str=None):
    if not today_str:
        today_str = date.today().isoformat()

    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT key,value FROM settings").fetchall()}
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
            cats_in_db = [c['category'] for c in db.execute("SELECT DISTINCT category FROM problems").fetchall()]
            non_dsa = [c for c in cats_in_db if c not in ('DSA', 'HR')]
            dsa_count = max(1, remaining // 2)
            other_count = (remaining - dsa_count) // max(len(non_dsa), 1) if non_dsa else 0
            dist = []
            if 'DSA' in cats_in_db:
                dist.append(('DSA', dsa_count))
            for c in non_dsa:
                dist.append((c, max(1, other_count)))

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
        db.execute("INSERT OR IGNORE INTO daily_log (log_date, problems_target) VALUES (?,?)", (today_str, goal))
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
            FROM daily_plan dp JOIN problems p ON dp.problem_id = p.id
            WHERE dp.plan_date = ? ORDER BY dp.order_index
        ''', (today_str,)).fetchall()
    return [dict(r) for r in plan]

def generate_daily_briefing():
    today = date.today().isoformat()
    with get_db() as db:
        settings = {r['key']: r['value'] for r in db.execute("SELECT key,value FROM settings").fetchall()}
        total = db.execute("SELECT COUNT(*) as c FROM problems").fetchone()['c']
        solved = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Solved'").fetchone()['c']
        pending = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Pending'").fetchone()['c']
        skipped = db.execute("SELECT COUNT(*) as c FROM problems WHERE status='Skipped'").fetchone()['c']
        yesterday_log = db.execute("SELECT * FROM daily_log WHERE log_date=?",
                                   ((date.today() - timedelta(days=1)).isoformat(),)).fetchone()
        weak_topics = db.execute(
            "SELECT topic, COUNT(*) as c FROM problems WHERE status='Skipped' AND topic!='' GROUP BY topic ORDER BY c DESC LIMIT 3"
        ).fetchall()
        deadline = settings.get('placement_deadline', '2026-10-01')
        days_left = (date.fromisoformat(deadline) - date.today()).days
        name = settings.get('name', 'Student')
        goal = settings.get('daily_goal', '10')

    yesterday_solved = yesterday_log['problems_solved'] if yesterday_log else 0
    weak_str = ', '.join([r['topic'] for r in weak_topics]) if weak_topics else 'None identified yet'

    prompt = f"""
Student: {name}
Days left to placement: {days_left}
Daily goal: {goal} problems
Total problems in bank: {total}
Solved: {solved} | Pending: {pending} | Skipped: {skipped}
Yesterday solved: {yesterday_solved}/{goal}
Weak topics (most skipped): {weak_str}

Generate a short (4-5 sentences), direct, honest daily briefing.
Include: progress status, what to focus on today, one free resource.
Be a direct mentor, not a cheerleader. Use the numbers.
"""
    feedback, model = ask_ai(prompt)
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO ai_feedback (feedback_date, feedback_type, content, model_used) VALUES (?,?,?,?)",
            (today, 'daily', feedback, model)
        )
        db.commit()
    return feedback, model
