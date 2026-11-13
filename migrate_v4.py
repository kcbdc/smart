"""One-time synthetic v4 -> v5 migration. Does NOT migrate user-state fake completions.
Usage: python migrate_v4.py /path/to/v4.sqlite3 /path/to/new_v5.sqlite3
Never overwrite a destination file. Use a fresh database with no other users.
"""
import sys,os,sqlite3,subprocess
from pathlib import Path
from datetime import datetime
if __name__=='__main__':
 if len(sys.argv)!=3:raise SystemExit('Usage: python migrate_v4.py SOURCE_V4_DB NEW_V5_DB')
 src=Path(sys.argv[1]).expanduser().resolve();dst=Path(sys.argv[2]).expanduser().resolve()
 if not src.is_file():raise SystemExit('Source database not found')
 if dst.exists():raise SystemExit('Destination already exists: refusing to overwrite')
 if src==dst:raise SystemExit('Source and destination must differ')
 dst.parent.mkdir(parents=True,exist_ok=True)
 # Initialize new v5 schema and salted demo credentials separately, never copy old passwords.
 from server import setup
 import server
 server.DB=dst
 setup()
 old=sqlite3.connect(src);old.row_factory=sqlite3.Row
 new=sqlite3.connect(dst);new.execute('PRAGMA foreign_keys=ON')
 def present(name):return old.execute('SELECT name FROM sqlite_master WHERE type="table" AND name=?',(name,)).fetchone() is not None
 counters={}
 try:
  with new:
   if present('enrollments'):
    new.execute('DELETE FROM enrollments')
    for r in old.execute('SELECT student,course,created_at FROM enrollments'):
     new.execute('INSERT OR IGNORE INTO enrollments(student,course,created_at) VALUES(?,?,?)',tuple(r))
    counters['enrollments']=new.execute('SELECT COUNT(*) FROM enrollments').fetchone()[0]
   if present('attendance'):
    for r in old.execute('SELECT student,course,lesson,recognized_at,ratio,rule_version FROM attendance'):
     new.execute('INSERT OR IGNORE INTO attendance VALUES(?,?,?,?,?,?)',tuple(r))
    counters['attendance']=new.execute('SELECT COUNT(*) FROM attendance').fetchone()[0]
   if present('academic_requests'):
    for r in old.execute('SELECT id,student,request_type,note,status,created_at FROM academic_requests'):
     new.execute('INSERT OR IGNORE INTO academic_requests VALUES(?,?,?,?,?,?)',tuple(r))
    counters['academic_requests']=new.execute('SELECT COUNT(*) FROM academic_requests').fetchone()[0]
   if present('academic_audit'):
    for r in old.execute('SELECT actor,action,subject,ts FROM academic_audit'):
     new.execute('INSERT INTO academic_audit(actor,action,subject,ts) VALUES(?,?,?,?)',tuple(r))
    counters['academic_audit']=new.execute('SELECT COUNT(*) FROM academic_audit').fetchone()[0]
 finally:old.close();new.close()
 print('Migrated trusted v4 database fields:',counters)
 print('Not migrated: legacy browser state, fake completed flags, active video sessions, passwords.')
 print('Use: SCU_DB='+str(dst)+' python server.py')
