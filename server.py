"""Smart Cyber University demo server: stdlib-only, local development ONLY."""
import json, os, sqlite3, secrets, hashlib, hmac, time, mimetypes, urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parent
DB=Path(os.getenv('SCU_DB', ROOT/'campus_demo.sqlite3'))
SESSIONS={}
USERS={'student':'student123!','professor':'professor123!','admin':'admin123!'}
CORPUS=[
 ('인공지능의 이해 · 머신러닝','머신러닝은 학습 데이터로 패턴을 학습하는 AI 방법입니다. 지도학습은 정답이 있는 데이터에서 학습하고, 비지도학습은 숨겨진 패턴을 찾습니다.'),
 ('인공지능의 이해 · 딥러닝','딥러닝은 여러 층의 인공신경망을 사용하는 머신러닝의 하위 분야입니다. 이미지, 음성, 언어 처리에 널리 사용됩니다.'),
 ('디지털 경영전략 · 디지털 전환','디지털 전환은 기술 도입만이 아니라 고객 경험, 업무 프로세스, 데이터 활용, 조직 문화를 함께 바꾸는 전략입니다.'),
 ('사회복지개론 · 사회복지','사회복지는 개인과 공동체의 삶의 질을 높이기 위한 제도와 실천을 다루며, 복지 서비스의 접근성과 형평성을 강조합니다.'),
 ('학사 FAQ · 수강신청','시연용 동계학기 수강신청은 학사행정 메뉴에서 가능합니다. 시연용 최대 신청 학점은 9학점이며 과목당 3학점입니다.'),
 ('학사 FAQ · 증명서','학사행정의 증명서 신청에서 재학증명서, 성적증명서, 수료증명서의 미리보기를 확인할 수 있습니다. 시연 출력물은 공식 증명서가 아닙니다.'),
 ('학사 FAQ · 졸업','학사행정의 학점·졸업진단 화면에서 예시 취득학점과 잔여학점을 확인할 수 있습니다. 실제 졸업 요건은 학과별 필수학점 등을 별도로 검증해야 합니다.'),
 ('학습 안내 · 학습 계획','학습 계획은 주간 과제 마감일과 남은 학습 진도를 확인한 후, 진도가 낮은 과목부터 짧은 구간으로 나누어 복습하는 방식으로 세웁니다.'),
]
def db_conn():
 c=sqlite3.connect(DB,timeout=10);c.row_factory=sqlite3.Row;return c

def setup():
 with db_conn() as db:
  db.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, role TEXT NOT NULL, salt TEXT NOT NULL, pw_hash TEXT NOT NULL)')
  db.execute('CREATE TABLE IF NOT EXISTS student_state (username TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at INTEGER NOT NULL)')
  db.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, ts INTEGER)')
  for u,pw in USERS.items():
   if db.execute('SELECT 1 FROM users WHERE username=?',(u,)).fetchone():continue
   salt=secrets.token_hex(16);digest=hashlib.pbkdf2_hmac('sha256',pw.encode(),bytes.fromhex(salt),210000).hex()
   db.execute('INSERT INTO users VALUES(?,?,?,?)',(u,'student' if u=='student' else u,salt,digest))

def search_corpus(question):
 import re
 tokens=set(re.findall(r'[a-z]{2,}|[가-힣]{2,}|[\u4e00-\u9fff]{2,}',question.lower()))
 aliases={'ai':'인공지능','ml':'머신러닝','학점':'졸업','과제':'학습','plan':'학습','learning':'학습','machine':'머신러닝','deep':'딥러닝','graduate':'졸업','certificate':'증명서','registration':'수강신청'}
 tokens|={aliases[t] for t in list(tokens) if t in aliases}
 scores=[]
 for title,body in CORPUS:
  doc=(title+' '+body).lower();score=sum(4 if t in title.lower() else 1 for t in tokens if t in doc)
  scores.append((score,title,body))
 return sorted(scores,reverse=True)[:3]

class Handler(BaseHTTPRequestHandler):
 server_version='SCU-Demo/2.0'
 def log_message(self,*args): pass
 def json(self,code,body,cookie=None):
  payload=json.dumps(body,ensure_ascii=False).encode('utf-8');self.send_response(code)
  self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(payload)))
  self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
  if cookie:self.send_header('Set-Cookie',cookie)
  self.end_headers();self.wfile.write(payload)
 def body(self):
  size=int(self.headers.get('Content-Length','0'))
  if size>50000:raise ValueError('Request too large')
  return json.loads(self.rfile.read(size) or b'{}')
 def session(self):
  cookie=SimpleCookie()
  try:cookie.load(self.headers.get('Cookie',''))
  except:pass
  tok=cookie.get('scu_session');entry=SESSIONS.get(tok.value) if tok else None
  if entry and entry['expires']>time.time():return entry
  return None
 def require(self,roles=None):
  sess=self.session()
  if not sess:self.json(401,{'error':'Login required'});return None
  if roles and sess['role'] not in roles:self.json(403,{'error':'Permission denied'});return None
  return sess
 def do_GET(self):
  path=urlparse(self.path).path
  if path=='/api/health':return self.json(200,{'status':'ok','database':str(DB.name),'mode':'demo'})
  if path=='/api/me':
   s=self.session();return self.json(200,{'user':{'username':s['username'],'role':s['role']} if s else None})
  if path=='/api/state':
   s=self.require();
   if not s:return
   with db_conn() as db:r=db.execute('SELECT payload FROM student_state WHERE username=?',(s['username'],)).fetchone()
   return self.json(200,{'state':json.loads(r['payload']) if r else None})
  if path=='/api/stats':
   s=self.require(['professor','admin']);
   if not s:return
   with db_conn() as db:
    rows=db.execute('SELECT username,payload,updated_at FROM student_state').fetchall()
    audit=db.execute('SELECT username,action,ts FROM audit ORDER BY id DESC LIMIT 15').fetchall()
   overview=[{'username':r['username'],'completed':len(json.loads(r['payload']).get('completed',[])),'registered':len(json.loads(r['payload']).get('registered',[])),'updated_at':r['updated_at']} for r in rows]
   return self.json(200,{'learners':overview,'audit':[dict(x) for x in audit] if s['role']=='admin' else []})
  file=ROOT/('index.html' if path=='/' else path.lstrip('/'))
  if not file.resolve().is_relative_to(ROOT) or not file.is_file():self.send_error(404);return
  mime=mimetypes.guess_type(file.name)[0] or 'application/octet-stream';data=file.read_bytes()
  self.send_response(200);self.send_header('Content-Type',mime+('; charset=utf-8' if mime.startswith('text/') or mime=='application/javascript' else ''))
  self.send_header('Content-Length',str(len(data)));self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
 def do_POST(self):
  path=urlparse(self.path).path
  try:data=self.body()
  except (ValueError,json.JSONDecodeError):return self.json(400,{'error':'Invalid request'})
  if path=='/api/login':
   name=str(data.get('username',''))[:50];password=str(data.get('password',''))
   with db_conn() as db:r=db.execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
   if not r:return self.json(401,{'error':'Invalid credentials'})
   digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(r['salt']),210000).hex()
   if not hmac.compare_digest(digest,r['pw_hash']):return self.json(401,{'error':'Invalid credentials'})
   tok=secrets.token_urlsafe(32);SESSIONS[tok]={'username':name,'role':r['role'],'expires':time.time()+8*3600}
   return self.json(200,{'user':{'username':name,'role':r['role']}},f'scu_session={tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800')
  if path=='/api/logout':
   cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''))
   if cookie.get('scu_session'):SESSIONS.pop(cookie['scu_session'].value,None)
   return self.json(200,{'ok':True},'scu_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
  if path=='/api/state':
   s=self.require(['student']);
   if not s:return
   new=data.get('state')
   if not isinstance(new,dict):return self.json(400,{'error':'State must be an object'})
   allowed=('completed','registered','certs','requests','messages','lang','senior','tab','course','lesson')
   clean={k:new[k] for k in allowed if k in new}
   if not isinstance(clean.get('completed',[]),list) or not isinstance(clean.get('registered',[]),list):return self.json(400,{'error':'Invalid data'})
   if len(json.dumps(clean))>30000:return self.json(413,{'error':'State too large'})
   now=int(time.time())
   with db_conn() as db:
    db.execute('INSERT INTO student_state VALUES(?,?,?) ON CONFLICT(username) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at',(s['username'],json.dumps(clean,ensure_ascii=False),now))
    db.execute('INSERT INTO audit(username,action,ts) VALUES(?,?,?)',(s['username'],'save_state',now))
   return self.json(200,{'ok':True,'saved_at':now})
  if path=='/api/tutor':
   s=self.require();
   if not s:return
   q=str(data.get('question','')).strip()[:500]
   if not q:return self.json(400,{'error':'Question missing'})
   hits=[{'title':title,'excerpt':body} for score,title,body in search_corpus(q) if score>0][:2]
   if not hits:return self.json(200,{'answer':'제공된 교안과 학사 FAQ에서 관련 근거를 찾지 못했습니다. 질문을 구체화하거나 담당 교수에게 문의해 주세요.','sources':[],'mode':'retrieval'})
   answer='\n'.join(x['excerpt'] for x in hits)
   if os.getenv('OPENAI_API_KEY'):
    try:
     req=urllib.request.Request('https://api.openai.com/v1/responses',data=json.dumps({'model':os.getenv('SCU_AI_MODEL','gpt-4.1-mini'),'input':[{'role':'system','content':'너는 사이버대학교 학습 도우미다. 제공된 교안만 근거로 200자 이내의 한국어 답변을 한다. 근거가 없으면 모른다고 답한다. 개인정보와 공식 학사 승인에 대한 결정을 하지 않는다.'},{'role':'user','content':'근거: '+answer+'\n질문: '+q}]}).encode(),headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY'],'Content-Type':'application/json'},method='POST')
     with urllib.request.urlopen(req,timeout=12) as resp:r=json.load(resp)
     parts=[z.get('text','') for item in r.get('output',[]) for z in item.get('content',[]) if z.get('type')=='output_text']
     if parts:answer=' '.join(parts);mode='openai-rag'
     else:mode='retrieval'
    except Exception:mode='retrieval'
   else:mode='retrieval'
   return self.json(200,{'answer':answer,'sources':[{'title':x['title']} for x in hits],'mode':mode})
  return self.json(404,{'error':'Not found'})

if __name__=='__main__':
 setup();port=int(os.getenv('PORT','8765'))
 print(f'Campus demo http://127.0.0.1:{port}  DB={DB}',flush=True)
 ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
