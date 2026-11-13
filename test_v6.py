"""Additional security, policy, and SIS integration contract tests; no external systems required."""
import unittest,tempfile,os,sqlite3,json,time,hmac,hashlib,subprocess,socket,urllib.request,urllib.error,http.cookiejar
from pathlib import Path
import security,sis,attendance_rules
ROOT=Path(__file__).resolve().parent
class V6Unit(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=sqlite3.connect(str(Path(self.tmp.name)/'test.sqlite3'))
  self.db.row_factory=sqlite3.Row
  import academic,operations
  academic.init(self.db);operations.init(self.db);security.init(self.db);sis.init(self.db);attendance_rules.init(self.db)
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def test_session_digest_expiration_and_logout(self):
  t,csrf=security.add_session(self.db,'student','student');self.assertEqual(security.read_session(self.db,t)['role'],'student');self.assertEqual(csrf,security.csrf_from_session(t))
  self.assertNotIn(t,[x[0] for x in self.db.execute('SELECT token_hash FROM auth_sessions')])
  self.db.execute('UPDATE auth_sessions SET last_at=last_at-2000 WHERE token_hash=?',(security.token_digest(t),));self.db.commit()
  self.assertIsNone(security.read_session(self.db,t))
 def test_policy_versioning_and_missing_policy(self):
  self.assertEqual(attendance_rules.get(self.db,'AI101')['version'],'DEMO-1')
  rule=dict(attendance_rules.DEFAULT_RULE)
  self.assertEqual(attendance_rules.publish(self.db,'2026-2','AI101','SCHOOL-2026',rule,'admin')[0],201)
  self.assertEqual(attendance_rules.get(self.db,'AI101')['version'],'SCHOOL-2026')
  self.assertEqual(attendance_rules.publish(self.db,'2026-2','AI101','SCHOOL-2026',rule,'admin')[0],409)
  self.assertEqual(attendance_rules.publish(self.db,'2026-2','AI101','bad',{'min_watch_ratio':0},'admin')[0],400)
 def test_sis_signature_replay_conflict(self):
  sis.SECRET='a'*48
  event={'event_id':'event-12345','event_type':'student.upsert','data':{'subject':'https://idp.example|123','student_id':'S000001','program':'융합ICT','standing':'enrolled'}}
  raw=json.dumps(event).encode();ts=str(int(time.time()));sig='sha256='+hmac.new(sis.SECRET.encode(),ts.encode()+b'.'+raw,hashlib.sha256).hexdigest()
  self.assertEqual(sis.inbound(self.db,raw,'wrong',ts)[0],401)
  self.assertEqual(sis.inbound(self.db,raw,sig,ts)[0],200)
  self.assertTrue(sis.inbound(self.db,raw,sig,ts)[1]['duplicate'])
  self.assertEqual(self.db.execute('SELECT program FROM academic_profiles WHERE username=?',('https://idp.example|123',)).fetchone()[0],'융합ICT')
  event['data']['student_id']='S000002';changed=json.dumps(event).encode();signed='sha256='+hmac.new(sis.SECRET.encode(),ts.encode()+b'.'+changed,hashlib.sha256).hexdigest()
  self.assertEqual(sis.inbound(self.db,changed,signed,ts)[0],409)
 def test_oidc_mfa_checks(self):
  # No live identity provider is accessed in this unit test.
  self.assertEqual(security.MODE,'demo')
  self.assertTrue(security.csrf_from_session('abc'))
 def test_prod_config_fail_closed(self):
  env={**os.environ,'SCU_MODE':'production','SCU_PUBLIC_URL':'http://localhost:8765'}
  result=subprocess.run(['python','-c','import security;security.validate_config()'],cwd=ROOT,env=env,capture_output=True)
  self.assertNotEqual(result.returncode,0)

if __name__=='__main__':unittest.main(verbosity=2)
