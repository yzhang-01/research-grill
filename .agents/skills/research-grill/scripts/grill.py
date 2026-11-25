"""Local records and portable weekly packages for the Research Grill skill."""

import argparse
import hashlib
import io
import json
import re
import sqlite3
import sys
import tempfile
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

FINAL_QUESTIONS = {"en": "Is there anything else you would like to add?", "zh-CN": "你还有什么要补充的？"}
DEFAULT_LANGUAGE = "en"
LEGACY_LANGUAGE = "zh-CN"
PACKAGE_SCHEMA = 1
RECORD_KINDS = ("progress", "evidence", "blocker", "extra", "activity", "commitment", "feedback", "supplement")
SOURCES = ("self_report", "evidence", "skill")
STATUSES = ("complete", "partial", "unfinished", "blocked", "unclear")
JUDGMENTS = ("supported", "plausible", "conflicting", "insufficient")
MAX_RECORD = 16 * 1024 * 1024


def demand(condition, message):
    if not condition:
        raise ValueError(message)


def obj(value, field):
    demand(isinstance(value, dict), f"{field} must be an object")
    return value


def items(value, field):
    demand(isinstance(value, list), f"{field} must be a list")
    return value


def required(value, field):
    demand(isinstance(value, str) and value.strip(), f"{field} must be nonempty text")
    return value


def optional(value, field):
    demand(isinstance(value, str), f"{field} must be text")
    return value


def choice(value, choices, field):
    demand(value in choices, f"{field} must be one of: {', '.join(choices)}")
    return value


def key(value, field):
    demand(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value),
           f"{field} must be a 1–64 character identifier using ASCII letters, digits, _ or -")
    return value


def week_key(value):
    demand(isinstance(value, str) and re.fullmatch(r"\d{4}-W\d{2}", value), "week must be YYYY-Www")
    date.fromisocalendar(int(value[:4]), int(value[6:]), 1)
    return value


def day(value, field):
    value = required(value, field)
    demand(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), f"{field} must be YYYY-MM-DD")
    return date.fromisoformat(value)


def timestamp(value):
    parsed = datetime.fromisoformat(required(value, "timestamp"))
    demand(parsed.utcoffset() is not None, "timestamp requires a UTC offset")
    return parsed


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def identity(data):
    return {
        "project_id": key(data.get("project_id"), "project_id"),
        "student_id": key(data.get("student_id"), "student_id"),
        "student_name": required(data.get("student_name"), "student_name"),
    }


def goals(data):
    result = []
    for index, raw in enumerate(items(data.get("goals"), "goals"), 1):
        raw = obj(raw, "goal")
        critical = raw.get("critical", False)
        demand(isinstance(critical, bool), "critical must be true or false")
        result.append({
            "id": f"G{index}",
            "title": required(raw.get("title"), "title"),
            "deliverable": required(raw.get("deliverable"), "deliverable"),
            "criteria": required(raw.get("criteria"), "criteria"),
            "due": day(raw.get("due"), "due").isoformat(),
            "critical": critical,
        })
    demand(result, "at least one goal is required")
    return result


def init_store(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS weeks (week TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS packages (
            project TEXT, student TEXT, week TEXT, version INTEGER,
            data TEXT NOT NULL,
            PRIMARY KEY (project, student, week, version)
        );
        CREATE TABLE IF NOT EXISTS rosters (project TEXT PRIMARY KEY, data TEXT NOT NULL);
    """)


def get_week(db, week):
    row = db.execute("SELECT data FROM weeks WHERE week = ?", (week,)).fetchone()
    demand(row, f"No frozen goals for {week}")
    return json.loads(row[0])


def save_week(db, week, state):
    db.execute(
        "INSERT INTO weeks VALUES (?, ?) ON CONFLICT(week) DO UPDATE SET data = excluded.data",
        (week, encode(state)),
    )


def goal_id(state, value, required_id=False):
    if value is None and not required_id:
        return None
    demand(any(goal["id"] == value for goal in state["goals"]), "unknown goal_id")
    return value


def append_record(state, data, at):
    record = {
        "id": f"R{len(state['records']) + 1}",
        "kind": choice(data.get("kind"), RECORD_KINDS, "kind"),
        "goal_id": goal_id(state, data.get("goal_id")),
        "text": required(data.get("text"), "text"),
        "source": choice(data.get("source", "self_report"), SOURCES, "source"),
        "reference": optional(data.get("reference", ""), "reference"),
        "at": at,
    }
    if record["source"] == "evidence" or record["kind"] == "evidence":
        required(record["reference"], "reference")
    if "observed_on" in data:
        observed = day(data["observed_on"], "observed_on")
        demand(observed <= timestamp(at).date(), "observed_on is in the future")
        record["observed_on"] = observed.isoformat()
    state["records"].append(record)
    return record


def questions_covered(state):
    return {q["goal_id"] for q in state["questions"] if q["kind"] == "goal" and "answer" in q}


def ask(state, data, at):
    questions = state["questions"]
    demand(not questions or "answer" in questions[-1], "answer the pending question first")
    kind = choice(data.get("kind"), ("goal", "followup", "final"), "kind")
    gid = goal_id(state, data.get("goal_id"), required_id=kind == "goal")
    if kind == "final":
        demand(gid is None, "the final question has no goal_id")
        demand(questions_covered(state) == {g["id"] for g in state["goals"]}, "answer one question per goal first")
        if state["version"] == 0:
            followed_up = {q["goal_id"] for q in questions if q["kind"] == "followup" and "answer" in q}
            missing = [goal["id"] for goal in state["goals"] if goal["id"] not in followed_up]
            demand(not missing, f"answer a goal-specific follow-up first for: {', '.join(missing)}")
        prompt = FINAL_QUESTIONS[state.get("language", LEGACY_LANGUAGE)]
    else:
        if kind == "followup" and gid is not None:
            demand(gid in questions_covered(state), "answer the initial goal question before its follow-up")
        prompt = required(data.get("prompt"), "prompt")
    question = {"id": f"Q{len(questions) + 1}", "goal_id": gid, "kind": kind, "prompt": prompt, "asked_at": at}
    questions.append(question)
    return question


def answer(state, data, at):
    demand(state["questions"], "there is no pending question")
    question = state["questions"][-1]
    demand(question["id"] == data.get("question_id") and "answer" not in question, "question_id must match the pending question")
    text = required(data.get("text"), "text")
    if question["kind"] == "final":
        confirmed = data.get("no_more")
        demand(isinstance(confirmed, bool), "the final answer needs no_more true or false")
        if not confirmed:
            append_record(state, {"kind": "supplement", "text": text}, at)
        question["no_more"] = confirmed
    question.update(answer=text, answered_at=at)
    return question


def assessments(state, data, at):
    result = {}
    valid_refs = {r["id"] for r in state["records"]}
    valid_refs.update(q["id"] for q in state["questions"] if "answer" in q)
    for raw in items(data.get("assessments"), "assessments"):
        raw = obj(raw, "assessment")
        gid = goal_id(state, raw.get("goal_id"), required_id=True)
        demand(gid not in result, f"duplicate assessment for {gid}")
        refs = items(raw.get("refs"), "refs")
        demand(refs and all(isinstance(r, str) and r in valid_refs for r in refs),
               f"{gid} needs references to recorded evidence or answers")
        record = {
            "goal_id": gid,
            "status": choice(raw.get("status"), STATUSES, "status"),
            "outcome": required(raw.get("outcome"), "outcome"),
            "student_explanation": optional(raw.get("student_explanation", ""), "student_explanation"),
            "judgment": choice(raw.get("judgment"), JUDGMENTS, "judgment"),
            "basis": required(raw.get("basis"), "basis"),
            "response_observation": required(raw.get("response_observation"), "response_observation"),
            "refs": list(dict.fromkeys(refs)),
            "next_step": optional(raw.get("next_step", ""), "next_step"),
        }
        if "delivered_on" in raw:
            delivered = day(raw["delivered_on"], "delivered_on")
            demand(delivered <= timestamp(at).date(), "delivered_on is in the future")
            demand(record["status"] == "complete", "delivered_on requires a complete goal")
            record["delivered_on"] = delivered.isoformat()
        result[gid] = record
    demand(set(result) == {g["id"] for g in state["goals"]}, "assess every frozen goal once")
    return [result[g["id"]] for g in state["goals"]]


def save_package(db, package):
    who = package["identity"]
    identifier = (who["project_id"], who["student_id"], package["week"], package["version"])
    serialized = encode(package)
    previous = db.execute(
        "SELECT data FROM packages WHERE project = ? AND student = ? AND week = ? AND version = ?", identifier
    ).fetchone()
    if previous:
        demand(previous[0] == serialized, "another package already uses this project, student, week and version")
        return False
    db.execute("INSERT INTO packages VALUES (?, ?, ?, ?, ?)", (*identifier, serialized))
    return True


def close(db, state, who, week, data, at):
    questions = state["questions"]
    demand(questions and questions[-1]["kind"] == "final" and questions[-1].get("no_more") is True,
           "finish the final question before closing")
    demand(len(questions) > state.get("questions_before_amendment", 0),
           "ask and answer the final question again after amending")
    package = {
        "schema": PACKAGE_SCHEMA,
        "identity": who,
        "week": week,
        "version": state["version"] + 1,
        "frozen_at": state["frozen_at"],
        "freeze_source": "student_device",
        "first_closed_at": state.get("first_closed_at", at),
        "closed_at": at,
        "direction": state["direction"],
        "goals": state["goals"],
        "records": state["records"],
        "questions": questions,
        "assessments": assessments(state, data, at),
    }
    if "language" in state:
        package["language"] = state["language"]
    save_package(db, package)
    state.update(closed=True, version=package["version"], first_closed_at=package["first_closed_at"],
                 latest_assessments=package["assessments"])
    return package


def report_markdown(package):
    if package.get("language", LEGACY_LANGUAGE) == "en":
        return english_report(package)
    return chinese_report(package)


def english_report(package):
    labels = dict(zip(STATUSES, ("Complete", "Partially complete", "Unfinished", "Blocked", "Unclear")))
    judgments = dict(zip(JUDGMENTS, ("Supported", "Plausible, unverified", "Conflicts with records", "Insufficient information")))
    who = package["identity"]
    parts = [
        f"# {who['student_name']} · {package['week']} research review",
        f"Project {who['project_id']} · Participant {who['student_id']} · Version {package['version']}",
        f"Review completed. Goals confirmed on the participant's device at {package['frozen_at']}. "
        f"Review closed at {package['closed_at']}.",
    ]
    if package["direction"]:
        parts.append(f"**Research direction** — {package['direction']}")
    for goal, assessed in zip(package["goals"], package["assessments"]):
        parts.append("\n".join([
            f"## {goal['id']} {goal['title']}",
            f"- Commitment — {goal['deliverable']} (due {goal['due']})",
            f"- Acceptance criteria — {goal['criteria']}",
            f"- Progress ({labels[assessed['status']]}) — {assessed['outcome']}",
            f"- Participant's explanation — {assessed['student_explanation'] or 'None recorded'}",
            f"- AI assessment ({judgments[assessed['judgment']]}) — {assessed['basis']}",
            f"- Observations from the review — {assessed['response_observation']}",
            f"- Record references — {', '.join(assessed['refs'])}",
            f"- Next step — {assessed['next_step'] or 'None recorded'}",
        ]))
    if package["records"]:
        parts.append("## Additional records and evidence")
        for record in package["records"]:
            reference = f" · {record['reference']}" if record["reference"] else ""
            parts.append(f"- {record['id']} · {record['kind']} · {record['source']} · {record['text']}{reference}")
    parts.append("See record.json for the verbatim review, evidence index, and timestamps.")
    return "\n\n".join(parts) + "\n"


def chinese_report(package):
    labels = dict(zip(STATUSES, ("已完成", "部分完成", "未完成", "受阻", "待判断")))
    judgments = dict(zip(JUDGMENTS, ("有材料支持", "说得通但待验证", "与记录冲突", "信息不足")))
    who = package["identity"]
    parts = [
        f"# {who['student_name']} · {package['week']} 科研周报",
        f"项目 {who['project_id']} · 学生 {who['student_id']} · 版本 {package['version']}",
        f"答辩已完成。目标确认时间取自学生端 {package['frozen_at']}。结案时间 {package['closed_at']}。",
    ]
    if package["direction"]:
        parts.append(f"研究方向：{package['direction']}")
    for goal, assessed in zip(package["goals"], package["assessments"]):
        parts.append("\n".join([
            f"## {goal['id']} {goal['title']}",
            f"- 承诺：{goal['deliverable']}，截止 {goal['due']}。",
            f"- 验收标准：{goal['criteria']}",
            f"- 进展（{labels[assessed['status']]}）：{assessed['outcome']}",
            f"- 学生解释：{assessed['student_explanation'] or '无单独解释'}",
            f"- AI 判断（{judgments[assessed['judgment']]}）：{assessed['basis']}",
            f"- 答辩表现：{assessed['response_observation']}",
            f"- 依据编号：{', '.join(assessed['refs'])}",
            f"- 下一步：{assessed['next_step'] or '未记录'}",
        ]))
    if package["records"]:
        parts.append("## 追加记录与证据")
        for record in package["records"]:
            link = f" · {record['reference']}" if record["reference"] else ""
            parts.append(f"- {record['id']} · {record['kind']} · {record['source']} · {record['text']}{link}")
    parts.append("答辩原文、证据索引和时间戳见包内 record.json。")
    return "\n\n".join(parts) + "\n"


def export_package(package, folder):
    data = encode(package).encode("utf-8")
    demand(len(data) <= MAX_RECORD, "package exceeds the structured record size limit")
    who = package["identity"]
    digest = hashlib.sha256(data).hexdigest()[:12]
    name = f"{who['project_id']}--{who['student_id']}--{package['week']}--v{package['version']}--{digest}.zip"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / name
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(zipfile.ZipInfo("record.json"), data, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr(zipfile.ZipInfo("report.md"), report_markdown(package).encode("utf-8"),
                         compress_type=zipfile.ZIP_DEFLATED)
    # Earlier versions have distinct names. Replace only the matching snapshot.
    with tempfile.NamedTemporaryFile(dir=folder, suffix=".part", delete=False) as temporary:
        temporary.write(stream.getvalue())
        draft = Path(temporary.name)
    try:
        draft.replace(destination)
    finally:
        draft.unlink(missing_ok=True)
    return str(destination)


def read_package(path):
    with zipfile.ZipFile(path) as archive:
        matches = [entry for entry in archive.infolist() if entry.filename == "record.json"]
        demand(len(matches) == 1 and matches[0].file_size <= MAX_RECORD, "invalid record.json in ZIP")
        package = obj(json.loads(archive.read(matches[0]).decode("utf-8")), "package")
    demand(type(package.get("schema")) is int and package["schema"] == PACKAGE_SCHEMA, "unsupported package schema")
    language = choice(package.get("language", LEGACY_LANGUAGE), tuple(FINAL_QUESTIONS), "language")
    demand(identity(obj(package.get("identity"), "identity")) == package["identity"], "invalid identity")
    week_key(package.get("week"))
    demand(type(package.get("version")) is int and package["version"] >= 1, "invalid version")
    at = required(package.get("closed_at"), "closed_at")
    demand(timestamp(package.get("frozen_at")) <= timestamp(package.get("first_closed_at")) <= timestamp(at),
           "invalid goal confirmation or close times")
    demand(package.get("freeze_source") == "student_device", "invalid freeze source")
    optional(package.get("direction"), "direction")
    demand(goals(package) == package["goals"], "invalid frozen goals")
    state = {"goals": package["goals"], "records": [], "questions": []}
    for raw in items(package.get("records"), "records"):
        timestamp(obj(raw, "record").get("at"))
        demand(append_record(state, raw, raw["at"]) == raw, "invalid record")
    for index, raw in enumerate(items(package.get("questions"), "questions"), 1):
        raw = obj(raw, "question")
        demand(raw.get("id") == f"Q{index}", "invalid question id")
        goal_id(state, raw.get("goal_id"), required_id=raw.get("kind") == "goal")
        choice(raw.get("kind"), ("goal", "followup", "final"), "question kind")
        required(raw.get("prompt"), "prompt")
        required(raw.get("answer"), "answer")
        timestamp(raw.get("asked_at"))
        timestamp(raw.get("answered_at"))
        if raw["kind"] == "final":
            demand(raw["prompt"] == FINAL_QUESTIONS[language] and type(raw.get("no_more")) is bool, "invalid final question")
        state["questions"].append(raw)
    questions = state["questions"]
    demand(questions and questions[-1]["kind"] == "final" and questions[-1]["no_more"],
           "package has not completed the final question")
    demand(questions_covered(state) == {g["id"] for g in state["goals"]}, "missing goal questions")
    demand(assessments(state, package, at) == package["assessments"], "invalid assessments")
    return package


def latest_packages(db, project, as_of):
    rows = db.execute("""
        SELECT student, week, data FROM packages WHERE project = ? ORDER BY student, week, version
    """, (project,))
    latest = {}
    for student, week, raw in rows:
        package = json.loads(raw)
        if timestamp(package["closed_at"]).date() <= as_of:
            latest[student, week] = package
    return list(latest.values())


def measure(package, as_of):
    assessed = {a["goal_id"]: a for a in package["assessments"]}
    goals_by_status = dict.fromkeys(STATUSES, 0)
    overdue = []
    on_time = 0
    delivery_date_unknown = 0
    for goal in package["goals"]:
        a = assessed[goal["id"]]
        goals_by_status[a["status"]] += 1
        due = date.fromisoformat(goal["due"])
        if a["status"] == "complete":
            if "delivered_on" in a:
                on_time += a["delivered_on"] <= goal["due"]
            else:
                delivery_date_unknown += 1
        elif due < as_of:
            overdue.append({"goal_id": goal["id"], "days": (as_of - due).days,
                            "critical": goal["critical"], "status": a["status"]})
    records = Counter(r["kind"] for r in package["records"])
    sources = Counter(r["source"] for r in package["records"])
    week = week_key(package["week"])
    year, number = int(week[:4]), int(week[6:])
    start = date.fromisocalendar(year, number, 1)
    end = date.fromisocalendar(year, number, 7)
    observed_days = {timestamp(package["frozen_at"]).date(), timestamp(package["closed_at"]).date()}
    observed_days.update(timestamp(q["answered_at"]).date() for q in package["questions"])
    observed_days.update(timestamp(r["at"]).date() for r in package["records"])
    reported_days = {date.fromisoformat(r["observed_on"]) for r in package["records"] if "observed_on" in r}
    evidence_goals = {r["goal_id"] for r in package["records"] if r["kind"] == "evidence" or r["source"] == "evidence"}
    evidence_goals.discard(None)
    return {
        "goal_count": len(assessed),
        "status_counts": goals_by_status,
        "completion_rate": goals_by_status["complete"] / len(assessed),
        "on_time_deliveries_confirmed": on_time,
        "completed_without_delivery_date": delivery_date_unknown,
        "overdue": overdue,
        "evidence_goal_count": len(evidence_goals),
        "record_counts": dict(records),
        "source_counts": dict(sources),
        "judgment_counts": dict(Counter(a["judgment"] for a in assessed.values())),
        "question_count": len(package["questions"]),
        "skill_active_days": sum(start <= d <= end for d in observed_days),
        "additional_reported_days": sum(start <= d <= end for d in reported_days - observed_days),
        "activity_scope": "Skill workspace events and explicitly dated supplements. Full Codex usage is unobserved.",
        "goal_results": [
            {"goal_id": g["id"], "title": g["title"], "critical": g["critical"], "due": g["due"],
             "status": assessed[g["id"]]["status"], "judgment": assessed[g["id"]]["judgment"],
             "refs": assessed[g["id"]]["refs"]}
            for g in package["goals"]
        ],
    }


def summary(db, data, week):
    project = key(data.get("project_id"), "project_id")
    as_of = day(data.get("as_of", date.today().isoformat()), "as_of")
    packages = latest_packages(db, project, as_of)
    row = db.execute("SELECT data FROM rosters WHERE project = ?", (project,)).fetchone()
    settings = json.loads(row[0]) if row else {"students": {}, "due_offset_days": 6}
    roster = settings["students"]
    monday = date.fromisocalendar(int(week[:4]), int(week[6:]), 1)
    report_due = monday + timedelta(days=settings["due_offset_days"])
    by_student = {}
    keys = ("completion_rate", "skill_active_days", "additional_reported_days", "evidence_goal_count")
    for p in packages:
        if p["week"] <= week:
            by_student.setdefault(p["identity"]["student_id"], []).append(p)
    students = []
    for student in sorted(by_student.keys() | roster.keys()):
        history = by_student.get(student, [])
        current = next((p for p in history if p["week"] == week), None)
        enrollment = roster.get(student, {})
        expected_from = enrollment.get("from_week")
        expected_through = enrollment.get("through_week")
        expected = expected_from is not None and expected_from <= week and (expected_through is None or week <= expected_through)
        display = history[-1]["identity"]["student_name"] if history else roster[student]["student_name"]
        result = {"student_id": student, "student_name": display, "expected": expected, "weekly": []}
        for p in history:
            metrics = measure(p, as_of if p["week"] == week else timestamp(p["closed_at"]).date())
            result["weekly"].append({"week": p["week"], "version": p["version"], **metrics})
        if current:
            result["current"] = "reported"
            result["closed_on_time"] = timestamp(current["first_closed_at"]).date() <= report_due if expected else None
        elif expected:
            result["current"] = "missing" if as_of > report_due else "pending"
        else:
            result["current"] = "unknown"
        prior = [m for m in result["weekly"] if m["week"] < week][-4:]
        if prior and current:
            latest = result["weekly"][-1]
            baseline = {k: sum(m[k] for m in prior) / len(prior) for k in keys}
            result["comparison"] = {
                "baseline_weeks": [m["week"] for m in prior],
                "baseline": baseline,
                "change": {k: latest[k] - baseline[k] for k in keys},
            }
        students.append(result)
    return {"project_id": project, "week": week, "as_of": as_of.isoformat(), "report_due": report_due.isoformat(),
            "roster_configured": bool(row), "students": students}


def package_entry(db, data, week):
    project = key(data.get("project_id"), "project_id")
    student = key(data.get("student_id"), "student_id")
    version = data.get("version")
    if version is not None:
        demand(type(version) is int and version >= 1, "version must be a positive integer")
    row = db.execute("""
        SELECT data FROM packages WHERE project = ? AND student = ? AND week = ?
        AND version = COALESCE(?, (SELECT MAX(version) FROM packages WHERE project = ? AND student = ? AND week = ?))
    """, (project, student, week, version, project, student, week)).fetchone()
    demand(row, "package version is not available")
    return json.loads(row[0])


def run(db, command, data, week):
    if command == "import":
        paths = items(data.get("paths"), "paths")
        demand(paths, "provide at least one ZIP path")
        return {"imported": [
            {"path": path, "added": save_package(db, read_package(Path(required(path, "path"))))}
            for path in paths
        ]}
    if command == "roster":
        project = key(data.get("project_id"), "project_id")
        due_offset = data.get("due_offset_days", 6)
        demand(type(due_offset) is int and 0 <= due_offset <= 7, "due_offset_days must be 0–7 after Monday")
        roster = {}
        for entry in items(data.get("students"), "students"):
            entry = obj(entry, "student")
            identifier = key(entry.get("student_id"), "student_id")
            demand(identifier not in roster, "duplicate student_id")
            roster[identifier] = {"student_name": required(entry.get("student_name"), "student_name"),
                                  "from_week": week_key(entry.get("from_week"))}
            if "through_week" in entry:
                through = week_key(entry["through_week"])
                demand(through >= roster[identifier]["from_week"], "through_week must be on or after from_week")
                roster[identifier]["through_week"] = through
        settings = {"students": roster, "due_offset_days": due_offset}
        db.execute("INSERT INTO rosters VALUES (?, ?) ON CONFLICT(project) DO UPDATE SET data = excluded.data",
                   (project, encode(settings)))
        return {"project_id": project, **settings}
    if command == "summary":
        return summary(db, data, week)
    if command == "view":
        return package_entry(db, data, week)
    row = db.execute("SELECT data FROM profile WHERE id = 1").fetchone()
    who = json.loads(row[0]) if row else None
    if command == "init":
        requested = identity(data)
        demand(who is None or who == requested, "this workspace already has a different identity")
        db.execute("INSERT OR IGNORE INTO profile VALUES (1, ?)", (encode(requested),))
        return requested
    if command == "status":
        limit = data.get("history_limit", 4)
        demand(type(limit) is int and limit >= 0, "history_limit must be a nonnegative integer")
        rows = db.execute("SELECT week, data FROM weeks WHERE week < ? ORDER BY week DESC LIMIT ?", (week, limit))
        current = db.execute("SELECT data FROM weeks WHERE week = ?", (week,)).fetchone()
        return {"identity": who, "week": week,
                "current": json.loads(current[0]) if current else None,
                "history": [{"week": period, **json.loads(raw)} for period, raw in rows]}
    demand(who, "set a workspace identity with init first")
    at = now()
    if command == "freeze":
        demand(not db.execute("SELECT 1 FROM weeks WHERE week = ?", (week,)).fetchone(),
               "weekly goals are already frozen")
        state = {
            "frozen_at": at, "direction": optional(data.get("direction", ""), "direction"),
            "language": choice(data.get("language", DEFAULT_LANGUAGE), tuple(FINAL_QUESTIONS), "language"),
            "goals": goals(data), "records": [], "questions": [], "closed": False, "version": 0,
        }
        save_week(db, week, state)
        return state
    if command == "export":
        return package_entry(db, {**data, "project_id": who["project_id"], "student_id": who["student_id"]}, week)
    state = get_week(db, week)
    if command == "amend":
        demand(state["closed"], "finish the open week or active amendment first")
        state["closed"] = False
        state["questions_before_amendment"] = len(state["questions"])
        result = append_record(state, {"kind": "supplement", "text": data.get("text")}, at)
    else:
        demand(not state["closed"], "this week is closed. Use amend to append a correction or export the existing version")
        if command == "record":
            result = append_record(state, data, at)
        elif command == "ask":
            result = ask(state, data, at)
        elif command == "answer":
            result = answer(state, data, at)
        else:
            result = close(db, state, who, week, data, at)
    save_week(db, week, state)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="existing project workspace")
    parser.add_argument("command", choices=(
        "init", "status", "freeze", "record", "ask", "answer", "close", "amend",
        "export", "import", "roster", "summary", "view",
    ))
    parser.add_argument("--week", help="ISO period YYYY-Www, required for weekly operations")
    parser.add_argument("--input", help="UTF-8 JSON object file, or - for stdin")
    args = parser.parse_args()
    try:
        demand(args.root.is_dir(), "workspace directory does not exist")
        week = week_key(args.week) if args.command not in ("init", "import", "roster") or args.week else None
        if args.input:
            raw = sys.stdin.buffer.read().decode("utf-8-sig") if args.input == "-" else Path(args.input).read_text(encoding="utf-8-sig")
            data = obj(json.loads(raw), "input")
        else:
            data = {}
        folder = args.root.resolve() / ".research-grill"
        folder.mkdir(exist_ok=True)
        with sqlite3.connect(folder / "records.sqlite3", timeout=15) as db:
            init_store(db)
            db.execute("BEGIN IMMEDIATE")
            result = run(db, args.command, data, week)
        if args.command in ("close", "export"):
            result = {"path": export_package(result, folder / "exports"), "week": week, "version": result["version"]}
        print(encode(result))
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, RuntimeError, zipfile.BadZipFile) as error:
        print(f"Research Grill: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
