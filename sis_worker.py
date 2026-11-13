"""Manual SIS outbox deliverer. In production schedule separately with restricted service identity."""
import os,sqlite3
from pathlib import Path
import sis
if __name__=='__main__':
 path=Path(os.environ['SCU_DB'])
 with sqlite3.connect(path) as db:
  db.row_factory=sqlite3.Row
  result=sis.deliver_pending(db)
  print('SIS outbox:',len(result),'attempted,',sum(x['delivered'] for x in result),'delivered')
