# ⛏ MineTracker — Placement OS

Your complete free placement preparation command center.
DSA + Aptitude + Verbal + Interview + Courses + Projects + AI Coach

---

## 🚀 Setup (3 Steps)

### Step 1 — Open folder in terminal
```
cd C:\Users\yourname\Downloads\minetracker
```

### Step 2 — Install dependencies (one time only)
```
pip install -r requirements.txt
```

### Step 3 — Run the app
```
python app.py
```

### Step 4 — Open browser
```
http://localhost:5000
```

---

## 🔑 Add Your Free AI Keys (in Settings page)

| Provider | Get Key | Best For |
|----------|---------|----------|
| Groq | console.groq.com | Fastest responses |
| Gemini | aistudio.google.com | Smartest free model |
| OpenRouter | openrouter.ai | Multiple free models |

App works without keys too (rule-based AI fallback).

---

## 📊 Excel Format

Your Excel file can have multiple sheets:

| Sheet Name | Category Auto-Detected |
|------------|----------------------|
| DSA / LeetCode / Coding | DSA |
| Aptitude / Quant / Math | Aptitude |
| Verbal / English / Communication | Verbal |
| Interview / HR / Behavioral | Interview/HR |

Columns needed (names auto-detected):
- Problem/Task/Name → problem name
- Topic/Subject → topic
- Difficulty/Level → Easy/Medium/Hard
- Link/URL/Problem Link → clickable problem link
- Resource/Reference → resource/tutorial link
- Date/Due/Scheduled → when to solve it

---

## 📁 Project Structure

```
minetracker/
├── app.py           ← Flask backend (all API routes)
├── database.py      ← SQLite schema + initialization
├── ai_service.py    ← Groq + Gemini + rule-based AI
├── requirements.txt ← Python dependencies
├── minetracker.db   ← Your data (auto-created)
├── uploads/         ← Temp upload folder
└── templates/
    └── index.html   ← Full frontend (all 10 pages)
```

---

## ✅ All Features

### 🏠 Daily Hub
- AI-generated daily briefing
- Auto-planned 10 problems for today (balanced across categories)
- Weekly + Monthly goal tracking
- Streak counter
- Real-time progress

### 🧩 Problem Tracker
- All problems with filters (category/status/difficulty/platform)
- Click status to cycle: Pending → Solved → Attempted → Skipped
- Clickable problem links + resource links
- Delete by batch/category/date

### 📚 Topic Planner
- Type any topic → see all problems for it
- AI provides free YouTube + article + practice links
- Related algorithm pattern shown

### 🧠 Algorithm Library
- 10 patterns pre-loaded with descriptions
- Mastery levels: Not Started → Learning → Practiced → Mastered
- Free YouTube + practice links per pattern

### 🎓 Courses (8 courses)
- Python, ML/AI, Data Viz, SQL, DevOps, MLOps, HTML/CSS/JS, DSA Patterns
- Individual progress per course
- Streak per course
- Free resource links per topic

### 🏗️ Projects
- Milestone-by-milestone tracking
- GitHub link
- Completion percentage

### 📊 Progress Board
- Placement readiness score (0-100)
- Days left counter
- 30-day activity chart
- Category breakdown
- AI weekly report

### 🤖 AI Coach
- Chat with AI about your preparation
- Daily honest feedback
- Quick action buttons
- New tech radar

### ⚙️ Settings
- Name, goal, deadline, companies
- API keys (stored locally)
- Dark mode
- Import history

---

## 🎓 For Viva

**AI Features:**
1. Priority auto-detection from problem name
2. Column name mapping from Excel (NLP)
3. Daily plan generation (balanced across categories)
4. Honest feedback using Groq/Gemini API
5. Placement readiness score calculation
6. Overload detection

**Tech Stack:**
- Backend: Python + Flask
- Database: SQLite
- AI: Groq API (Llama3) + Gemini API + rule-based fallback
- Frontend: HTML + CSS + Vanilla JS
- Data: pandas + openpyxl

**Why SQLite:** Lightweight, file-based, no setup — perfect for personal use.
**Why Groq:** Free, fastest AI API available — 30 req/min at zero cost.
