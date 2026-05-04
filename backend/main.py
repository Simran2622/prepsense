from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import engine, SessionLocal
from models import Base, User, Attempt
import random

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
        return {
            "total": 0, "avg": 0, "best": 0, "last": 0,
            "modes": {}, "recent": [], "scores_list": [],
            "improvement": 0, "weakest": "dsa"
        }

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

    recent = [
        {"mode": a.mode, "question": a.question, "score": a.score}
        for a in reversed(attempts[-5:])
    ]

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

    if word_count < 20:
        scores['clarity'] = 3
        feedback.append("Answer too short — aim for at least 4-5 sentences.")
    elif word_count > 300:
        scores['clarity'] = 6
        feedback.append("Answer too long — keep it concise.")
    else:
        scores['clarity'] = 8

    example_phrases = ['for example','for instance','such as','like when',
                       'in my project','consider','suppose','imagine','e.g']
    used = any(p in lower for p in example_phrases)
    scores['used_example'] = 10 if used else 0
    if not used:
        feedback.append("Always use a concrete example to support your answer.")

    keywords = get_keywords(question, mode)
    matched = [k for k in keywords if k.lower() in lower]
    ratio = len(matched) / max(len(keywords), 1)
    scores['technical_accuracy'] = min(10, int(ratio * 10))
    missing = [k for k in keywords if k.lower() not in lower]
    if missing:
        feedback.append(f"Missing key concepts: {', '.join(missing[:3])}.")

    markers = ['first','second','third','finally','to begin','in conclusion',
               'firstly','additionally','furthermore','also','next','lastly']
    count = sum(1 for m in markers if m in lower)
    scores['structure'] = min(10, count * 3)
    if count == 0:
        feedback.append("Structure your answer — use 'First... Then... Finally' format.")

    scores['completeness'] = 3 if word_count < 30 else 6 if word_count < 60 else 9

    scores['total'] = round(
        (scores['clarity'] + scores['used_example'] +
         scores['technical_accuracy'] + scores['structure'] +
         scores['completeness']) / 5
    )
    return scores, feedback

def generate_feedback(scores, rule_feedback, mode):
    total = scores['total']

    correct_pct = round(total * 10)
    wrong_pct = 100 - correct_pct
    improvement_required = wrong_pct

    if total >= 8:
        verdict = "Strong"
        overall_msg = "Excellent answer — well structured with good technical depth."
    elif total >= 6:
        verdict = "Good"
        overall_msg = "Good answer. You covered the main points."
    elif total >= 4:
        verdict = "Average"
        overall_msg = "Average answer. Significant improvement needed."
    else:
        verdict = "Weak"
        overall_msg = "Answer needs major improvement. Review the model answer."

    weak_dims = []
    if scores.get('technical_accuracy', 0) < 5:
        weak_dims.append("technical accuracy")
    if scores.get('used_example', 0) == 0:
        weak_dims.append("use of examples")
    if scores.get('structure', 0) < 5:
        weak_dims.append("answer structure")
    if scores.get('clarity', 0) < 6:
        weak_dims.append("clarity and length")

    round_tips = {
        "dsa": [
            "Always mention time complexity (Big O notation) for every algorithm.",
            "Always mention space complexity alongside time complexity.",
            "Give a concrete example with actual values — e.g. array [1,3,5,7,9].",
            "Explain edge cases — empty input, single element, duplicates.",
            "Compare with at least one alternative approach."
        ],
        "hr": [
            "Use STAR format — Situation, Task, Action, Result.",
            "Always give a specific real example from your own experience.",
            "Quantify your impact where possible — use numbers.",
            "Keep spoken answers between 1-2 minutes.",
            "End with what you learned or how it benefited the team."
        ],
        "os": [
            "Start with a clear definition of the concept.",
            "Explain why it happens or why it matters in a real system.",
            "Give a real world analogy or example.",
            "Mention prevention or solution strategies.",
            "Compare with a related concept to show depth."
        ],
        "cn": [
            "Name the specific protocol or OSI layer involved.",
            "Explain the difference between similar concepts clearly.",
            "Give a practical real world example of where it is used.",
            "Mention advantages and disadvantages.",
            "Use correct technical terminology throughout."
        ],
        "system_design": [
            "Start by clarifying functional and non-functional requirements.",
            "Always explain how the system scales to millions of users.",
            "Discuss database choice and justify why — SQL vs NoSQL.",
            "Mention caching strategy — Redis, CDN etc.",
            "Discuss failure scenarios and how your design handles them."
        ]
    }

    tips = round_tips.get(mode, round_tips["dsa"])
    need = max(0, 7 - total)
    round_focus = (
        f"To clear {mode.upper()} rounds you need 7+/10. "
        f"You scored {total}/10 — need {need} more point{'s' if need != 1 else ''} to reach the bar."
        if need > 0 else
        f"Great — your {mode.upper()} score of {total}/10 clears the interview bar!"
    )

    return {
        "verdict": verdict,
        "overall_msg": overall_msg,
        "correct_pct": correct_pct,
        "wrong_pct": wrong_pct,
        "improvement_required": improvement_required,
        "strength": f"{correct_pct}% of key concepts covered correctly.",
        "weakness": (
            f"{wrong_pct}% needs improvement. Weak areas: {', '.join(weak_dims)}."
            if weak_dims else f"{wrong_pct}% can still be improved with more detail."
        ),
        "suggestion": f"For {mode.upper()} round: {tips[0]}",
        "mode_tips": tips[:3],
        "round_focus": round_focus
    }

def get_model_answer(question):
    answers = {
        "Explain binary search and its time complexity.":
            "Binary search finds an element in a sorted array by repeatedly halving the search space. First compare the target with the middle element. If equal return it. If smaller search the left half. If larger search the right half. Time complexity is O(log n) because we halve the search space each step. Space complexity is O(1) for iterative. For example finding 7 in [1,3,5,7,9] — mid is 5, target is greater, search [7,9], mid is 7, found.",
        "Tell me about yourself.":
            "I am a final year Computer Science student with strong foundations in data structures, algorithms, and web development. I built PrepSense, an AI-powered mock interview platform that gives real-time feedback. I am proficient in Python, SQL, and JavaScript and looking for a software engineering role where I can build scalable products.",
        "What is the difference between a process and a thread?":
            "A process is an independent program in execution with its own memory space. A thread is a unit of execution within a process that shares the same memory. Processes are isolated — a crash in one does not affect others. Threads share memory making communication faster but requiring synchronisation. Context switching between threads is faster than between processes. For example a browser uses separate processes per tab but multiple threads within each tab.",
        "What is the difference between TCP and UDP?":
            "TCP is connection-oriented and guarantees reliable ordered delivery using a three-way handshake. UDP is connectionless with no delivery guarantee but is much faster. TCP is used for web browsing, email, and file transfer. UDP is used for video streaming, online gaming, and DNS queries where speed matters more than perfect delivery. For example HTTP uses TCP while live video calls use UDP."
    }
    return answers.get(
        question,
        "Structure your answer with: 1) Clear definition, 2) How it works step by step, 3) A concrete example with real values, 4) Time/space complexity or trade-offs where applicable."
    )