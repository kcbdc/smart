"""SIS integration contract: versioned JSON mapping, authenticated inbound webhook, transactional outbox.
No actual campus SIS is connected unless configured with a real partner system.
"""
import os,json,hmac,hashlib,time,secrets,urllib.parse

SECRET=os.getenv('SCU_SIS_WEBHOOK_SECRET','')
OUTBOUND_URL=os.getenv('SCU_SIS_OUTBOUND_URL','')

def init(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS sis_identities(issuer_subject TEXT PRIMARY KEY,sis_student_id TEXT UNIQUE NOT NULL,updated_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS sis_inbox(event_id TEXT PRIMARY KEY,event_type TEXT NOT NULL,payload_digest TEXT NOT NULL,processed_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS sis_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,delivered_at INTEGER);
 CREATE TABLE IF NOT EXISTS sis_sync_errors(id INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT,reason TEXT NOT NULL,created_at INTEGER NOT NULL);
 ''')

def authenticate(raw,signature,timestamp):
 if not SECRET or len(SECRET)<32:return False
 try:ts=int(timestamp)
 except (ValueError,TypeError):return False
 if abs(time.time()-ts)>300:return False
 digest=hmac.new(SECRET.encode(),str(ts).encode()+b'.'+raw,hashlib.sha256).hexdigest()
 return hmac.compare_digest('sha256='+digest,signature or '')

def inbound(db,raw,signature,timestamp):
 if not authenticate(raw,signature,timestamp):return 401,{'error':'Invalid SIS signature or expired timestamp'}
 if len(raw)>65536:return 413,{'error':'Payload too large'}
 try:payload=json.loads(raw)
 except (ValueError,UnicodeError):return 400,{'error':'Invalid JSON'}
 if not isinstance(payload,dict):return 400,{'error':'Invalid payload'}
 event_id=payload.get('event_id');kind=payload.get('event_type');details=payload.get('data')
 if not isinstance(event_id,str) or not 8<=len(event_id)<=120 or kind not in ('student.upsert','student.status','enrollment.upsert') or not isinstance(details,dict):return 400,{'error':'Unsupported SIS contract'}
 subject=details.get('subject');sis_id=details.get('student_id')
 if not isinstance(subject,str) or not 3<=len(subject)<=250 or not isinstance(sis_id,str) or not 3<=len(sis_id)<=100:return 400,{'error':'Student identity mapping required'}
 if details.get('standing','enrolled') not in ('enrolled','leave','graduated','withdrawn'):return 400,{'error':'Invalid standing'}
 if kind=='enrollment.upsert':
  if details.get('course') not in {r[0] for r in db.execute('SELECT code FROM academic_courses')} or details.get('term')!='2026-2' or details.get('enrolled') not in (True,False):
   return 400,{'error':'Invalid course, term or enrolled state'}
 program=details.get('program','미지정')
 if not isinstance(program,str) or not 1<=len(program)<=120:return 400,{'error':'Invalid program'}
 digest=hashlib.sha256(raw).hexdigest();now=int(time.time())
 try:
  with db:
   prior=db.execute('SELECT payload_digest FROM sis_inbox WHERE event_id=?',(event_id,)).fetchone()
   if prior:
    if prior['payload_digest']!=digest:return 409,{'error':'Event ID collision'}
    return 200,{'ok':True,'duplicate':True}
   # No inferred identity based on supplied display name. Issuer-qualified OIDC subject only.
   db.execute('INSERT INTO sis_identities VALUES(?,?,?) ON CONFLICT(issuer_subject) DO UPDATE SET sis_student_id=excluded.sis_student_id,updated_at=excluded.updated_at',(subject,sis_id,now))
   if kind in ('student.upsert','student.status'):
    db.execute('INSERT INTO academic_profiles(username,program,standing,earned_credits) VALUES(?,?,?,0) ON CONFLICT(username) DO UPDATE SET program=excluded.program,standing=excluded.standing',(subject,program,details.get('standing','enrolled')))
   if kind=='enrollment.upsert':
    if details['enrolled']:
     db.execute('INSERT OR IGNORE INTO enrollments(student,course,created_at) VALUES(?,?,?)',(subject,details['course'],now))
    else:db.execute('DELETE FROM enrollments WHERE student=? AND course=?',(subject,details['course']))
   db.execute('INSERT INTO sis_inbox VALUES(?,?,?,?)',(event_id,kind,digest,now))
 except Exception:return 409,{'error':'SIS mapping conflict or DB failure'}
 return 200,{'ok':True,'duplicate':False,'event_id':event_id}

def queue_event(db,kind,payload):
 db.execute('INSERT INTO sis_outbox(event_type,payload,created_at) VALUES(?,?,?)',(kind,json.dumps(payload,ensure_ascii=False,sort_keys=True),int(time.time())))

def validate_outbound_config():
 if not OUTBOUND_URL.startswith('https://'):raise ValueError('SIS endpoint must use HTTPS')
 u=urllib.parse.urlparse(OUTBOUND_URL)
 if not u.hostname or u.username or u.password or u.fragment:raise ValueError('Invalid SIS endpoint')
 if len(SECRET)<32:raise ValueError('SIS signing secret not configured')

def deliver_pending(db,limit=30):
 """Explicitly run by operator/worker; fixed HTTPS endpoint, no user-controlled URL."""
 import requests
 validate_outbound_config();results=[]
 rows=db.execute("SELECT id,event_type,payload FROM sis_outbox WHERE status='pending' ORDER BY id LIMIT ?",(limit,)).fetchall()
 for r in rows:
  body=json.dumps({'event_id':'scu-'+str(r['id']),'event_type':r['event_type'],'data':json.loads(r['payload'])},ensure_ascii=False).encode()
  ts=str(int(time.time()));signature='sha256='+hmac.new(SECRET.encode(),ts.encode()+b'.'+body,hashlib.sha256).hexdigest()
  try:
   response=requests.post(OUTBOUND_URL,data=body,headers={'Content-Type':'application/json','X-SIS-Timestamp':ts,'X-SIS-Signature':signature},timeout=8,allow_redirects=False)
   success=200<=response.status_code<300
  except requests.RequestException:success=False
  with db:
   db.execute('UPDATE sis_outbox SET attempts=attempts+1,status=?,delivered_at=? WHERE id=?',('delivered' if success else 'pending',int(time.time()) if success else None,r['id']))
  results.append({'id':r['id'],'delivered':success})
 return results
