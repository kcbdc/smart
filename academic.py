"""Normalized academic records and attendance-policy proof of concept.
All records are synthetic; NOT an accredited attendance or registrar system.
"""
import json, sqlite3, secrets, time, os
import attendance_rules

COURSES = [
 ('AI101','인공지능의 이해',3,'professor'),
 ('BUS201','디지털 경영전략',3,'professor'),
 ('SOC110','사회복지개론',3,'professor'),
 ('UX301','사용자 경험 설계',3,'professor'),
 ('DAT210','데이터 분석 기초',3,'professor'),
]
POLICY={'min_watch_ratio':0.8,'min_watch_seconds':12,'video_duration_seconds':15,'max_credits':9,'heartbeat_interval_seconds':3}

def init(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS academic_courses (code TEXT PRIMARY KEY,title TEXT NOT NULL,credits INTEGER NOT NULL,teacher TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS enrollments (student TEXT NOT NULL,course TEXT NOT NULL,created_at INTEGER NOT NULL,PRIMARY KEY(student,course),FOREIGN KEY(course) REFERENCES academic_courses(code));
 CREATE TABLE IF NOT EXISTS video_sessions (id TEXT PRIMARY KEY,student TEXT NOT NULL,course TEXT NOT NULL,lesson INTEGER NOT NULL,started_at REAL NOT NULL,last_at REAL NOT NULL,last_position REAL NOT NULL DEFAULT 0,credited_seconds REAL NOT NULL DEFAULT 0,closed INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS attendance (student TEXT NOT NULL,course TEXT NOT NULL,lesson INTEGER NOT NULL,recognized_at INTEGER NOT NULL,ratio REAL NOT NULL,rule_version TEXT NOT NULL,PRIMARY KEY(student,course,lesson));
 CREATE TABLE IF NOT EXISTS academic_requests (id INTEGER PRIMARY KEY AUTOINCREMENT,student TEXT NOT NULL,request_type TEXT NOT NULL,note TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS academic_audit (id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT NOT NULL,action TEXT NOT NULL,subject TEXT NOT NULL,ts INTEGER NOT NULL);
 ''')
 db.executemany('INSERT OR IGNORE INTO academic_courses VALUES (?,?,?,?)',COURSES)
 cols=[r[1] for r in db.execute('PRAGMA table_info(video_sessions)')]
 if 'policy_json' not in cols:db.execute('ALTER TABLE video_sessions ADD COLUMN policy_json TEXT')
 if 'duration_seconds' not in cols:db.execute('ALTER TABLE video_sessions ADD COLUMN duration_seconds INTEGER')
 # Synthetic initial enrollment for LMS demonstration; no registration decisions made here.
 now=int(time.time())
 db.executemany('INSERT OR IGNORE INTO enrollments VALUES (?,?,?)',[('student',c,now) for c in ['AI101','BUS201','SOC110']])

def catalog(db, student=None):
 rows=db.execute('SELECT code,title,credits,teacher FROM academic_courses ORDER BY code').fetchall()
 enrolled=set(x[0] for x in db.execute('SELECT course FROM enrollments WHERE student=?',(student,)).fetchall()) if student else set()
 return [dict(x, enrolled=x['code'] in enrolled) for x in rows]

def attendances(db, student):
 return [dict(x) for x in db.execute('SELECT student,course,lesson,recognized_at,ratio,rule_version FROM attendance WHERE student=? ORDER BY recognized_at DESC',(student,)).fetchall()]

def audit(db,actor,action,subject):
 db.execute('INSERT INTO academic_audit(actor,action,subject,ts) VALUES (?,?,?,?)',(actor,action,subject,int(time.time())))

def enrollment(db, student, course, operation):
 c=db.execute('SELECT credits FROM academic_courses WHERE code=?',(course,)).fetchone()
 if not c: return 404,{'error':'Unknown course'}
 if operation not in ('enroll','drop'):return 400,{'error':'Invalid operation'}
 with db:
  if operation=='enroll':
   current=db.execute('SELECT COALESCE(SUM(c.credits),0) FROM enrollments e JOIN academic_courses c ON c.code=e.course WHERE e.student=?',(student,)).fetchone()[0]
   exists=db.execute('SELECT 1 FROM enrollments WHERE student=? AND course=?',(student,course)).fetchone()
   if not exists and current+c['credits']>POLICY['max_credits']:return 409,{'error':'Credit limit exceeded','current_credits':current}
   db.execute('INSERT OR IGNORE INTO enrollments VALUES (?,?,?)',(student,course,int(time.time())))
  else:
   db.execute('DELETE FROM enrollments WHERE student=? AND course=?',(student,course))
  audit(db,student,'course_'+operation,course)
 return 200,{'ok':True,'courses':catalog(db,student)}

def start(db,student,course,lesson):
 if not isinstance(lesson,int) or isinstance(lesson,bool) or not (0<=lesson<6):return 400,{'error':'Invalid lesson'}
 if not db.execute('SELECT 1 FROM enrollments WHERE student=? AND course=?',(student,course)).fetchone():return 403,{'error':'Course enrollment required'}
 if not db.execute('SELECT 1 FROM lessons WHERE course=? AND lesson=? AND active=1',(course,lesson)).fetchone():return 403,{'error':'Lesson is unpublished or unavailable'}
 policy=attendance_rules.get(db,course)
 if not policy:return 409,{'error':'No approved attendance policy for this course and term'}
 item=db.execute('SELECT duration_seconds FROM lessons WHERE course=? AND lesson=?',(course,lesson)).fetchone()
 duration=item['duration_seconds']
 if not duration or duration<1:return 409,{'error':'Invalid lesson duration'}
 sid=secrets.token_urlsafe(24);now=time.time()
 with db:db.execute('INSERT INTO video_sessions(id,student,course,lesson,started_at,last_at,policy_json,duration_seconds) VALUES (?,?,?,?,?,?,?,?)',(sid,student,course,lesson,now,now,json.dumps(policy),duration))
 return 200,{'session_id':sid,'policy':policy,'duration_seconds':duration,'course':course,'lesson':lesson}

def heartbeat(db,student,sid,position,ended=False):
 if not isinstance(position,(float,int)) or isinstance(position,bool):return 400,{'error':'Invalid position'}
 row=db.execute('SELECT * FROM video_sessions WHERE id=? AND student=?',(sid,student)).fetchone()
 if not row:return 404,{'error':'Unknown session'}
 if row['closed']:return 409,{'error':'Session closed'}
 now=time.time();policy=json.loads(row['policy_json']) if row['policy_json'] else POLICY
 duration=row['duration_seconds'] or POLICY['video_duration_seconds'];pos=float(position)
 if pos<0 or pos>duration+.5:return 400,{'error':'Position out of range'}
 elapsed=max(0,now-row['last_at']);delta=max(0,pos-row['last_position'])
 # Seek-ahead does not earn time. Progress over the elapsed wall-clock time is bounded.
 earned=min(delta,elapsed*policy.get('max_speed',1)+policy.get('heartbeat_grace_seconds',0.5))
 # A long idle tab cannot accumulate attendance if player did not move.
 total=min(duration,row['credited_seconds']+earned)
 ratio=total/duration;eligible=total>=policy['min_watch_seconds'] and ratio>=policy['min_watch_ratio']
 with db:
  db.execute('UPDATE video_sessions SET last_at=?,last_position=?,credited_seconds=?,closed=? WHERE id=?',(now,pos,total,int(bool(ended)),sid))
  if ended and eligible and policy.get('require_ended',True):
   db.execute('INSERT OR IGNORE INTO attendance VALUES (?,?,?,?,?,?)',(student,row['course'],row['lesson'],int(now),round(ratio,3),policy.get('version','legacy-v5')))
   audit(db,student,'demo_attendance_recognized',row['course']+':'+str(row['lesson']))
 return 200,{'credited_seconds':round(total,2),'ratio':round(ratio,3),'eligible':eligible,'recognized':bool(ended and eligible),'policy_version':policy.get('version','legacy-v5'),'policy':'Pilot evidence only — subject to institution rules and human verification'}

def create_request(db,student,kind,note):
 if kind not in ('leave','return','major_change'):return 400,{'error':'Unsupported request type'}
 if not isinstance(note,str) or not (5<=len(note.strip())<=500):return 400,{'error':'Note must be 5-500 characters'}
 with db:
  cur=db.execute('INSERT INTO academic_requests(student,request_type,note,status,created_at) VALUES (?,?,?,?,?)',(student,kind,note.strip(),'pending',int(time.time())))
  audit(db,student,'academic_request',str(cur.lastrowid))
 return 201,{'request_id':cur.lastrowid,'status':'pending','official':False}
