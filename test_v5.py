"""End-to-end HTTP API checks on a clean, throwaway SQLite database."""
import unittest,tempfile,subprocess,os,socket,time,json,urllib.request,urllib.error,http.cookiejar,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parent
class V5Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.db=Path(cls.tmp.name)/'qa.sqlite3'
  s=socket.socket();s.bind(('127.0.0.1',0));cls.port=s.getsockname()[1];s.close()
  cls.proc=subprocess.Popen(['python','server.py'],cwd=ROOT,env={**os.environ,'PORT':str(cls.port),'SCU_DB':str(cls.db)},stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
  for _ in range(80):
   try:urllib.request.urlopen(f'http://127.0.0.1:{cls.port}/api/health',timeout=.3);break
   except Exception:time.sleep(.1)
  else:raise RuntimeError('server not starting')
 @classmethod
 def tearDownClass(cls):cls.proc.terminate();cls.proc.wait(timeout=5);cls.tmp.cleanup()
 def setUp(self):self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 def call(self,path,payload=None,origin=None):
  h={'Content-Type':'application/json'}
  if origin:h['Origin']=origin
  if payload is not None and path!='/api/login':
   with self.opener.open(f'http://127.0.0.1:{self.port}/api/me') as me:
    token=json.load(me).get('csrf_token')
   if token:h['X-CSRF-Token']=token
  req=urllib.request.Request(f'http://127.0.0.1:{self.port}{path}',data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None,headers=h)
  try:
   with self.opener.open(req,timeout=3) as resp:return resp.status,json.load(resp)
  except urllib.error.HTTPError as e:
   try:return e.code,json.loads(e.read())
   except:return e.code,{}
 def login(self,u,p):self.assertEqual(self.call('/api/login',{'username':u,'password':p})[0],200)
 def test_01_role_and_protected_resources(self):
  self.assertEqual(self.call('/api/v5/dashboard')[0],401)
  self.assertEqual(self.call('/operations.py')[0],404)
  self.assertEqual(self.call('/api/v5/materials')[0],401)
  self.login('student','student123!')
  self.assertEqual(self.call('/api/v5/dashboard')[0],200)
  self.assertEqual(self.call('/api/v5/staff')[0],403)
  self.assertEqual(self.call('/api/v5/decision',{'id':1,'decision':'approved','comment':'Demo approved'})[0],403)
  self.assertEqual(self.call('/api/v5/material',{'course':'AI101','lesson':0,'title':'student edit','body':'A student cannot edit resources'})[0],403)
  self.assertEqual(self.call('/api/v5/tutor',{'question':'머신러닝'})[0],200)
 def test_02_single_source_progress(self):
  self.login('student','student123!')
  before=self.call('/api/v5/dashboard')[1];c=next(x for x in before['courses'] if x['code']=='AI101')
  self.assertEqual(c['progress'],0)
  code,sess=self.call('/api/v5/video/start',{'course':'AI101','lesson':2});self.assertEqual(code,200)
  # Seek ahead immediately is not accepted.
  result=self.call('/api/v5/video/progress',{'session_id':sess['session_id'],'position':15,'ended':True})[1]
  self.assertFalse(result['recognized'])
  after=self.call('/api/v5/dashboard')[1];c=next(x for x in after['courses'] if x['code']=='AI101');self.assertEqual(c['progress'],0)
  code,sess=self.call('/api/v5/video/start',{'course':'AI101','lesson':3});self.assertEqual(code,200)
  # Emulate elapsed time on a disposable test DB, NOT a browser bypass.
  with sqlite3.connect(self.db) as db:db.execute('UPDATE video_sessions SET last_at=last_at-14 WHERE id=?',(sess['session_id'],))
  result=self.call('/api/v5/video/progress',{'session_id':sess['session_id'],'position':14,'ended':True})[1]
  self.assertTrue(result['recognized']);self.assertEqual(result['dashboard']['recognized_lessons'],1)
  lesson=self.call('/api/v5/lessons?course=AI101')[1]['lessons'][3];self.assertTrue(lesson['recognized'])
  c=next(x for x in self.call('/api/v5/dashboard')[1]['courses'] if x['code']=='AI101');self.assertEqual(c['progress'],17)
 def test_03_enrollment_immediately_updates_all_views(self):
  self.login('student','student123!')
  self.assertEqual(self.call('/api/v5/registration',{'course':'UX301','operation':'enroll'})[0],409)
  self.assertEqual(self.call('/api/v5/registration',{'course':'SOC110','operation':'drop'})[0],200)
  s,result=self.call('/api/v5/registration',{'course':'UX301','operation':'enroll'});self.assertEqual(s,200)
  self.assertTrue(next(c for c in result['dashboard']['courses'] if c['code']=='UX301')['enrolled'])
  self.assertEqual(self.call('/api/v5/lessons?course=SOC110')[0],403)
  self.assertEqual(self.call('/api/v5/lessons?course=UX301')[0],200)
 def test_04_request_admin_workflow_and_immutable_audit(self):
  self.login('student','student123!')
  status,r=self.call('/api/v5/request',{'type':'leave','note':'Personal academic leave request demo'});self.assertEqual(status,201)
  rid=r['request_id'];self.assertEqual(self.call('/api/v5/requests')[1]['requests'][0]['status'],'pending')
  self.call('/api/logout',{});self.login('professor','professor123!')
  self.assertEqual(self.call('/api/v5/requests')[0],403)
  self.assertEqual(self.call('/api/v5/decision',{'id':rid,'decision':'approved','comment':'Professor attempt'})[0],403)
  self.call('/api/logout',{});self.login('admin','admin123!')
  self.assertEqual(self.call('/api/v5/decision',{'id':rid,'decision':'approved','comment':'Approved for demo'})[0],200)
  self.assertEqual(self.call('/api/v5/decision',{'id':rid,'decision':'rejected','comment':'Duplicate request'})[0],409)
  self.assertEqual(next(r for r in self.call('/api/v5/requests')[1]['requests'] if r['id']==rid)['status'],'approved')
  with sqlite3.connect(self.db) as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM workflow_events WHERE request_id=?',(rid,)).fetchone()[0],1)
   self.assertEqual(db.execute('SELECT standing FROM academic_profiles WHERE username="student"').fetchone()[0],'enrolled')
 def test_05_material_version_and_enrollment_scoped_retrieval(self):
  self.login('student','student123!')
  self.assertEqual(self.call('/api/v5/tutor',{'question':'머신러닝'})[1]['sources'][0]['course'],'AI101')
  self.assertEqual(self.call('/api/v5/materials?course=UX301')[1]['materials'],[])
  self.call('/api/logout',{});self.login('professor','professor123!')
  data={'course':'AI101','lesson':0,'title':'교수자 최신 교안','body':'최신 교안에서는 학습 목표와 모델 검증을 자세히 소개합니다.'}
  status,r=self.call('/api/v5/material',data);self.assertEqual(status,200)
  mid=r['id'];data.update({'id':mid,'body':'수정 교안에서는 데이터 편향과 학습 목표를 검증합니다.'})
  self.assertEqual(self.call('/api/v5/material',data)[0],200)
  m=next(x for x in self.call('/api/v5/materials')[1]['materials'] if x['id']==mid);self.assertEqual(m['version'],2)
  self.call('/api/logout',{});self.login('student','student123!')
  result=self.call('/api/v5/tutor',{'question':'교수자 최신 교안'})[1]
  self.assertTrue(any(x['id']==mid and x['version']==2 for x in result['sources']))
  self.assertTrue(result['sources'])
 def test_06_teacher_controls_lesson_and_denies_student(self):
  self.login('student','student123!')
  payload={'course':'AI101','lesson':5,'title':'교수자가 수정한 마지막 차시','active':False}
  self.assertEqual(self.call('/api/v5/lesson',payload)[0],403)
  self.call('/api/logout',{});self.login('professor','professor123!')
  self.assertEqual(self.call('/api/v5/lesson',payload)[0],200)
  self.assertEqual(self.call('/api/v5/lesson',{**payload,'course':'BAD101'})[0],403)
  staff=self.call('/api/v5/staff')[1]
  self.assertEqual(next(x for x in staff['lessons'] if x['course']=='AI101' and x['lesson']==5)['active'],0)
  self.call('/api/logout',{});self.login('student','student123!')
  les=self.call('/api/v5/lessons?course=AI101')[1]['lessons'];self.assertEqual(len(les),5)
  self.assertEqual(self.call('/api/v5/video/start',{'course':'AI101','lesson':5})[0],403)
  c=next(x for x in self.call('/api/v5/dashboard')[1]['courses'] if x['code']=='AI101');self.assertEqual(c['total_lessons'],5)
 def test_07_legacy_attendance_security_unchanged(self):
  self.login('student','student123!')
  self.assertEqual(self.call('/api/v5/registration',{'course':'AI101','operation':'drop'},'https://evil.example')[0],403)
  self.assertEqual(self.call('/api/v5/video/start',{'course':'ZZ999','lesson':0})[0],403)
if __name__=='__main__':unittest.main(verbosity=2)
