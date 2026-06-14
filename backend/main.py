from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import engine, SessionLocal
from models import Base, User, Attempt
import random
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class UserCreate(BaseModel):
    name: str
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class AnswerSubmit(BaseModel):
    user_id: int
    question: str
    answer: str
    mode: str = "dsa"

class ModelAnswerRequest(BaseModel):
    question: str
    mode: str = "dsa"

class CompareRequest(BaseModel):
    question: str
    user_answer: str
    mode: str = "dsa"

class ResumeRequest(BaseModel):
    resume_text: str

class SessionSummaryRequest(BaseModel):
    user_id: int
    attempts: list

@app.get("/")
def home():
    return {"message": "PrepSense backend running"}

# ── AUTH ──────────────────────────────────────────────────
@app.post("/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = User(name=user.name, email=user.email, password=user.password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"user_id": new_user.id, "message": "Account created"}

@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = User(name=user.name, email=user.email, password=user.password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"user_id": new_user.id, "message": "Account created"}

@app.post("/login")
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or user.password != data.password:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"user_id": user.id, "name": user.name}

# ── QUESTIONS ─────────────────────────────────────────────
QUESTIONS = {
    "dsa": [
        "Explain binary search and its time complexity.",
        "What is dynamic programming? Give an example.",
        "How does quicksort work? What is its time complexity?",
        "What is a hash map and how does collision resolution work?",
        "Explain the difference between BFS and DFS.",
        "What is a linked list? How does it differ from an array?",
        "How do you detect a cycle in a linked list?",
        "What is recursion? Explain with an example.",
        "What is a stack and queue? Give real world examples.",
        "Explain merge sort and why it is preferred over quicksort sometimes."
    ],
    "hr": [
        "Tell me about yourself.",
        "What is your greatest strength? Give a specific example.",
        "What is your greatest weakness and what are you doing about it?",
        "Where do you see yourself in 5 years?",
        "Why should we hire you over other candidates?",
        "Describe a time you faced a conflict in a team.",
        "Tell me about a project you are most proud of.",
        "How do you handle pressure and tight deadlines?",
        "What motivates you to do your best work?",
        "Describe a situation where you showed leadership."
    ],
    "os": [
        "What is the difference between a process and a thread?",
        "Explain deadlock and how it can be prevented.",
        "What is virtual memory and why is it useful?",
        "Explain CPU scheduling algorithms.",
        "What is a semaphore? How does it differ from a mutex?",
        "What is paging in operating systems?",
        "Explain the concept of thrashing.",
        "What is inter-process communication?",
        "What is a context switch?",
        "Explain preemptive vs non-preemptive scheduling."
    ],
    "cn": [
        "What is the difference between TCP and UDP?",
        "Explain the OSI model and its 7 layers.",
        "What happens when you type a URL in a browser?",
        "What is the difference between HTTP and HTTPS?",
        "Explain the TCP three-way handshake.",
        "What is DNS and how does it work?",
        "What is subnetting?",
        "Explain the difference between a hub, switch, and router.",
        "What is ARP protocol?",
        "What is the difference between IPv4 and IPv6?"
    ],
    "system_design": [
        "Design a URL shortener like bit.ly.",
        "How would you design a basic chat application?",
        "Design a notification system for millions of users.",
        "How would you design a leaderboard for an online game?",
        "Design a parking lot management system.",
        "Design a rate limiter for an API.",
        "How would you design a file storage system like Google Drive?",
        "Design a search autocomplete feature.",
        "How would you design a basic e-commerce product catalog?",
        "Design a system to handle OTP delivery at scale."
    ]
}

@app.get("/question/{topic}")
def get_question(topic: str):
    topic_lower = topic.lower()
    q_list = QUESTIONS.get(topic_lower, QUESTIONS["dsa"])
    return {"question": random.choice(q_list), "mode": topic_lower}

# ── SUBMIT ────────────────────────────────────────────────
@app.post("/submit")
def submit(data: AnswerSubmit, db: Session = Depends(get_db)):
    answer = data.answer.strip()
    if not answer:
        raise HTTPException(status_code=400, detail="No answer provided")
    scores, rule_feedback = score_answer(data.question, answer, data.mode)
    feedback_obj = generate_feedback(scores, rule_feedback, data.mode)
    model_ans = get_model_answer(data.question)
    attempt = Attempt(
        user_id=data.user_id,
        mode=data.mode,
        question=data.question,
        answer=answer,
        score=scores["total"]
    )
    db.add(attempt)
    db.commit()
    return {
        "score": scores["total"],
        "scores": scores,
        "correct_pct": feedback_obj["correct_pct"],
        "wrong_pct": feedback_obj["wrong_pct"],
        "improvement_required": feedback_obj["improvement_required"],
        "strength": feedback_obj["strength"],
        "weakness": feedback_obj["weakness"],
        "suggestion": feedback_obj["suggestion"],
        "verdict": feedback_obj["verdict"],
        "overall_msg": feedback_obj["overall_msg"],
        "round_focus": feedback_obj["round_focus"],
        "mode_tips": feedback_obj["mode_tips"],
        "rule_feedback": rule_feedback,
        "model_answer": model_ans
    }

# ── STATS ─────────────────────────────────────────────────
@app.get("/stats/{user_id}")
def stats(user_id: int, db: Session = Depends(get_db)):
    attempts = db.query(Attempt).filter(Attempt.user_id == user_id).order_by(Attempt.id).all()
    if not attempts:
        return {"total": 0, "avg": 0, "best": 0, "last": 0, "modes": {}, "recent": [], "scores_list": [], "improvement": 0, "weakest": "dsa"}
    scores = [a.score for a in attempts]
    mode_data = {}
    for a in attempts:
        mode_data.setdefault(a.mode, []).append(a.score)
    mode_avg = {k: round(sum(v) / len(v), 1) for k, v in mode_data.items()}
    weakest = min(mode_avg, key=mode_avg.get)
    improvement = 0
    if len(scores) >= 6:
        first3 = sum(scores[:3]) / 3
        last3 = sum(scores[-3:]) / 3
        improvement = round(((last3 - first3) / max(first3, 1)) * 100, 1)
    recent = [{"mode": a.mode, "question": a.question, "score": a.score} for a in reversed(attempts[-5:])]
    return {
        "total": len(scores),
        "avg": round(sum(scores) / len(scores), 1),
        "best": max(scores),
        "last": scores[-1],
        "modes": mode_avg,
        "recent": recent,
        "scores_list": scores[-14:],
        "improvement": improvement,
        "weakest": weakest
    }

# ── MODEL ANSWER ──────────────────────────────────────────
@app.post("/model-answer")
def model_answer_route(data: ModelAnswerRequest):
    answer = get_model_answer(data.question)
    keywords = get_keywords(data.question, data.mode)
    return {"model_answer": answer, "key_points": keywords[:6]}

# ── COMPARE ───────────────────────────────────────────────
@app.post("/compare")
def compare(data: CompareRequest):
    user = data.user_answer.strip()
    user_lower = user.lower()
    model = get_model_answer(data.question)
    model_lower = model.lower()
    keywords = get_keywords(data.question, data.mode)
    matched_kw = [k for k in keywords if k.lower() in user_lower]
    missing_kw = [k for k in keywords if k.lower() not in user_lower]
    kw_match_pct = round((len(matched_kw) / max(len(keywords), 1)) * 100)
    user_words = set(user_lower.split())
    model_words_set = set(model_lower.split())
    stop = {'a','an','the','is','are','was','were','be','been','being','have','has','had','do','does','did','will','would','could','should','may','might','shall','can','to','of','in','on','at','by','for','with','about','as','from','or','and','but','not','it','its','this','that','they','them','their','we','our','you','your','i','my','he','his','she','her','so','if','then','than','when','where','which','who'}
    user_content = user_words - stop
    model_content = model_words_set - stop
    overlap = user_content & model_content
    word_overlap_pct = round((len(overlap) / max(len(model_content), 1)) * 100)
    match_pct = round((kw_match_pct * 0.6) + (min(word_overlap_pct, 100) * 0.4))
    missing_pct = 100 - match_pct
    user_word_count = len(user.split())
    model_word_count = len(model.split())
    length_pct = round((user_word_count / max(model_word_count, 1)) * 100)
    what_correct = "Your answer correctly covers: " + ", ".join(matched_kw[:4]) if matched_kw else "No key concepts were matched."
    what_missing = "Missing key concepts: " + ", ".join(missing_kw[:4]) if missing_kw else "No major concepts missing."
    additions = []
    if missing_kw: additions.append("Explain: " + ", ".join(missing_kw[:3]))
    if user_word_count < 40: additions.append("Your answer is too short — add more detail")
    if 'example' not in user_lower and 'e.g' not in user_lower: additions.append("Add a concrete example with real values")
    if not any(m in user_lower for m in ['first','second','finally','also','additionally']): additions.append("Structure your answer — use First, Then, Finally format")
    what_to_add = ". ".join(additions) if additions else "Your answer is complete — just polish the language."
    if match_pct >= 80: verdict = "Excellent"
    elif match_pct >= 60: verdict = "Good"
    elif match_pct >= 40: verdict = "Average"
    else: verdict = "Weak"
    return {
        "match_pct": match_pct,
        "missing_pct": missing_pct,
        "extra_pct": min(100, length_pct),
        "what_correct": what_correct,
        "what_missing": what_missing,
        "what_to_add": what_to_add,
        "verdict": verdict,
        "ideal_answer": model
    }

# ── RESUME ANALYSER ───────────────────────────────────────
@app.post("/analyse-resume")
def analyse_resume(data: ResumeRequest):
    text = data.resume_text.lower()
    original = data.resume_text
    score = 0
    missing = []
    good = []
    improvements = []
    sections = {}
    has_email = '@' in text and '.com' in text
    has_phone = '+91' in text or len(re.findall(r'\d{10}', text)) > 0
    has_linkedin = 'linkedin' in text
    has_github = 'github' in text
    contact_score = 0
    if has_email: contact_score += 25
    if has_phone: contact_score += 25
    if has_linkedin: contact_score += 25; good.append("LinkedIn profile link found")
    if has_github: contact_score += 25; good.append("GitHub profile link found")
    sections['contact'] = contact_score
    score += contact_score * 0.15
    if not has_email: missing.append("Email address not found")
    if not has_phone: missing.append("Phone number not found")
    if not has_linkedin: missing.append("LinkedIn profile URL missing")
    if not has_github: missing.append("GitHub profile URL missing")
    edu_keywords = ['b.tech','btech','b.e','bachelor','engineering','university','college','cgpa','gpa','percentage','10th','12th']
    has_edu = any(k in text for k in edu_keywords)
    has_cgpa = 'cgpa' in text or 'gpa' in text or 'percentage' in text
    edu_score = 0
    if has_edu: edu_score += 60; good.append("Education section present")
    if has_cgpa: edu_score += 40; good.append("CGPA/GPA mentioned")
    sections['education'] = edu_score
    score += edu_score * 0.2
    if not has_edu: missing.append("Education section not found")
    if not has_cgpa: improvements.append("Add your CGPA or percentage")
    tech_skills = ['python','java','c++','javascript','sql','html','css','react','node','django','flask','fastapi','machine learning','ml','ai','data structures','algorithms','git','linux','docker','aws','mongodb','mysql','postgresql','tensorflow','numpy','pandas']
    found_skills = [s for s in tech_skills if s in text]
    skill_score = min(100, len(found_skills) * 10)
    sections['skills'] = skill_score
    score += skill_score * 0.2
    if len(found_skills) >= 5: good.append(f"Good skills section — {len(found_skills)} technical skills found")
    elif len(found_skills) > 0: improvements.append(f"Only {len(found_skills)} technical skills found — add more")
    else: missing.append("Skills section not found")
    project_keywords = ['project','built','developed','implemented','created','designed','deployed']
    has_projects = any(k in text for k in project_keywords)
    action_verbs = ['built','developed','implemented','created','designed','deployed','optimised','improved','reduced','increased','automated']
    found_verbs = [v for v in action_verbs if v in text]
    proj_score = 0
    if has_projects: proj_score += 60; good.append("Projects section present")
    if len(found_verbs) >= 3: proj_score += 40; good.append(f"Good use of action verbs")
    sections['projects'] = proj_score
    score += proj_score * 0.25
    if not has_projects: missing.append("Projects section not found")
    if len(found_verbs) < 3: improvements.append("Use strong action verbs: Built, Developed, Implemented")
    numbers = re.findall(r'\d+[%xk]?', original)
    if len(numbers) >= 3: good.append("Resume contains quantified achievements"); score += 5
    else: improvements.append("Add numbers — e.g. 'Improved load time by 40%'")
    exp_keywords = ['internship','intern','experience','worked at','trainee']
    has_exp = any(k in text for k in exp_keywords)
    exp_score = 100 if has_exp else 0
    sections['experience'] = exp_score
    score += exp_score * 0.1
    if has_exp: good.append("Internship or work experience found")
    else: improvements.append("Add internship experience if any")
    word_count = len(original.split())
    if 200 <= word_count <= 600: good.append(f"Good resume length — {word_count} words"); score += 5
    elif word_count < 200: missing.append(f"Resume too short ({word_count} words)")
    else: improvements.append(f"Resume too long ({word_count} words) — keep to 1 page")
    final_score = min(100, round(score))
    if final_score >= 80: summary = "Your resume is strong. Make minor improvements to maximise chances."
    elif final_score >= 60: summary = "Your resume covers basics. Adding missing elements will improve shortlisting rate."
    elif final_score >= 40: summary = "Your resume needs work. Focus on Projects, GitHub, and LinkedIn."
    else: summary = "Your resume is missing critical sections. Build from scratch using checklist below."
    return {
        "ats_score": final_score, "summary": summary, "sections": sections,
        "missing": missing, "good": good, "improvements": improvements,
        "fresher_tips": [
            "Keep your resume to exactly 1 page",
            "Put Projects section right after Education",
            "Each project should mention: what you built, technologies used, and result",
            "Add your GitHub link prominently",
            "Include CGPA if above 7.0",
            "Add a 2-line objective at the top",
            "List skills in order of proficiency",
            "Use a clean single-column format",
            "Save as PDF with your name in filename",
            "Add LinkedIn URL"
        ]
    }

# ── WEEKLY PROGRESS ───────────────────────────────────────
@app.get("/weekly-progress/{user_id}")
def weekly_progress(user_id: int, db: Session = Depends(get_db)):
    from datetime import datetime, timedelta
    attempts = db.query(Attempt).filter(Attempt.user_id == user_id).order_by(Attempt.id).all()
    if not attempts:
        return {"weeks": [], "daily": [], "best_day": None, "best_week": None, "total_days_active": 0, "current_streak": 0}
    today = datetime.now().date()
    daily = []
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        day_attempts = [a for a in attempts if hasattr(a.created_at, 'date') and a.created_at.date() == day]
        daily.append({"date": day.strftime("%d %b"), "count": len(day_attempts), "avg_score": round(sum(a.score for a in day_attempts) / len(day_attempts), 1) if day_attempts else 0})
    weeks = []
    for w in range(7, -1, -1):
        week_start = today - timedelta(days=today.weekday()) - timedelta(weeks=w)
        week_end = week_start + timedelta(days=6)
        week_attempts = [a for a in attempts if hasattr(a.created_at, 'date') and week_start <= a.created_at.date() <= week_end]
        mode_counts = {}
        for a in week_attempts:
            mode_counts[a.mode] = mode_counts.get(a.mode, 0) + 1
        weeks.append({"week": week_start.strftime("%d %b"), "count": len(week_attempts), "avg_score": round(sum(a.score for a in week_attempts) / len(week_attempts), 1) if week_attempts else 0, "modes": mode_counts})
    best_day = max(daily, key=lambda x: x['count']) if daily else None
    best_week = max(weeks, key=lambda x: x['avg_score']) if weeks else None
    return {"weeks": weeks, "daily": daily, "best_day": best_day, "best_week": best_week, "total_days_active": len([d for d in daily if d['count'] > 0]), "current_streak": get_current_streak(attempts, today)}

def get_current_streak(attempts, today):
    from datetime import timedelta
    if not attempts: return 0
    active_days = set()
    for a in attempts:
        if hasattr(a.created_at, 'date'):
            active_days.add(a.created_at.date())
    streak = 0
    check_day = today
    while check_day in active_days:
        streak += 1
        check_day = check_day - timedelta(days=1)
    return streak

# ── SESSION SUMMARY ───────────────────────────────────────
@app.post("/session-summary")
def session_summary(data: SessionSummaryRequest):
    attempts = data.attempts
    if not attempts:
        return {"error": "No attempts"}
    scores = [a['score'] for a in attempts]
    avg = round(sum(scores) / len(scores), 1)
    best = max(scores)
    worst = min(scores)
    mode_scores = {}
    for a in attempts:
        mode_scores.setdefault(a['mode'], []).append(a['score'])
    mode_avg = {k: round(sum(v)/len(v), 1) for k, v in mode_scores.items()}
    strongest = max(mode_avg, key=mode_avg.get) if mode_avg else 'dsa'
    weakest = min(mode_avg, key=mode_avg.get) if mode_avg else 'dsa'
    if avg >= 8: overall = "Excellent"; overall_msg = "Outstanding session!"; color = "green"
    elif avg >= 6: overall = "Good"; overall_msg = "Good session. A little more practice and you will be ready."; color = "orange"
    elif avg >= 4: overall = "Average"; overall_msg = "Average session. Focus on the weak areas."; color = "orange"
    else: overall = "Needs Work"; overall_msg = "This topic needs more attention."; color = "red"
    study_plan = {
        "dsa": "Revise time complexity, practice 3 sorting algorithms, solve 2 linked list problems.",
        "hr": "Practice STAR format for 3 questions, record yourself answering.",
        "os": "Revise process vs thread, deadlock prevention, CPU scheduling.",
        "cn": "Revise OSI model, TCP vs UDP, DNS flow.",
        "system_design": "Practice URL shortener and chat app design."
    }
    next_focus = study_plan.get(weakest, study_plan['dsa'])
    score_distribution = {
        "excellent": len([s for s in scores if s >= 8]),
        "good": len([s for s in scores if 6 <= s < 8]),
        "average": len([s for s in scores if 4 <= s < 6]),
        "weak": len([s for s in scores if s < 4])
    }
    return {
        "total_questions": len(attempts), "avg_score": avg, "best_score": best, "worst_score": worst,
        "overall": overall, "overall_msg": overall_msg, "color": color,
        "strongest": strongest, "weakest": weakest, "mode_avg": mode_avg,
        "next_focus": next_focus, "score_distribution": score_distribution, "attempts": attempts
    }

# ── SCORING ENGINE ────────────────────────────────────────
def get_keywords(question, mode):
    q = question.lower()
    if any(w in q for w in ['array','linked list','tree','graph','stack','queue','hash','sort','search','recursion','dynamic programming']):
        return ['time complexity','space complexity','example','steps']
    if any(w in q for w in ['process','thread','deadlock','semaphore','mutex','paging','virtual','scheduling']):
        return ['definition','example','cause','prevention']
    if any(w in q for w in ['tcp','udp','http','dns','osi','handshake']):
        return ['protocol','connection','example','difference']
    if mode == 'dsa':
        if 'binary search' in q: return ['time complexity','O(log n)','sorted','mid']
        if 'hash' in q: return ['hash function','collision','O(1)','key']
        if 'linked list' in q: return ['node','pointer','head','next']
        if 'quicksort' in q: return ['pivot','partition','O(n log n)','worst case']
        return ['time complexity','space complexity','algorithm','example']
    elif mode == 'hr':
        if 'about yourself' in q: return ['education','skills','project','goal']
        if 'strength' in q: return ['example','result','helped','achieved']
        if 'weakness' in q: return ['working on','improving','learning']
        return ['example','situation','action','result']
    elif mode == 'system_design':
        return ['scale','database','api','availability','cache']
    return ['definition','example','use case','concept']

def score_answer(question, answer, mode):
    scores = {}
    feedback = []
    words = answer.strip().split()
    word_count = len(words)
    lower = answer.lower()
    if word_count < 20: scores['clarity'] = 3; feedback.append("Answer too short — aim for at least 4-5 sentences.")
    elif word_count > 300: scores['clarity'] = 6; feedback.append("Answer too long — keep it concise.")
    else: scores['clarity'] = 8
    example_phrases = ['for example','for instance','such as','like when','e.g','consider','suppose']
    used = any(p in lower for p in example_phrases)
    scores['used_example'] = 10 if used else 0
    if not used: feedback.append("Always use a concrete example to support your answer.")
    keywords = get_keywords(question, mode)
    matched = [k for k in keywords if k.lower() in lower]
    ratio = len(matched) / max(len(keywords), 1)
    scores['technical_accuracy'] = min(10, int(ratio * 10))
    missing = [k for k in keywords if k.lower() not in lower]
    if missing: feedback.append(f"Missing key concepts: {', '.join(missing[:3])}.")
    markers = ['first','second','third','finally','to begin','in conclusion','additionally','furthermore','also','next']
    count = sum(1 for m in markers if m in lower)
    scores['structure'] = min(10, count * 3)
    if count == 0: feedback.append("Structure your answer — use 'First... Then... Finally' format.")
    scores['completeness'] = 3 if word_count < 30 else 6 if word_count < 60 else 9
    scores['total'] = round((scores['clarity'] + scores['used_example'] + scores['technical_accuracy'] + scores['structure'] + scores['completeness']) / 5)
    return scores, feedback

def generate_feedback(scores, rule_feedback, mode):
    total = scores['total']
    correct_pct = round(total * 10)
    wrong_pct = 100 - correct_pct
    if total >= 8: verdict = "Strong"; overall_msg = "Excellent answer — well structured with good technical depth."
    elif total >= 6: verdict = "Good"; overall_msg = "Good answer. You covered the main points."
    elif total >= 4: verdict = "Average"; overall_msg = "Average answer. Significant improvement needed."
    else: verdict = "Weak"; overall_msg = "Answer needs major improvement. Review the model answer."
    weak_dims = []
    if scores.get('technical_accuracy', 0) < 5: weak_dims.append("technical accuracy")
    if scores.get('used_example', 0) == 0: weak_dims.append("use of examples")
    if scores.get('structure', 0) < 5: weak_dims.append("answer structure")
    if scores.get('clarity', 0) < 6: weak_dims.append("clarity and length")
    round_tips = {
        "dsa": ["Always mention time complexity (Big O) for every algorithm.", "Always mention space complexity.", "Give a concrete example with actual values."],
        "hr": ["Use STAR format — Situation, Task, Action, Result.", "Always give a specific real example.", "Quantify your impact where possible."],
        "os": ["Start with a clear definition.", "Give a real world analogy.", "Mention prevention or solution strategies."],
        "cn": ["Name the specific protocol or OSI layer.", "Give a practical real world example.", "Use correct technical terminology."],
        "system_design": ["Start by clarifying requirements.", "Always explain how the system scales.", "Discuss database choice and justify why."]
    }
    tips = round_tips.get(mode, round_tips["dsa"])
    need = max(0, 7 - total)
    round_focus = (f"To clear {mode.upper()} rounds you need 7+/10. You scored {total}/10 — need {need} more point{'s' if need != 1 else ''} to reach the bar." if need > 0 else f"Great — your {mode.upper()} score of {total}/10 clears the interview bar!")
    return {
        "verdict": verdict, "overall_msg": overall_msg, "correct_pct": correct_pct, "wrong_pct": wrong_pct,
        "improvement_required": wrong_pct,
        "strength": f"{correct_pct}% of key concepts covered correctly.",
        "weakness": (f"{wrong_pct}% needs improvement. Weak areas: {', '.join(weak_dims)}." if weak_dims else f"{wrong_pct}% can still be improved."),
        "suggestion": f"For {mode.upper()} round: {tips[0]}", "mode_tips": tips[:3], "round_focus": round_focus
    }

def get_model_answer(question):
    answers = {
        "Explain binary search and its time complexity.": "Binary search works on a sorted array by repeatedly halving the search space. Compare the target with the middle element. If equal, return it. If target is smaller, search the left half. If larger, search the right half. Time complexity is O(log n). Space complexity is O(1) for iterative. For example, finding 7 in [1,3,5,7,9] — mid is 5, target is greater, search [7,9], found in 2 steps.",
        "What is dynamic programming? Give an example.": "Dynamic programming solves complex problems by breaking them into overlapping subproblems and storing results to avoid recomputation. Two approaches — memoization (top-down) and tabulation (bottom-up). For example Fibonacci: store fib(1)=1, fib(2)=1, fib(3)=2, fib(4)=3, fib(5)=5. Time complexity drops from O(2^n) to O(n).",
        "How does quicksort work? What is its time complexity?": "Quicksort selects a pivot and partitions the array — elements smaller on left, greater on right. Recursively sorts both halves. Average time complexity O(n log n). Worst case O(n²) when pivot is always the smallest or largest. Use random pivot to avoid worst case.",
        "What is a hash map and how does collision resolution work?": "A hash map stores key-value pairs using a hash function to compute an index. Average O(1) for get, put, delete. Collisions: chaining — each index holds a linked list, or open addressing — probe next available slot.",
        "Explain the difference between BFS and DFS.": "BFS explores level by level using a queue. Finds shortest path in unweighted graphs. O(V+E). DFS explores deep using a stack or recursion. Better for cycle detection and topological sorting. BFS for shortest path, DFS for connected components.",
        "What is a linked list? How does it differ from an array?": "A linked list has nodes with data and a pointer to next node. Arrays have O(1) random access, linked lists O(n). Insertion at beginning is O(1) for linked lists vs O(n) for arrays. Arrays have better cache performance.",
        "How do you detect a cycle in a linked list?": "Use Floyd's cycle detection — slow moves one step, fast moves two. If they meet, there is a cycle. If fast reaches null, no cycle. Time O(n), space O(1).",
        "What is recursion? Explain with an example.": "Recursion is when a function calls itself. Needs a base case and recursive case. Example: factorial(n) = n * factorial(n-1), base case factorial(0)=1. So factorial(4) = 4*3*2*1 = 24.",
        "What is a stack and queue? Give real world examples.": "Stack is LIFO — push and pop are O(1). Examples: browser back button, undo in editors. Queue is FIFO — enqueue and dequeue are O(1). Examples: printer queue, BFS traversal.",
        "Explain merge sort and why it is preferred over quicksort sometimes.": "Merge sort divides array in half, sorts each, merges. O(n log n) always. Space O(n). Preferred when stable sort needed or for linked lists. Quicksort is faster for in-memory arrays but has O(n²) worst case.",
        "Tell me about yourself.": "I am a final year Computer Science student with strong foundations in data structures and full stack development. I built PrepSense, an AI-powered mock interview platform with real-time feedback, camera posture analysis, and answer comparison. Proficient in Python, SQL, JavaScript, FastAPI. I am looking for a software engineering role where I can build products that solve real problems.",
        "What is the difference between a process and a thread?": "A process is an independent program with its own memory. A thread is the smallest unit within a process sharing the same memory. Processes are isolated — a crash in one does not affect others. Threads share memory making communication faster but requiring synchronisation.",
        "Explain deadlock and how it can be prevented.": "Deadlock is when processes wait for each other's resources forever. Four conditions: mutual exclusion, hold and wait, no preemption, circular wait. Prevention: resource ordering, request all resources at once, or allow preemption.",
        "What is virtual memory and why is it useful?": "Virtual memory gives each process the illusion of a large address space. OS maps virtual to physical addresses using page tables. Allows running programs larger than RAM. Page fault loads from disk when needed.",
        "What is the difference between TCP and UDP?": "TCP is connection-oriented, guarantees reliable ordered delivery using handshake and acknowledgements. UDP is connectionless with no delivery guarantee but lower latency. TCP for HTTP, FTP. UDP for DNS, video streaming, gaming.",
        "Explain the OSI model and its 7 layers.": "Physical — raw bits. Data Link — MAC addresses, Ethernet. Network — IP addresses, routing. Transport — TCP/UDP, ports. Session — connection management. Presentation — encryption, compression. Application — HTTP, FTP, DNS.",
        "What happens when you type a URL in a browser?": "DNS lookup to get IP address. TCP three-way handshake. TLS handshake if HTTPS. HTTP GET request sent. Server returns HTML. Browser parses HTML, fetches CSS and JS. Renders page.",
        "What is the difference between HTTP and HTTPS?": "HTTP sends data in plaintext. HTTPS encrypts using TLS. Prevents eavesdropping and man-in-the-middle attacks. Port 80 vs 443.",
        "Explain the TCP three-way handshake.": "SYN: client sends SYN with sequence number. SYN-ACK: server acknowledges and sends its sequence number. ACK: client acknowledges. Connection established.",
        "What is DNS and how does it work?": "DNS translates domain names to IP addresses. Query goes to recursive resolver, then root server, TLD server, authoritative nameserver. Result cached with TTL.",
        "Design a URL shortener like bit.ly.": "POST /shorten generates 6-character base62 code from auto-incremented ID. Store short_code and long_url in database. GET /{code} looks up Redis cache then database, returns 301 redirect. Scale with Redis cache and CDN.",
        "How would you design a basic chat application?": "Use WebSockets for real-time connections. Store messages in Cassandra. If user offline, store and deliver on reconnect. Use Kafka for decoupling. Multiple chat servers with presence service.",
        "Design a rate limiter for an API.": "Use token bucket or sliding window algorithm. Store counters in Redis with TTL. Check counter on each request, reject if limit exceeded. Return 429 status. Scale with distributed Redis cluster.",
    }
    q = question.strip()
    if q in answers:
        return answers[q]
    return f"For the question '{question}': 1) Define the concept clearly. 2) Explain how it works step by step. 3) Give a concrete example. 4) Mention time/space complexity or trade-offs. 5) Compare with a related concept."