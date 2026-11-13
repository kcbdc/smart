"""Versioned configurable academic policy; a policy is applied to a specific course+term.
Rules MUST be reviewed and approved against the real institution's regulations.
"""
import os,json,time

DEFAULT_RULE={'min_watch_ratio':0.8,'min_watch_seconds':12,'require_ended':True,'heartbeat_grace_seconds':0.5,'max_speed':1.0}

def init(db):
 db.executescript('''CREATE TABLE IF NOT EXISTS attendance_policies(id INTEGER PRIMARY KEY AUTOINCREMENT,term TEXT NOT NULL,course TEXT NOT NULL,version TEXT NOT NULL,rule_json TEXT NOT NULL,effective_at INTEGER NOT NULL,approved_by TEXT NOT NULL,created_at INTEGER NOT NULL,UNIQUE(term,course,version));''')
 if os.getenv('SCU_MODE','demo')=='demo':
  db.execute('INSERT OR IGNORE INTO attendance_policies(term,course,version,rule_json,effective_at,approved_by,created_at) VALUES (?,?,?,?,?,?,?)',('2026-2','*','DEMO-1',json.dumps(DEFAULT_RULE),0,'DEMO-SEED',int(time.time())))

def get(db,course,term='2026-2'):
 row=db.execute('''SELECT * FROM attendance_policies WHERE term=? AND course IN (?,'*') AND effective_at<=? ORDER BY (course=?) DESC,effective_at DESC,id DESC LIMIT 1''',(term,course,int(time.time()),course)).fetchone()
 if not row:return None
 p=json.loads(row['rule_json']);p.update({'version':row['version'],'term':row['term'],'approved_by':row['approved_by']});return p

def validate(rule):
 if not isinstance(rule,dict):raise ValueError('Policy must be object')
 if not isinstance(rule.get('min_watch_ratio'),(float,int)) or isinstance(rule['min_watch_ratio'],bool) or not 0.1<=rule['min_watch_ratio']<=1:raise ValueError('Invalid watch ratio')
 if not isinstance(rule.get('min_watch_seconds'),(int,float)) or not 0<=rule['min_watch_seconds']<=36000:raise ValueError('Invalid watch duration')
 if rule.get('require_ended') is not True:raise ValueError('Pilot requires end confirmation')
 if rule.get('max_speed')!=1.0:raise ValueError('Pilot uses 1x credit speed')
 return True

def publish(db,term,course,version,rule,approver):
 if not all(isinstance(x,str) and 1<=len(x)<=80 for x in (term,course,version)):return 400,{'error':'Invalid policy identifiers'}
 try:validate(rule)
 except ValueError as ex:return 400,{'error':str(ex)}
 if not db.execute('SELECT 1 FROM terms WHERE term_id=?',(term,)).fetchone():return 404,{'error':'Unknown term'}
 if course!='*' and not db.execute('SELECT 1 FROM academic_courses WHERE code=?',(course,)).fetchone():return 404,{'error':'Unknown course'}
 try:
  with db:db.execute('INSERT INTO attendance_policies(term,course,version,rule_json,effective_at,approved_by,created_at) VALUES (?,?,?,?,?,?,?)',(term,course,version,json.dumps(rule,sort_keys=True),int(time.time()),approver,int(time.time())))
 except Exception:return 409,{'error':'Policy version already exists'}
 return 201,{'ok':True,'version':version,'term':term,'course':course}
