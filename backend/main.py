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

@app.post("/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):
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

@app.post("/model-answer")
def model_answer_route(data: ModelAnswerRequest):
    answer = get_model_answer(data.question)
    keywords = get_keywords(data.question, data.mode)
    return {"model_answer": answer, "key_points": keywords[:6]}

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
    improvement_needed = 100 - match_pct
    if match_pct >= 80: verdict = "Excellent"; verdict_msg = "Covers most key points."; verdict_color = "green"
    elif match_pct >= 60: verdict = "Good"; verdict_msg = "A few concepts missing."; verdict_color = "orange"
    elif match_pct >= 40: verdict = "Average"; verdict_msg = "Significant gaps."; verdict_color = "orange"
    else: verdict = "Weak"; verdict_msg = "Major concepts missing."; verdict_color = "red"
    user_sentences = [s.strip() for s in user.replace('?','.').replace('!','.').split('.') if len(s.strip()) > 10]
    model_sentences = [s.strip() for s in model.replace('?','.').replace('!','.').split('.') if len(s.strip()) > 10]
    sentence_analysis = []
    for us in user_sentences[:5]:
        us_words = set(us.lower().split()) - stop
        best_match = 0
        for ms in model_sentences:
            ms_words = set(ms.lower().split()) - stop
            if not ms_words: continue
            overlap_s = us_words & ms_words
            score_s = len(overlap_s) / max(len(ms_words), 1)
            best_match = max(best_match, score_s)
        pct = round(best_match * 100)
        sentence_analysis.append({"sentence": us[:80] + ("..." if len(us) > 80 else ""), "match": pct, "status": "good" if pct >= 60 else "needs_work" if pct >= 30 else "missing"})
    return {
        "match_pct": match_pct, "missing_pct": missing_pct, "improvement_needed": improvement_needed,
        "length_pct": min(100, length_pct), "kw_match_pct": kw_match_pct, "word_overlap_pct": min(100, word_overlap_pct),
        "what_correct": what_correct, "what_missing": what_missing, "what_to_add": what_to_add,
        "verdict": verdict, "verdict_msg": verdict_msg, "verdict_color": verdict_color,
        "sentence_analysis": sentence_analysis, "ideal_answer": model,
        "user_word_count": user_word_count, "model_word_count": model_word_count
    }

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
    if not has_linkedin: missing.append("LinkedIn profile URL missing — very important for freshers")
    if not has_github: missing.append("GitHub profile URL missing — essential for CS freshers")
    edu_keywords = ['b.tech','btech','b.e','bachelor','engineering','university','college','cgpa','gpa','percentage','10th','12th','ssc','hsc']
    has_edu = any(k in text for k in edu_keywords)
    has_cgpa = 'cgpa' in text or 'gpa' in text or 'percentage' in text
    edu_score = 0
    if has_edu: edu_score += 60; good.append("Education section present")
    if has_cgpa: edu_score += 40; good.append("CGPA/GPA mentioned")
    sections['education'] = edu_score
    score += edu_score * 0.2
    if not has_edu: missing.append("Education section not found")
    if not has_cgpa: improvements.append("Add your CGPA or percentage — recruiters look for this in fresher resumes")
    tech_skills = ['python','java','c++','javascript','sql','html','css','react','node','django','flask','fastapi','machine learning','ml','ai','data structures','algorithms','git','linux','docker','aws','mongodb','mysql','postgresql','tensorflow','numpy','pandas']
    found_skills = [s for s in tech_skills if s in text]
    skill_score = min(100, len(found_skills) * 10)
    sections['skills'] = skill_score
    score += skill_score * 0.2
    if len(found_skills) >= 5: good.append(f"Good skills section — {len(found_skills)} technical skills found")
    elif len(found_skills) > 0: improvements.append(f"Only {len(found_skills)} technical skills found — add more")
    else: missing.append("Skills section not found or no recognisable technical skills")
    project_keywords = ['project','built','developed','implemented','created','designed','deployed','app','website','system','platform']
    has_projects = any(k in text for k in project_keywords)
    action_verbs = ['built','developed','implemented','created','designed','deployed','optimised','improved','reduced','increased','automated','integrated']
    found_verbs = [v for v in action_verbs if v in text]
    proj_score = 0
    if has_projects: proj_score += 60; good.append("Projects section present")
    if len(found_verbs) >= 3: proj_score += 40; good.append(f"Good use of action verbs: {', '.join(found_verbs[:3])}")
    sections['projects'] = proj_score
    score += proj_score * 0.25
    if not has_projects: missing.append("Projects section not found — most important section for freshers")
    if len(found_verbs) < 3: improvements.append("Use strong action verbs: Built, Developed, Implemented, Deployed")
    numbers = re.findall(r'\d+[%xk]?', original)
    if len(numbers) >= 3: good.append("Resume contains quantified achievements"); score += 5
    else: improvements.append("Add numbers — e.g. 'Improved load time by 40%', 'Built app with 500+ users'")
    exp_keywords = ['internship','intern','experience','worked at','work experience','trainee']
    has_exp = any(k in text for k in exp_keywords)
    exp_score = 100 if has_exp else 0
    sections['experience'] = exp_score
    score += exp_score * 0.1
    if has_exp: good.append("Internship or work experience found")
    else: improvements.append("Add internship experience if any — even 1 month matters for freshers")
    cert_keywords = ['certification','certified','certificate','coursera','udemy','nptel','hackerrank','leetcode','codechef']
    if any(k in text for k in cert_keywords): good.append("Certifications or competitive programming found"); score += 5
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
            "Keep your resume to exactly 1 page — recruiters spend 6 seconds on a fresher resume",
            "Put Projects section right after Education — it is your strongest section as a fresher",
            "Each project should mention: what you built, technologies used, and impact or result",
            "Add your GitHub link prominently — recruiters will check your code",
            "Include CGPA if above 7.0 — you can hide it if below 6.5",
            "Add a 2-line objective at the top tailored to the role you want",
            "List skills in order of proficiency — strongest skills first",
            "Use a clean single-column format — avoid tables, graphics, and colours",
            "Save as PDF with your name in the filename — e.g. Simran_Jha_Resume.pdf",
            "Add LinkedIn URL — even a basic profile shows professionalism"
        ]
    }

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
    if avg >= 8: overall = "Excellent"; overall_msg = "Outstanding session! You are interview-ready for this topic."; color = "green"
    elif avg >= 6: overall = "Good"; overall_msg = "Good session. A little more practice and you will be ready."; color = "orange"
    elif avg >= 4: overall = "Average"; overall_msg = "Average session. Focus on the weak areas before your interview."; color = "orange"
    else: overall = "Needs Work"; overall_msg = "This topic needs more attention. Review concepts and retry."; color = "red"
    study_plan = {
        "dsa": "Revise time complexity, practice 3 sorting algorithms with examples, solve 2 linked list problems.",
        "hr": "Practice STAR format for 3 questions, record yourself answering, review your answers.",
        "os": "Revise process vs thread, deadlock prevention, CPU scheduling algorithms.",
        "cn": "Revise OSI model layers, TCP vs UDP, practice explaining DNS flow step by step.",
        "system_design": "Practice designing URL shortener and chat app. Focus on scale and database choice."
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

# ── Scoring engine ────────────────────────────────────────
def get_keywords(question, mode):
    q = question.lower()
    if any(w in q for w in ['deadlock','semaphore','mutex','paging','virtual memory','context switch','scheduling','thrashing']):
        return ['definition','example','cause','prevention']
    if any(w in q for w in ['tcp','udp','http','dns','osi','handshake','socket','routing','subnet']):
        return ['protocol','connection','example','difference']
    if any(w in q for w in ['process','thread']):
        return ['memory','shared','example','difference']
    if any(w in q for w in ['array','linked list','tree','graph','stack','queue','hash','sort','search','recursion','dynamic programming']):
        return ['time complexity','space complexity','example','steps']
    if any(w in q for w in ['oop','class','object','inheritance','polymorphism','encapsulation']):
        return ['definition','example','real world','advantage']
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
    example_phrases = ['for example','for instance','such as','like when','in my project','consider','suppose','imagine','e.g']
    used = any(p in lower for p in example_phrases)
    scores['used_example'] = 10 if used else 0
    if not used: feedback.append("Always use a concrete example to support your answer.")
    keywords = get_keywords(question, mode)
    matched = [k for k in keywords if k.lower() in lower]
    ratio = len(matched) / max(len(keywords), 1)
    scores['technical_accuracy'] = min(10, int(ratio * 10))
    missing = [k for k in keywords if k.lower() not in lower]
    if missing: feedback.append(f"Missing key concepts: {', '.join(missing[:3])}.")
    markers = ['first','second','third','finally','to begin','in conclusion','firstly','additionally','furthermore','also','next','lastly']
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
    improvement_required = wrong_pct
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
        "dsa": ["Always mention time complexity (Big O notation) for every algorithm.", "Always mention space complexity alongside time complexity.", "Give a concrete example with actual values — e.g. array [1,3,5,7,9]."],
        "hr": ["Use STAR format — Situation, Task, Action, Result.", "Always give a specific real example from your own experience.", "Quantify your impact where possible — use numbers."],
        "os": ["Start with a clear definition of the concept.", "Give a real world analogy or example.", "Mention prevention or solution strategies."],
        "cn": ["Name the specific protocol or OSI layer involved.", "Give a practical real world example of where it is used.", "Use correct technical terminology throughout."],
        "system_design": ["Start by clarifying functional and non-functional requirements.", "Always explain how the system scales to millions of users.", "Discuss database choice and justify why — SQL vs NoSQL."]
    }
    tips = round_tips.get(mode, round_tips["dsa"])
    need = max(0, 7 - total)
    round_focus = (f"To clear {mode.upper()} rounds you need 7+/10. You scored {total}/10 — need {need} more point{'s' if need != 1 else ''} to reach the bar." if need > 0 else f"Great — your {mode.upper()} score of {total}/10 clears the interview bar!")
    return {
        "verdict": verdict, "overall_msg": overall_msg, "correct_pct": correct_pct, "wrong_pct": wrong_pct, "improvement_required": improvement_required,
        "strength": f"{correct_pct}% of key concepts covered correctly.",
        "weakness": (f"{wrong_pct}% needs improvement. Weak areas: {', '.join(weak_dims)}." if weak_dims else f"{wrong_pct}% can still be improved with more detail."),
        "suggestion": f"For {mode.upper()} round: {tips[0]}", "mode_tips": tips[:3], "round_focus": round_focus
    }

def get_model_answer(question):
    answers = {
        "Explain binary search and its time complexity.": "Binary search works on a sorted array by repeatedly halving the search space. First compare the target with the middle element. If equal, return it. If target is smaller, search the left half. If larger, search the right half. Repeat until found or space is empty. Time complexity is O(log n) because we halve the input each step. Space complexity is O(1) for iterative and O(log n) for recursive due to call stack. For example, finding 7 in [1,3,5,7,9] — mid is 5, target is greater, search [7,9], mid is 7, found in 2 steps.",
        "What is dynamic programming? Give an example.": "Dynamic programming solves complex problems by breaking them into overlapping subproblems and storing results to avoid recomputation. Two approaches — memoization (top-down, cache recursive results) and tabulation (bottom-up, fill a table iteratively). Key condition is optimal substructure. For example Fibonacci: instead of recomputing fib(5) recursively many times, store fib(1)=1, fib(2)=1, fib(3)=2, fib(4)=3, fib(5)=5. Time complexity drops from O(2^n) to O(n). Used in problems like longest common subsequence, knapsack, and shortest path.",
        "How does quicksort work? What is its time complexity?": "Quicksort selects a pivot and partitions the array into two halves — elements smaller than pivot on the left, greater on the right. It recursively sorts both halves. Average time complexity is O(n log n). Worst case is O(n²) when pivot is always the smallest or largest element. Space complexity is O(log n) for the call stack. To avoid worst case use random pivot or median-of-three. Quicksort is faster in practice than merge sort for in-memory arrays due to better cache locality.",
        "What is a hash map and how does collision resolution work?": "A hash map stores key-value pairs using a hash function to compute an index for each key. Average O(1) for get, put, and delete. Collisions occur when two keys hash to the same index. Two resolution strategies: chaining — each index holds a linked list of colliding entries, and open addressing — probe the next available slot using linear probing, quadratic probing, or double hashing. Java HashMap uses chaining and converts chain to balanced tree when it exceeds 8 entries for O(log n) worst case.",
        "Explain the difference between BFS and DFS.": "BFS explores a graph level by level using a queue. It finds the shortest path in unweighted graphs. Time and space complexity are O(V+E). DFS explores as deep as possible along a branch before backtracking using a stack or recursion. DFS is better for detecting cycles, topological sorting, and finding connected components. BFS is better for shortest path and level-order traversal. For example in a social network BFS finds people within 2 connections while DFS explores all connections through one person first.",
        "What is a linked list? How does it differ from an array?": "A linked list is a data structure where each node contains data and a pointer to the next node. Arrays store elements in contiguous memory with O(1) random access by index. Linked lists store in non-contiguous memory with O(n) access since you traverse from head. Insertion and deletion at the beginning is O(1) for linked lists versus O(n) for arrays since shifting is needed. Arrays have better cache performance. Use arrays for random access, linked lists for frequent insertions and deletions.",
        "How do you detect a cycle in a linked list?": "Use Floyd's cycle detection — two pointers, slow moves one step and fast moves two steps. If there is a cycle, fast catches up to slow inside it. If fast reaches null, no cycle exists. Time complexity O(n), space complexity O(1). For example in 1->2->3->4->2 (cycle at 2), slow and fast will meet inside the cycle after a few iterations. To find the start of the cycle, reset one pointer to head after meeting point and move both one step at a time — they meet at cycle start.",
        "What is recursion? Explain with an example.": "Recursion is when a function calls itself to solve a smaller version of the same problem. Every recursive function needs a base case to stop recursion and a recursive case moving toward the base case. For example factorial: base case is factorial(0)=1, recursive case is factorial(n) = n * factorial(n-1). So factorial(4) = 4*3*2*1 = 24. Each call is added to the call stack and resolved when base case is reached. Space complexity is O(n) due to call stack depth. Recursion is used in tree traversal, DFS, divide and conquer algorithms.",
        "What is a stack and queue? Give real world examples.": "A stack is LIFO — Last In First Out. Operations push and pop are both O(1). Real world example: browser back button, undo in text editors, function call stack. A queue is FIFO — First In First Out. Enqueue and dequeue are both O(1). Real world example: printer queue, ticket booking line, BFS traversal. Stack is implemented using arrays or linked lists. Queue is implemented using circular array or two stacks. Deque supports insertion and deletion at both ends.",
        "Explain merge sort and why it is preferred over quicksort sometimes.": "Merge sort divides array into two halves, recursively sorts each, then merges. Time complexity O(n log n) in all cases — best, average, and worst. Space complexity O(n). Quicksort is O(n log n) average but O(n²) worst case. Merge sort is preferred when stable sort is needed — equal elements maintain original order. It is better for linked lists since merging is efficient. For external sorting on disk merge sort is better. Quicksort is faster for in-memory arrays due to better cache performance.",
        "Tell me about yourself.": "I am a final year Computer Science student. I have strong foundations in data structures, algorithms, and full stack web development. I built PrepSense, an AI-powered mock interview platform that gives real-time feedback on answers using a custom scoring engine, camera-based posture analysis, and answer comparison. I am proficient in Python, SQL, and JavaScript with hands-on experience in FastAPI and SQLAlchemy. I pick up new technologies quickly, work well under pressure, and take ownership of my work end to end. I am looking for a software engineering role where I can build products that solve real problems.",
        "What is your greatest strength? Give a specific example.": "My greatest strength is problem solving under pressure. I break complex problems into smaller subproblems, identify what I know and what I need to find out, and work systematically. For example while building PrepSense I noticed the scoring engine was inconsistent for similar answers. I logged every intermediate value, identified the keyword matching was case-sensitive and failing on capitalised words, and fixed it by normalising all text to lowercase. The fix took 20 minutes because I approached it methodically instead of guessing.",
        "What is your greatest weakness and what are you doing about it?": "My weakness is spending too much time perfecting one part before moving on. I have been fixing this using time-boxing — setting a fixed limit for each task and moving forward even if not fully satisfied, then revisiting later. I also use a task tracker to stay accountable to deadlines. This has improved my productivity noticeably and helped me ship features faster while maintaining quality.",
        "Where do you see yourself in 5 years?": "In 5 years I see myself as a senior software engineer who has shipped products real users depend on. First 2 years I want to go deep on one stack and learn to build scalable systems. By year 3-4 I want to mentor junior developers and own features end to end from design to deployment. By year 5 I want to make meaningful technical decisions and contribute to architecture. I am open to a tech lead role if the opportunity comes but my primary focus is becoming an excellent engineer first.",
        "Why should we hire you over other candidates?": "You should hire me because I build things, not just learn concepts. I built PrepSense — a full stack AI interview platform with a custom scoring engine, real-time feedback, camera analysis, and answer comparison. Beyond technical skills I pick up new things quickly, ask good questions, and take ownership. I will not wait to be told what to do — I identify problems, propose solutions, and execute. I am genuinely passionate about software engineering as a craft which means I keep improving long after joining.",
        "Describe a time you faced a conflict in a team.": "During a college project, two teammates disagreed on approach — one wanted a no-code tool for speed, other wanted to build from scratch for learning. I scheduled a 30-minute discussion where both explained their reasoning. I proposed a middle path — build core functionality from scratch, use libraries for non-critical parts. Both agreed because their core concerns were addressed. We finished on time and all three learned the technical concepts. The key was making sure both people felt heard before proposing a solution.",
        "Tell me about a project you are most proud of.": "I am most proud of PrepSense. Not because it is technically complex but because it solves a real problem I personally faced — getting feedback on interview answers at 2am when no mentor is available. I built the entire stack — FastAPI backend, SQLite with SQLAlchemy, custom scoring engine evaluating answers on 5 dimensions, live feedback as you type, camera posture analysis for HR rounds, and a comparison mode showing exactly what is missing from your answer. Every feature exists because I thought carefully about what would actually help a student prepare.",
        "What is the difference between a process and a thread?": "A process is an independent program in execution with its own memory space — code, data, heap, and stack. A thread is the smallest unit of execution within a process sharing the same memory. Processes are isolated — a crash in one does not affect others. Threads share memory making communication faster but requiring synchronisation with locks or semaphores. Context switching between threads is faster because less state needs saving. For example a browser uses separate processes per tab for isolation but multiple threads within each tab for rendering, JavaScript, and network calls simultaneously.",
        "Explain deadlock and how it can be prevented.": "Deadlock occurs when processes each wait for a resource held by another, causing all to wait forever. Four conditions must hold — mutual exclusion, hold and wait, no preemption, and circular wait. Prevention: use resource ordering to prevent circular wait, require all resources requested at once to prevent hold and wait, or allow preemption. Detection and recovery checks for cycles in the resource allocation graph and kills one process to break the cycle. Banker's algorithm avoids deadlock by only granting requests if the system stays in a safe state.",
        "What is virtual memory and why is it useful?": "Virtual memory gives each process the illusion of having its own large contiguous address space even if physical RAM is limited. The OS maps virtual addresses to physical addresses using a page table. When a process accesses a page not in RAM, a page fault occurs and OS loads it from disk, evicting another page if needed. Benefits: run programs larger than physical RAM, memory isolation between processes, simplified memory management. Downside is page fault overhead. Excessive paging is thrashing and severely degrades performance.",
        "What is a semaphore? How does it differ from a mutex?": "A semaphore uses a counter to control access to shared resources. Counting semaphore allows up to N processes. Binary semaphore allows one. Operations: wait decrements and blocks if zero, signal increments and wakes a waiting process. A mutex is for mutual exclusion — only the thread that locked it can unlock it, enforcing ownership. Semaphore has no ownership — any process can signal it. Use mutex for protecting a critical section, semaphore for signalling between processes or controlling access to a resource pool like database connections.",
        "What is paging in operating systems?": "Paging divides physical memory into fixed-size frames and logical memory into pages of the same size. OS maintains a page table per process mapping page numbers to frame numbers. MMU translates virtual addresses using the page table. Paging eliminates external fragmentation since any free frame holds any page. Internal fragmentation occurs in the last page. Page faults load pages from disk on demand. TLB caches recent page table entries for fast translation. Multi-level page tables reduce memory overhead for large address spaces.",
        "Explain the concept of thrashing.": "Thrashing occurs when a process spends more time paging than executing. It happens when too many processes compete for limited RAM causing frequent page faults. Each page fault triggers slow disk I/O and CPU utilisation drops drastically. The OS detects thrashing by monitoring page fault rate. Solutions: reduce degree of multiprogramming by suspending some processes, use working set model to ensure each process has enough frames for its active pages, or increase RAM. Thrashing is a sign that the system is overloaded beyond its memory capacity.",
        "What is inter-process communication?": "IPC allows processes to exchange data and synchronise. Methods: Pipes are unidirectional byte streams between related processes. Named pipes work between unrelated processes via filesystem. Message queues let processes send discrete messages through a kernel queue. Shared memory is fastest — processes map the same physical memory, requires explicit synchronisation with semaphores. Sockets communicate over network or locally. Signals notify a process of events asynchronously like SIGKILL and SIGTERM. Choice depends on relationship between processes, data size, and performance requirements.",
        "What is a context switch?": "A context switch saves the state of a running process and loads the state of another. State includes program counter, CPU registers, memory maps, and PCB. Triggers: preemption by scheduler, system call, blocking on I/O. Context switch is pure overhead — CPU does no useful work during it. Thread switches are faster than process switches because threads share the same memory space and page tables. Modern CPUs have many registers increasing context switch overhead. OS minimises context switches by using appropriate scheduling quantum.",
        "Explain preemptive vs non-preemptive scheduling.": "Preemptive scheduling can interrupt a running process before it finishes — the OS forcibly switches to another process based on priority or time quantum. Examples: Round Robin, Priority Preemptive. Non-preemptive scheduling runs a process until it completes, blocks, or voluntarily yields. Examples: FCFS, SJF non-preemptive. Preemptive is better for interactive and real-time systems where response time matters. Non-preemptive is simpler and avoids context switch overhead but can cause long waiting times. Modern OS use preemptive scheduling for better responsiveness.",
        "What is the difference between TCP and UDP?": "TCP is connection-oriented and guarantees reliable ordered delivery using three-way handshake, sequence numbers, acknowledgements, and retransmission. Flow control and congestion control prevent overwhelming receiver and network. Overhead makes it slower. UDP is connectionless with no delivery guarantee, ordering, or error recovery — just sends packets. TCP is used for HTTP, FTP, email, file transfer where correctness matters. UDP for DNS, video streaming, gaming, VoIP where low latency matters more. A dropped video frame is acceptable but a dropped payment transaction is not.",
        "Explain the OSI model and its 7 layers.": "Physical layer transmits raw bits — cables, radio. Data Link handles node-to-node delivery with MAC addresses and error detection — Ethernet, WiFi. Network handles logical addressing and routing with IP addresses — IP, routers. Transport provides end-to-end communication with error recovery — TCP, UDP, ports. Session manages connections between applications. Presentation handles encryption, compression, data format — SSL, JPEG. Application provides services to applications — HTTP, FTP, DNS, SMTP. TCP/IP model combines these into 4 layers: Network Access, Internet, Transport, Application.",
        "What happens when you type a URL in a browser?": "Browser checks DNS cache for IP address. If not found, queries DNS resolver which checks cache then queries root server, TLD server, and authoritative nameserver to get IP. Browser establishes TCP connection via three-way handshake. If HTTPS, TLS handshake establishes encryption. Browser sends HTTP GET request. Server processes and returns HTML response. Browser parses HTML and builds DOM. Fetches CSS and JavaScript with additional requests. CSS parsed to CSSOM. JavaScript executed. DOM and CSSOM combined into render tree. Browser paints pixels on screen.",
        "What is the difference between HTTP and HTTPS?": "HTTP transmits data in plaintext — anyone intercepting the network traffic can read it. HTTPS encrypts data using TLS. TLS uses asymmetric encryption for handshake — server sends certificate with public key, client verifies against CA, they exchange symmetric session key. All data encrypted with session key. HTTPS prevents man-in-the-middle attacks, eavesdropping, and tampering. Also improves SEO and enables HTTP/2. Port 80 for HTTP, port 443 for HTTPS.",
        "Explain the TCP three-way handshake.": "Step 1 SYN: client sends SYN with random sequence number X. Step 2 SYN-ACK: server acknowledges X+1 and sends its sequence number Y. Step 3 ACK: client acknowledges Y+1. Connection established with both sides knowing sequence numbers for ordering packets. Ensures both parties reachable and synchronises state. Four-way teardown uses FIN and ACK. SYN flood attack sends many SYN packets without completing handshakes.",
        "What is DNS and how does it work?": "DNS translates domain names to IP addresses. Distributed hierarchical database. Query: check local cache, ask recursive resolver, resolver queries root server, TLD server, authoritative nameserver which returns IP. Result cached with TTL. DNS uses UDP port 53 for small queries, TCP for larger. Record types: A (IPv4), AAAA (IPv6), CNAME (alias), MX (mail), TXT (verification), NS (nameserver).",
        "What is subnetting?": "Subnetting divides a large network into smaller sub-networks. Subnet mask defines network vs host bits. 192.168.1.0/24 means first 24 bits are network giving 254 usable hosts. CIDR replaced class-based addressing. Benefits: reduces broadcast traffic, improves security, enables efficient IP allocation. A company can divide /24 into four /26 subnets each with 62 usable hosts.",
        "Explain the difference between a hub, switch, and router.": "Hub broadcasts to all ports — Layer 1, causes collisions, obsolete. Switch learns MAC addresses and forwards only to target port — Layer 2, efficient. Router routes packets between different networks using IP addresses — Layer 3, connects to internet. Home router combines all three plus WiFi access point.",
        "What is ARP protocol?": "ARP maps IP addresses to MAC addresses within a LAN. Device broadcasts ARP request asking who has a given IP. Device with that IP responds with its MAC. Sender caches mapping in ARP table with TTL. Operates at Layer 2/3 boundary. ARP spoofing sends fake replies to enable man-in-the-middle attacks.",
        "What is the difference between IPv4 and IPv6?": "IPv4 is 32-bit giving 4.3B addresses — nearly exhausted. IPv6 is 128-bit giving unlimited addresses. IPv4 uses dotted decimal like 192.168.1.1. IPv6 uses hex groups. IPv6 has simplified header, built-in IPSec, no need for NAT. Transition uses dual stack, tunnelling, and NAT64.",
        "Design a URL shortener like bit.ly.": "Requirements: shorten URL, redirect, custom alias, expiry. Design: POST /shorten generates 6-character base62 code from auto-incremented ID. Store short_code, long_url, created_at, expiry in database. GET /{code} looks up Redis cache first, then database, returns 301 redirect. Scale: Redis cache for reads, CDN for latency, horizontal app servers behind load balancer, shard database at extreme scale.",
        "How would you design a basic chat application?": "Use WebSockets for real-time bidirectional connections. Message flow: user A sends, server finds B's WebSocket and delivers. If offline, store and deliver on reconnect. Database: Cassandra for write-heavy time-series messages. Schema: message_id, sender_id, receiver_id, content, timestamp. Scale: Kafka decouples sending from delivery. Multiple chat servers with presence service. Load balancer with sticky sessions.",
        "Design a notification system for millions of users.": "API publishes to Kafka by notification type. Workers consume and call FCM for push, SendGrid for email, Twilio for SMS. Each worker scales independently. Store log for history and deduplication. Retry with exponential backoff. Rate limit per user. User preference service filters before sending. Batch notifications to reduce API calls.",
    }
    q = question.lower().strip()
    if 'paging' in q: return "Paging divides physical memory into fixed-size frames and logical memory into pages. OS maintains a page table mapping pages to frames. MMU translates virtual to physical addresses. Eliminates external fragmentation. Page faults load pages from disk on demand. TLB caches recent translations for speed."
    if 'thrashing' in q: return "Thrashing occurs when a process spends more time paging than executing due to insufficient RAM. Frequent page faults trigger slow disk I/O, dropping CPU utilisation. Fix by reducing active processes, using working set model, or adding RAM."
    if 'semaphore' in q or 'mutex' in q: return "Semaphore uses a counter — counting allows N processes, binary allows one. Operations wait and signal. Mutex enforces ownership — only locker can unlock. Use mutex for critical sections, semaphore for signalling or resource pools."
    if 'ipc' in q or 'inter-process' in q: return "IPC methods: pipes for related processes, named pipes for unrelated, message queues for discrete messages, shared memory for fastest communication (needs semaphore sync), sockets for network/local, signals for async notification."
    if 'scheduling' in q: return "CPU scheduling: FCFS simple but convoy effect. SJF minimises waiting time. Round Robin fair with time quantum. Priority with aging prevents starvation. MLFQ best for general systems. Preemptive can interrupt running process."
    if 'subnetting' in q or 'subnet' in q: return "Subnetting divides a network into smaller sub-networks using subnet masks. /24 gives 254 usable hosts. Reduces broadcast traffic and improves security. CIDR notation replaced class-based addressing."
    if 'arp' in q: return "ARP maps IP addresses to MAC addresses within a LAN via broadcast request and unicast reply. Results cached in ARP table with TTL. ARP spoofing enables man-in-the-middle attacks by sending fake replies."
    if 'normalisation' in q or 'normalization' in q: return "1NF: atomic values, no repeating groups. 2NF: no partial dependencies on primary key. 3NF: no transitive dependencies. BCNF: stricter 3NF. Normalisation reduces redundancy and ensures data integrity."
    if 'index' in q and ('database' in q or 'sql' in q): return "Database index (B-tree or hash) speeds up queries from O(n) to O(log n). Primary index auto-created. Secondary on other columns. Composite covers multiple columns. Indexes slow writes. Use on frequently queried columns and foreign keys."
    if 'hub' in q or 'switch' in q or 'router' in q: return "Hub broadcasts to all ports (Layer 1, obsolete). Switch learns MAC addresses and forwards only to target port (Layer 2, efficient). Router routes between networks using IP (Layer 3, connects to internet)."
    if 'ipv4' in q or 'ipv6' in q: return "IPv4 is 32-bit giving 4.3B addresses (nearly exhausted). IPv6 is 128-bit giving unlimited addresses. IPv6 has simplified header, built-in security, no need for NAT."
    if 'http' in q and 'https' in q: return "HTTP sends data in plaintext. HTTPS encrypts using TLS — asymmetric for handshake, symmetric for data. Prevents eavesdropping and man-in-the-middle attacks. Port 80 vs 443."
    return (f"For the question '{question}': 1) Define the concept clearly in one sentence. 2) Explain how it works step by step. 3) Give a concrete example with specific values. 4) Mention time/space complexity or trade-offs. 5) Compare with a related concept to show depth.")