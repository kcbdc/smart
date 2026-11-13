"""API integration tests with isolated temporary SQLite DB and local subprocess."""
import unittest, tempfile, subprocess, os, socket, time, json, urllib.request, urllib.error, http.cookiejar, sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parent
class V3Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.db=Path(cls.tmp.name)/'test.sqlite'
  sock=socket.socket();sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1];sock.close()
  cls.proc=subprocess.Popen(['python','server.py'],cwd=ROOT,env={**os.environ,'PORT':str(cls.port),'SCU_DB':str(cls.db)},stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
  for _ in range(80):
   try:
    urllib.request.urlopen(f'http://127.0.0.1:{cls.port}/api/health',timeout=.3);break
   except Exception:time.sleep(.1)
  else:raise RuntimeError('server failed')
 @classmethod
 def tearDownClass(cls):cls.proc.terminate();cls.proc.wait(timeout=5);cls.tmp.cleanup()
 def setUp(self):
  self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 def request(self,path,payload=None,origin=None):
  h={'Content-Type':'application/json'}
  if origin:h['Origin']=origin
  req=urllib.request.Request(f'http://127.0.0.1:{self.port}{path}',data=json.dumps(payload).encode() if payload is not None else None,headers=h)
  try:
   with self.opener.open(req) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:
   try:return e.code,json.loads(e.read())
   except:return e.code,{}
 def login(self,username='student',password='student123!'):
  status,_=self.request('/api/login',{'username':username,'password':password});self.assertEqual(status,200)
 def test_a_auth_and_static_protection(self):
  self.assertEqual(self.request('/api/v3/catalog')[0],401)
  self.assertEqual(self.request('/server.py')[0],404)
  self.assertEqual(self.request('/campus_demo.sqlite3')[0],404)
  self.login();self.assertEqual(self.request('/api/v3/catalog')[0],200)
  self.assertEqual(self.request('/api/v3/attendance')[0],200)
  self.assertEqual(self.request('/api/v3/enrollment',{'course':'UX301','operation':'enroll'},'https://evil.example')[0],403)
 def test_b_enrollment_credit_limit_and_roles(self):
  self.login();self.assertEqual(self.request('/api/v3/enrollment',{'course':'UX301','operation':'enroll'})[0],409)
  self.assertEqual(self.request('/api/v3/enrollment',{'course':'SOC110','operation':'drop'})[0],200)
  self.assertEqual(self.request('/api/v3/enrollment',{'course':'UX301','operation':'enroll'})[0],200)
  self.assertEqual(self.request('/api/v3/video/start',{'course':'SOC110','lesson':2})[0],403)
  self.request('/api/logout',{})
  self.login('professor','professor123!')
  self.assertEqual(self.request('/api/v3/enrollment',{'course':'AI101','operation':'drop'})[0],403)
  self.assertEqual(self.request('/api/v3/overview')[0],200)
 def test_c_attendance_cannot_complete_with_seek(self):
  self.login()
  status,d=self.request('/api/v3/video/start',{'course':'AI101','lesson':0});self.assertEqual(status,200)
  sid=d['session_id'];status,d=self.request('/api/v3/video/progress',{'session_id':sid,'position':15,'ended':True})
  self.assertEqual(status,200);self.assertFalse(d['recognized']);self.assertEqual(self.request('/api/v3/attendance')[1]['attendance'],[])
 def test_d_attendance_realtime_synthetic(self):
  self.login();status,d=self.request('/api/v3/video/start',{'course':'BUS201','lesson':1});sid=d['session_id']
  # Simulated elapsed playback time with the test database only.
  with sqlite3.connect(self.db) as db:db.execute('UPDATE video_sessions SET last_at=last_at-14 WHERE id=?',(sid,))
  status,d=self.request('/api/v3/video/progress',{'session_id':sid,'position':14,'ended':True});self.assertEqual(status,200);self.assertTrue(d['recognized'])
  self.assertTrue(any(x['course']=='BUS201' for x in self.request('/api/v3/attendance')[1]['attendance']))
  self.assertEqual(self.request('/api/v3/video/progress',{'session_id':sid,'position':15,'ended':True})[0],409)
 def test_e_pending_request_and_staff_audit(self):
  self.login();s,d=self.request('/api/v3/requests',{'type':'leave','note':'Test leave request'});self.assertEqual(s,201);self.assertEqual(d['status'],'pending')
  self.request('/api/logout',{});self.login('admin','admin123!');s,d=self.request('/api/v3/overview');self.assertEqual(s,200);self.assertGreater(len(d['audit']),0)
if __name__=='__main__':unittest.main(verbosity=2)
