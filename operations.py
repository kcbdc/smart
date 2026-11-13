"""Integrated academic operations demo, sqlite-backed. All institutional records synthetic."""
import sqlite3, time, re
import sis
from academic import audit

SAMPLE_RESOURCES=[('AI101',0,'머신러닝의 기본','머신러닝은 데이터에서 패턴을 찾는 인공지능의 한 분야입니다. 지도학습은 정답이 표시된 데이터를 이용하고 비지도학습은 정답 없이 패턴을 발견합니다. 과적합을 줄이기 위해 검증 데이터와 일반화 성능을 살펴야 합니다.'),('AI101',1,'딥러닝의 이해','딥러닝은 여러 계층의 인공신경망을 이용하는 머신러닝의 한 종류입니다. 신경망은 입력과 출력의 오차를 줄이도록 가중치를 학습합니다.'),('BUS201',0,'디지털 전환 전략','디지털 전환은 기술 도입을 넘어 프로세스 재설계와 고객 경험 혁신을 포함합니다. 핵심 지표와 데이터 거버넌스를 함께 설계해야 합니다.'),('SOC110',0,'사회복지 실천 원칙','사회복지 실천은 인간의 존엄, 자기결정권, 접근성, 형평성을 중시합니다. 사례관리는 욕구 사정부터 계획, 개입, 평가 단계로 진행됩니다.')]

def init(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS terms (term_id TEXT PRIMARY KEY,name TEXT NOT NULL,status TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS sections (id TEXT PRIMARY KEY,course TEXT NOT NULL,term_id TEXT NOT NULL,teacher TEXT NOT NULL,capacity INTEGER NOT NULL DEFAULT 50);
 CREATE TABLE IF NOT EXISTS lessons (course TEXT NOT NULL,lesson INTEGER NOT NULL,title TEXT NOT NULL,duration_seconds INTEGER NOT NULL,active INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(course,lesson));
 CREATE TABLE IF NOT EXISTS materials (id INTEGER PRIMARY KEY AUTOINCREMENT,course TEXT NOT NULL,lesson INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,teacher TEXT NOT NULL,updated_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS workflow_events (id INTEGER PRIMARY KEY AUTOINCREMENT,request_id INTEGER NOT NULL,actor TEXT NOT NULL,old_status TEXT NOT NULL,new_status TEXT NOT NULL,comment TEXT NOT NULL,ts INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS academic_profiles (username TEXT PRIMARY KEY,program TEXT NOT NULL,standing TEXT NOT NULL,earned_credits INTEGER NOT NULL DEFAULT 0);
 CREATE INDEX IF NOT EXISTS ix_materials_course ON materials(course,lesson);
 CREATE INDEX IF NOT EXISTS ix_enrollments_student ON enrollments(student);
 CREATE INDEX IF NOT EXISTS ix_attendance_course ON attendance(course,student);
 ''')
 db.execute("INSERT OR IGNORE INTO terms VALUES ('2026-2','2026학년도 2학기','active')")
 db.execute("INSERT OR IGNORE INTO academic_profiles VALUES ('student','융합ICT학부','enrolled',96)")
 for code in ['AI101','BUS201','SOC110','UX301','DAT210']:
  db.execute('INSERT OR IGNORE INTO sections(id,course,term_id,teacher,capacity) VALUES (?,?,?,?,?)',(f'2026-2-{code}',code,'2026-2','professor',50))
  for n in range(6):
   db.execute('INSERT OR IGNORE INTO lessons(course,lesson,title,duration_seconds) VALUES (?,?,?,?)',(code,n,['학습 오리엔테이션','핵심 개념 이해','원리와 사례','심화 학습','실무 응용','형성평가 및 정리'][n],15))
 for code,n,title,body in SAMPLE_RESOURCES:
  if not db.execute('SELECT 1 FROM materials WHERE course=? AND lesson=? AND title=?',(code,n,title)).fetchone():
   db.execute('INSERT INTO materials(course,lesson,title,body,teacher,updated_at) VALUES (?,?,?,?,?,?)',(code,n,title,body,'professor',int(time.time())))

def courses(db,student='student'):
 rows=db.execute('''SELECT c.code,c.title,c.credits,c.teacher,s.term_id,s.capacity,
 EXISTS(SELECT 1 FROM enrollments e WHERE e.student=? AND e.course=c.code) AS enrolled,
 (SELECT COUNT(*) FROM attendance a JOIN lessons l ON l.course=a.course AND l.lesson=a.lesson AND l.active=1 WHERE a.student=? AND a.course=c.code) AS recognized,
 (SELECT COUNT(*) FROM lessons l WHERE l.course=c.code AND l.active=1) AS total_lessons
 FROM academic_courses c JOIN sections s ON s.course=c.code ORDER BY c.code''',(student,student)).fetchall()
 return [dict(x,progress=round(100*x['recognized']/x['total_lessons']) if x['total_lessons'] else 0) for x in rows]

def lessons(db,student,course):
 if not db.execute('SELECT 1 FROM enrollments WHERE student=? AND course=?',(student,course)).fetchone():return None
 rows=db.execute('''SELECT l.course,l.lesson,l.title,l.duration_seconds,
 CASE WHEN a.student IS NULL THEN 0 ELSE 1 END AS recognized,a.ratio,a.recognized_at
 FROM lessons l LEFT JOIN attendance a ON a.course=l.course AND a.lesson=l.lesson AND a.student=? WHERE l.course=? AND l.active=1 ORDER BY l.lesson''',(student,course)).fetchall()
 return [dict(r) for r in rows]

def summary(db,student):
 cs=courses(db,student);enrolled=[x for x in cs if x['enrolled']]
 pending=db.execute("SELECT COUNT(*) FROM academic_requests WHERE student=? AND status='pending'",(student,)).fetchone()[0]
 profile=db.execute('SELECT * FROM academic_profiles WHERE username=?',(student,)).fetchone()
 return {'courses':cs,'enrolled_count':len(enrolled),'average_progress':round(sum(c['progress'] for c in enrolled)/len(enrolled)) if enrolled else 0,'pending_requests':pending,'recognized_lessons':sum(c['recognized'] for c in enrolled),'profile':dict(profile) if profile else None,'source':'authoritative SQLite attendance only'}

def requests(db,student=None):
 query="""SELECT r.*,w.actor AS decided_by,w.comment AS decision_note,w.ts AS decided_at
 FROM academic_requests r LEFT JOIN workflow_events w ON w.id=(SELECT MAX(w2.id) FROM workflow_events w2 WHERE w2.request_id=r.id)"""
 if student:rows=db.execute(query+' WHERE r.student=? ORDER BY r.id DESC',(student,)).fetchall()
 else:rows=db.execute(query+' ORDER BY CASE r.status WHEN "pending" THEN 0 ELSE 1 END,r.id DESC LIMIT 100').fetchall()
 return [dict(x) for x in rows]

def approve(db,admin,request_id,decision,comment):
 if decision not in ('approved','rejected'):return 400,{'error':'Invalid decision'}
 if not isinstance(comment,str) or len(comment.strip())<3 or len(comment)>500:return 400,{'error':'Enter a reason of 3-500 characters'}
 with db:
  row=db.execute('SELECT * FROM academic_requests WHERE id=?',(request_id,)).fetchone()
  if not row:return 404,{'error':'Request not found'}
  if row['status']!='pending':return 409,{'error':'Request has already been resolved'}
  updated=db.execute("UPDATE academic_requests SET status=? WHERE id=? AND status='pending'",(decision,request_id))
  if updated.rowcount!=1:return 409,{'error':'Concurrent update'}
  db.execute('INSERT INTO workflow_events(request_id,actor,old_status,new_status,comment,ts) VALUES (?,?,?,?,?,?)',(request_id,admin,'pending',decision,comment.strip(),int(time.time())))
  # Demonstration only: approval deliberately doesn't mutate authoritative student standing.
  audit(db,admin,'workflow_'+decision,str(request_id))
  sis.queue_event(db,'academic.request.decided',{'request_id':request_id,'student':row['student'],'request_type':row['request_type'],'decision':decision,'actor':admin})
 return 200,{'ok':True,'status':decision,'request_id':request_id,'official':False}

def course_students(db,teacher,course):
 owned=db.execute('SELECT 1 FROM academic_courses WHERE code=? AND teacher=?',(course,teacher)).fetchone()
 if not owned:return None
 rows=db.execute('''SELECT e.student,COUNT(a.lesson) AS recognized,(SELECT COUNT(*) FROM lessons WHERE course=?) AS total
 FROM enrollments e LEFT JOIN attendance a ON a.student=e.student AND a.course=e.course
 WHERE e.course=? GROUP BY e.student ORDER BY e.student''',(course,course)).fetchall()
 return [dict(x,progress=round(100*x['recognized']/x['total']) if x['total'] else 0) for x in rows]

def material_list(db,role,username,course=None):
 if role=='student':
  rows=db.execute('''SELECT m.id,m.course,m.lesson,m.title,m.body,m.version,m.updated_at FROM materials m JOIN enrollments e ON e.course=m.course AND e.student=? WHERE (? IS NULL OR m.course=?) ORDER BY m.course,m.lesson,m.id''',(username,course,course)).fetchall()
 elif role=='professor':
  rows=db.execute('''SELECT m.id,m.course,m.lesson,m.title,m.body,m.version,m.updated_at FROM materials m JOIN academic_courses c ON c.code=m.course AND c.teacher=? WHERE (? IS NULL OR m.course=?) ORDER BY m.course,m.lesson,m.id''',(username,course,course)).fetchall()
 else:rows=db.execute('SELECT id,course,lesson,title,body,version,updated_at FROM materials WHERE (? IS NULL OR course=?) ORDER BY course,lesson,id',(course,course)).fetchall()
 return [dict(x) for x in rows]

def material_write(db,teacher,data):
 course=data.get('course');lesson=data.get('lesson');title=data.get('title');body=data.get('body');mid=data.get('id')
 if not isinstance(course,str) or not isinstance(lesson,int) or isinstance(lesson,bool) or not 0<=lesson<6:return 400,{'error':'Invalid course or lesson'}
 if not isinstance(title,str) or not 3<=len(title.strip())<=120 or not isinstance(body,str) or not 15<=len(body.strip())<=10000:return 400,{'error':'Title 3-120 and content 15-10000 characters required'}
 if not db.execute('SELECT 1 FROM academic_courses WHERE code=? AND teacher=?',(course,teacher)).fetchone():return 403,{'error':'Not your course'}
 if not db.execute('SELECT 1 FROM lessons WHERE course=? AND lesson=?',(course,lesson)).fetchone():return 404,{'error':'Lesson missing'}
 with db:
  if mid is not None:
   if not isinstance(mid,int):return 400,{'error':'Invalid resource ID'}
   row=db.execute('SELECT * FROM materials WHERE id=?',(mid,)).fetchone()
   if not row:return 404,{'error':'Resource not found'}
   if row['course']!=course:return 403,{'error':'Course mismatch'}
   db.execute('UPDATE materials SET lesson=?,title=?,body=?,version=version+1,updated_at=? WHERE id=?',(lesson,title.strip(),body.strip(),int(time.time()),mid));rid=mid
  else:
   cur=db.execute('INSERT INTO materials(course,lesson,title,body,teacher,updated_at) VALUES (?,?,?,?,?,?)',(course,lesson,title.strip(),body.strip(),teacher,int(time.time())));rid=cur.lastrowid
  audit(db,teacher,'material_updated',str(rid))
 return 200,{'ok':True,'id':rid}

def retrieve(db,role,user,question,course=None):
 docs=material_list(db,role,user,course)
 toks=set(re.findall(r'[가-힣]{2,}|[a-zA-Z]{2,}',question.lower()))
 synonym={'ai':'인공지능','ml':'머신러닝','deep':'딥러닝','디지털':'전환','수강':'학습','신경망':'딥러닝'}
 toks|={synonym[x] for x in toks if x in synonym}
 scored=[]
 for m in docs:
  title=m['title'].lower();body=m['body'].lower()
  score=sum((5 if t in title else 0)+(2 if t in body else 0) for t in toks)
  # No unrelated sources; access enforced by material_list.
  if score>0:scored.append((score,m))
 scored.sort(key=lambda x:(-x[0],x[1]['id']))
 hits=[m for _,m in scored[:3]]
 if not hits:return {'answer':'현재 수강 중인 강의 교안에서 충분한 근거를 찾지 못했습니다. 과목이나 핵심 개념을 구체적으로 질문해 주세요.','sources':[],'mode':'grounded-retrieval','caution':'교수자 확인 필요'}
 preview=' '.join(h['body'][:260] for h in hits[:2]);return {'answer':preview,'sources':[{'id':h['id'],'course':h['course'],'lesson':h['lesson']+1,'title':h['title'],'version':h['version'],'excerpt':h['body'][:180]} for h in hits],'mode':'grounded-retrieval','caution':'교안 발췌 기반 시연이며 생성형 답변 아님'}


def lesson_write(db,teacher,data):
 course=data.get('course');lesson=data.get('lesson');title=data.get('title');active=data.get('active')
 if not isinstance(course,str) or not isinstance(lesson,int) or isinstance(lesson,bool) or not 0<=lesson<6:return 400,{'error':'Invalid course or lesson'}
 if not isinstance(title,str) or not 3<=len(title.strip())<=120:return 400,{'error':'Lesson title must be 3-120 characters'}
 if not isinstance(active,bool):return 400,{'error':'Active must be boolean'}
 if not db.execute('SELECT 1 FROM academic_courses WHERE code=? AND teacher=?',(course,teacher)).fetchone():return 403,{'error':'Not your course'}
 with db:
  result=db.execute('UPDATE lessons SET title=?,active=? WHERE course=? AND lesson=?',(title.strip(),int(active),course,lesson))
  if not result.rowcount:return 404,{'error':'Lesson not found'}
  audit(db,teacher,'lesson_updated',course+':'+str(lesson))
 return 200,{'ok':True,'course':course,'lesson':lesson,'active':active}

def staff_lessons(db,teacher):
 return [dict(x) for x in db.execute('SELECT l.* FROM lessons l JOIN academic_courses c ON c.code=l.course WHERE c.teacher=? ORDER BY l.course,l.lesson',(teacher,)).fetchall()]
