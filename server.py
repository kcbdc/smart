"""SMART CYBER UNIVERSITY — v5 local validation server (NOT production-ready).
Uses Python stdlib + SQLite; all identities, approvals and attendance are DEMO only.
"""
import os, json, time, sqlite3, secrets, hashlib, hmac, mimetypes, threading
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs
import academic, operations, security, sis, attendance_rules

ROOT=Path(__file__).resolve().parent
DB=Path(os.getenv('SCU_DB',ROOT/'campus_demo.sqlite3'))
SESSIONS={}
LOGIN_FAILURES={}
AUTH_LOCK=threading.Lock()
DEMO_ACCOUNTS={'student':('student','student123!'),'professor':('professor','professor123!'),'admin':('admin','admin123!')}
MAX_BODY=20000
SESSION_AGE=security.SESSION_ABSOLUTE
security.validate_config()


def db_conn():
 con=sqlite3.connect(DB,timeout=15)
 con.row_factory=sqlite3.Row
 con.execute('PRAGMA foreign_keys=ON')
 con.execute('PRAGMA busy_timeout=15000')
 return con


def setup():
 DB.parent.mkdir(parents=True,exist_ok=True)
 with db_conn() as db:
  db.execute('PRAGMA journal_mode=WAL')
  db.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY,role TEXT NOT NULL,salt TEXT NOT NULL,pw_hash TEXT NOT NULL)')
  academic.init(db)
  operations.init(db)
  security.init(db)
  sis.init(db)
  attendance_rules.init(db)
  for user,(role,password) in (DEMO_ACCOUNTS.items() if security.MODE=='demo' else []):
   if db.execute('SELECT 1 FROM users WHERE username=?',(user,)).fetchone():continue
   salt=secrets.token_hex(16)
   digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),250000).hex()
   db.execute('INSERT INTO users VALUES(?,?,?,?)',(user,role,salt,digest))


class Handler(BaseHTTPRequestHandler):
 server_version='SCU-v5-local'
 def log_message(self,*args):pass
 def headers_common(self):
  self.send_header('X-Content-Type-Options','nosniff')
  self.send_header('Referrer-Policy','no-referrer')
  self.send_header('X-Frame-Options','DENY')
  self.send_header('Cache-Control','no-store')
  self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
  if security.MODE=='production':self.send_header('Strict-Transport-Security','max-age=31536000; includeSubDomains')
  self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; media-src 'self'; img-src 'self' data:; font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
 def respond(self,status,result,cookie=None):
  raw=json.dumps(result,ensure_ascii=False).encode()
  self.send_response(status)
  self.send_header('Content-Type','application/json; charset=utf-8')
  self.send_header('Content-Length',str(len(raw)))
  self.headers_common()
  if cookie:self.send_header('Set-Cookie',cookie)
  self.end_headers();self.wfile.write(raw)
 def read_body(self):
  try:size=int(self.headers.get('Content-Length','0'))
  except ValueError:raise ValueError('Invalid length')
  if size<0 or size>MAX_BODY:raise ValueError('Invalid body length')
  raw=self.rfile.read(size)
  try:data=json.loads(raw or b'{}')
  except json.JSONDecodeError:raise ValueError('Invalid JSON')
  if not isinstance(data,dict):raise ValueError('Object required')
  return data
 def session_token(self):
  jar=SimpleCookie()
  try:jar.load(self.headers.get('Cookie',''))
  except Exception:return None
  item=jar.get('__Host-scu_session' if security.MODE=='production' else 'scu_session')
  return item.value if item else None
 def session(self):
  with db_conn() as db:return security.read_session(db,self.session_token())
 def csrf_token(self,s):
  return security.csrf_from_session(self.session_token())
 def csrf_ok(self):
  s=self.session()
  if not s:return True
  header=self.headers.get('X-CSRF-Token','')
  return bool(header and hmac.compare_digest(security.token_digest(header),s['csrf_hash']))
 def tls_ok(self):
  if security.MODE!='production':return True
  # Process is bound to 127.0.0.1 only and must run behind a secured, trusted TLS reverse proxy.
  return self.headers.get('X-Forwarded-Proto','')=='https'
 def redirect(self,url,cookie=None,status=302):
  self.send_response(status);self.send_header('Location',url)
  self.headers_common()
  if cookie:self.send_header('Set-Cookie',cookie)
  self.send_header('Content-Length','0');self.end_headers()
 def require(self,roles=None):
  s=self.session()
  if not s:self.respond(401,{'error':'Login required'});return None
  if roles and s['role'] not in roles:self.respond(403,{'error':'Permission denied'});return None
  return s
 def safe_origin(self):
  origin=self.headers.get('Origin')
  host=self.headers.get('Host','')
  return not origin or origin.rstrip('/') in ('http://'+host,'https://'+host)
 def do_GET(self):
  parsed=urlparse(self.path);path=parsed.path;args=parse_qs(parsed.query)
  if not self.tls_ok():return self.respond(403,{'error':'HTTPS required'})
  if path=='/api/health':return self.respond(200,{'status':'ok','version':'v6','mode':security.MODE})
  if path=='/auth/start':
   if security.MODE!='production':return self.respond(404,{'error':'OIDC not enabled in demo'})
   try:
    with db_conn() as db:url,state=security.begin_oidc(db)
    return self.redirect(url,f'__Host-scu_oidc={state}; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=300')
   except Exception:return self.respond(503,{'error':'Identity provider unavailable'})
  if path=='/auth/callback':
   if security.MODE!='production':return self.respond(404,{'error':'OIDC not enabled'})
   try:
    jar=SimpleCookie();jar.load(self.headers.get('Cookie',''))
    cookie_state=jar.get('__Host-scu_oidc')
    state=args.get('state',[''])[0]
    if not cookie_state or not hmac.compare_digest(cookie_state.value,state):return self.respond(401,{'error':'OIDC browser state mismatch'})
    with db_conn() as db:
     username,role,mfa=security.complete_oidc(db,state,args.get('code',[''])[0])
     token,csrf=security.add_session(db,username,role,'oidc',mfa)
    return self.redirect('/',security.secure_cookie(token))
   except Exception:return self.respond(401,{'error':'SSO verification failed or MFA assurance missing'})
  if path=='/api/me':
   s=self.session();return self.respond(200,{'user':{'username':s['username'],'role':s['role']} if s else None,'csrf_token':s and self.csrf_token(s)})
  if path=='/api/v5/dashboard':
   s=self.require(['student']);
   if not s:return
   with db_conn() as db:result=operations.summary(db,s['username'])
   return self.respond(200,result)
  if path=='/api/v5/lessons':
   s=self.require(['student']);
   if not s:return
   with db_conn() as db:result=operations.lessons(db,s['username'],args.get('course',[''])[0])
   return self.respond(200,{'lessons':result}) if result is not None else self.respond(403,{'error':'Course enrollment required'})
  if path=='/api/v5/requests':
   s=self.require(['student','admin']);
   if not s:return
   with db_conn() as db:result=operations.requests(db,s['username'] if s['role']=='student' else None)
   return self.respond(200,{'requests':result})
  if path=='/api/v5/materials':
   s=self.require();
   if not s:return
   with db_conn() as db:result=operations.material_list(db,s['role'],s['username'],args.get('course',[None])[0])
   return self.respond(200,{'materials':result})
  if path=='/api/v5/staff':
   s=self.require(['professor','admin']);
   if not s:return
   with db_conn() as db:
    courses=operations.courses(db)
    if s['role']=='professor':courses=[c for c in courses if c['teacher']==s['username']]
    rosters={c['code']:operations.course_students(db,c['teacher'],c['code']) for c in courses}
    result={'courses':courses,'rosters':rosters,'lessons':operations.staff_lessons(db,s['username']) if s['role']=='professor' else [],'requests':operations.requests(db) if s['role']=='admin' else [],'audit':[dict(x) for x in db.execute('SELECT actor,action,subject,ts FROM academic_audit ORDER BY id DESC LIMIT 40').fetchall()] if s['role']=='admin' else []}
   return self.respond(200,result)
  if path not in ('/','/index.html') and not path.startswith('/assets/'):
   self.send_error(404);return
  filepath=(ROOT / ('index.html' if path=='/' else path.lstrip('/'))).resolve()
  if not filepath.is_relative_to(ROOT) or not filepath.is_file():self.send_error(404);return
  mime=mimetypes.guess_type(filepath.name)[0] or 'application/octet-stream'
  raw=filepath.read_bytes()
  self.send_response(200);self.send_header('Content-Type',mime+('; charset=utf-8' if mime in ('text/html','text/css','application/javascript') else ''))
  self.send_header('Content-Length',str(len(raw)));self.headers_common();self.end_headers();self.wfile.write(raw)
 def do_POST(self):
  path=urlparse(self.path).path
  if not self.tls_ok():return self.respond(403,{'error':'HTTPS required'})
  if path=='/api/sis/webhook':
   try:
    n=int(self.headers.get('Content-Length','0'))
    if n<1 or n>65536:return self.respond(413,{'error':'Invalid payload length'})
    raw=self.rfile.read(n)
    with db_conn() as db:status,result=sis.inbound(db,raw,self.headers.get('X-SIS-Signature',''),self.headers.get('X-SIS-Timestamp',''))
    return self.respond(status,result)
   except Exception:return self.respond(400,{'error':'Webhook processing failed'})
  if security.MODE=='production' and path=='/api/login':return self.respond(403,{'error':'Local login disabled: use campus SSO'})
  if path not in ('/api/login',) and not self.csrf_ok():return self.respond(403,{'error':'Invalid or missing CSRF token'})
  if not self.safe_origin():return self.respond(403,{'error':'Origin rejected'})
  if self.headers.get('Content-Type','').split(';',1)[0].strip()!='application/json':return self.respond(415,{'error':'JSON required'})
  try:data=self.read_body()
  except ValueError as e:return self.respond(400,{'error':str(e)})
  if path=='/api/login':
   user=str(data.get('username',''))[:50];password=str(data.get('password',''))[:256]
   key=(self.client_address[0],user);now=time.time()
   with AUTH_LOCK:
    hits=[x for x in LOGIN_FAILURES.get(key,[]) if now-x<300]
    LOGIN_FAILURES[key]=hits
    if len(hits)>=5:return self.respond(429,{'error':'Too many failed attempts; try again later'})
   with db_conn() as db:r=db.execute('SELECT * FROM users WHERE username=?',(user,)).fetchone()
   if r:
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(r['salt']),250000).hex()
    valid=hmac.compare_digest(digest,r['pw_hash'])
   else:
    hashlib.pbkdf2_hmac('sha256',password.encode(),b'0'*16,250000)
    valid=False
   if not valid:
    with AUTH_LOCK:LOGIN_FAILURES.setdefault(key,[]).append(now)
    return self.respond(401,{'error':'Invalid credentials'})
   with db_conn() as db:token,csrf=security.add_session(db,user,r['role'],'demo',False)
   with AUTH_LOCK:LOGIN_FAILURES.pop(key,None)
   return self.respond(200,{'user':{'username':user,'role':r['role']},'csrf_token':csrf},security.secure_cookie(token))
  if path=='/api/logout':
   with db_conn() as db:security.remove_session(db,self.session_token())
   return self.respond(200,{'ok':True},security.secure_cookie('',0))
  if path=='/api/v6/policy':
   s=self.require(['admin'])
   if not s:return
   if security.MODE=='production' and not s['mfa']:return self.respond(403,{'error':'MFA required'})
   with db_conn() as db:code,result=attendance_rules.publish(db,data.get('term'),data.get('course'),data.get('version'),data.get('rule'),s['username'])
   return self.respond(code,result)
  if path.startswith('/api/v5/'):
   s=self.require();
   if not s:return
   allowed={'/api/v5/registration':'student','/api/v5/request':'student','/api/v5/video/start':'student','/api/v5/video/progress':'student','/api/v5/decision':'admin','/api/v5/material':'professor','/api/v5/lesson':'professor'}
   if path!='/api/v5/tutor' and path not in allowed:return self.respond(404,{'error':'Unknown endpoint'})
   if security.MODE=='production' and path in ('/api/v5/decision','/api/v5/material','/api/v5/lesson') and not s['mfa']:return self.respond(403,{'error':'MFA required'})
   if path in allowed and s['role']!=allowed[path]:return self.respond(403,{'error':'Permission denied'})
   with db_conn() as db:
    if path=='/api/v5/registration':
     code,result=academic.enrollment(db,s['username'],str(data.get('course','')),str(data.get('operation','')))
     if code==200:result['dashboard']=operations.summary(db,s['username'])
    elif path=='/api/v5/request':code,result=academic.create_request(db,s['username'],data.get('type'),data.get('note'))
    elif path=='/api/v5/decision':code,result=operations.approve(db,s['username'],data.get('id'),data.get('decision'),data.get('comment'))
    elif path=='/api/v5/material':code,result=operations.material_write(db,s['username'],data)
    elif path=='/api/v5/lesson':code,result=operations.lesson_write(db,s['username'],data)
    elif path=='/api/v5/video/start':code,result=academic.start(db,s['username'],str(data.get('course','')),data.get('lesson'))
    elif path=='/api/v5/video/progress':
     code,result=academic.heartbeat(db,s['username'],str(data.get('session_id','')),data.get('position'),data.get('ended') is True)
     if code==200:result['dashboard']=operations.summary(db,s['username'])
    elif path=='/api/v5/tutor':
     q=data.get('question','');course=data.get('course')
     if not isinstance(q,str) or not 2<=len(q.strip())<=500:return self.respond(400,{'error':'Question must contain 2-500 characters'})
     if course is not None and not isinstance(course,str):return self.respond(400,{'error':'Invalid course'})
     code,result=200,operations.retrieve(db,s['role'],s['username'],q,course)
    else:code,result=404,{'error':'Unknown endpoint'}
   return self.respond(code,result)
  return self.respond(404,{'error':'Not found'})

if __name__=='__main__':
 setup()
 port=int(os.getenv('PORT','8765'))
 print(f'Campus OS v6 {security.MODE} — bind 127.0.0.1:{port}; DB={DB}',flush=True)
 ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
