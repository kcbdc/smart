"""Campus OS security foundation: OIDC code + PKCE, server-side sessions, and CSRF.
Production mode intentionally fails closed until campus IdP and HTTPS are configured.
OIDC ID tokens are verified with remote issuer JWKS. Optional dependencies: PyJWT, requests.
"""
import os, time, secrets, hashlib, base64, json, urllib.parse, hmac

MODE=os.getenv('SCU_MODE','demo').lower()
PUBLIC_URL=os.getenv('SCU_PUBLIC_URL','').rstrip('/')
ISSUER=os.getenv('SCU_OIDC_ISSUER','').rstrip('/')
CLIENT_ID=os.getenv('SCU_OIDC_CLIENT_ID','')
CLIENT_SECRET=os.getenv('SCU_OIDC_CLIENT_SECRET','')
ROLE_CLAIM=os.getenv('SCU_OIDC_ROLE_CLAIM','campus_role')
REQUIRE_MFA=os.getenv('SCU_REQUIRE_MFA','true').lower()=='true'
SESSION_ABSOLUTE=4*3600
SESSION_IDLE=30*60
# Per-process key intentionally means restart invalidates CSRF tokens (sessions should be rotated on restart).
# For multi-instance deployments configure shared SCU_CSRF_SECRET from a secrets manager.
_CSRF_KEY=os.getenv('SCU_CSRF_SECRET','')
if MODE=='production' and len(_CSRF_KEY)<32:raise RuntimeError('SCU_CSRF_SECRET must be >=32 characters in production')
_CSRF_KEY=(_CSRF_KEY.encode() if _CSRF_KEY else secrets.token_bytes(32))

def csrf_from_session(token):
 return hmac.new(_CSRF_KEY,(token or '').encode(),hashlib.sha256).hexdigest()



def validate_config():
 if MODE not in ('demo','production'):raise RuntimeError('SCU_MODE must be demo or production')
 if MODE=='production':
  if not PUBLIC_URL.startswith('https://') or not ISSUER.startswith('https://') or not CLIENT_ID:
   raise RuntimeError('Production requires HTTPS SCU_PUBLIC_URL and HTTPS OIDC issuer/client ID')
  if os.getenv('SCU_TRUST_PROXY','')!='explicit':
   raise RuntimeError('Production requires explicit trusted TLS reverse proxy configuration')
  try:import jwt,requests
  except ImportError as ex:raise RuntimeError('Production requires PyJWT[crypto] and requests') from ex


def token_digest(token):return hashlib.sha256(token.encode()).hexdigest()
def add_session(db,user,role,method='demo',mfa=False):
 token=secrets.token_urlsafe(32);csrf=csrf_from_session(token);now=int(time.time())
 with db:
  db.execute('INSERT INTO auth_sessions(token_hash,username,role,csrf_hash,method,mfa,created_at,last_at,expires) VALUES (?,?,?,?,?,?,?,?,?)',
             (token_digest(token),user,role,token_digest(csrf),method,int(bool(mfa)),now,now,now+SESSION_ABSOLUTE))
 return token,csrf

def read_session(db,token):
 if not token:return None
 row=db.execute('SELECT * FROM auth_sessions WHERE token_hash=?',(token_digest(token),)).fetchone()
 now=int(time.time())
 if not row:return None
 if row['expires']<=now or now-row['last_at']>SESSION_IDLE:
  db.execute('DELETE FROM auth_sessions WHERE token_hash=?',(token_digest(token),));db.commit();return None
 db.execute('UPDATE auth_sessions SET last_at=? WHERE token_hash=?',(now,token_digest(token)));db.commit()
 return dict(row)

def remove_session(db,token):
 if token:
  with db:db.execute('DELETE FROM auth_sessions WHERE token_hash=?',(token_digest(token),))

def init(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY,username TEXT NOT NULL,role TEXT NOT NULL,csrf_hash TEXT NOT NULL,method TEXT NOT NULL,mfa INTEGER NOT NULL,created_at INTEGER NOT NULL,last_at INTEGER NOT NULL,expires INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS oidc_pending(state_hash TEXT PRIMARY KEY,nonce TEXT NOT NULL,code_verifier TEXT NOT NULL,expires INTEGER NOT NULL);
 CREATE INDEX IF NOT EXISTS auth_sessions_expiry ON auth_sessions(expires);
 ''')

def openid_metadata():
 import requests
 response=requests.get(ISSUER+'/.well-known/openid-configuration',timeout=7,allow_redirects=False)
 response.raise_for_status();metadata=response.json()
 if metadata.get('issuer')!=ISSUER:raise ValueError('Issuer metadata mismatch')
 for key in ('authorization_endpoint','token_endpoint','jwks_uri'):
  if not str(metadata.get(key,'')).startswith('https://'):raise ValueError('Non-HTTPS OIDC endpoint')
 return metadata

def begin_oidc(db):
 if MODE!='production':raise ValueError('OIDC requires production configuration')
 state=secrets.token_urlsafe(32);nonce=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
 challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
 with db:
  db.execute('DELETE FROM oidc_pending WHERE expires<?',(int(time.time()),))
  db.execute('INSERT INTO oidc_pending VALUES (?,?,?,?)',(token_digest(state),nonce,verifier,int(time.time())+300))
 m=openid_metadata()
 q={'response_type':'code','client_id':CLIENT_ID,'redirect_uri':PUBLIC_URL+'/auth/callback','scope':'openid profile email',
    'state':state,'nonce':nonce,'code_challenge_method':'S256','code_challenge':challenge,'prompt':'login'}
 return m['authorization_endpoint']+'?'+urllib.parse.urlencode(q),state

def complete_oidc(db,state,code):
 if not state or not code or len(state)>200 or len(code)>3000:raise ValueError('Invalid OIDC response')
 with db:
  item=db.execute('SELECT * FROM oidc_pending WHERE state_hash=?',(token_digest(state),)).fetchone()
  db.execute('DELETE FROM oidc_pending WHERE state_hash=?',(token_digest(state),))
 if not item or item['expires']<time.time():raise ValueError('State missing or expired')
 import requests,jwt
 m=openid_metadata()
 payload={'grant_type':'authorization_code','code':code,'redirect_uri':PUBLIC_URL+'/auth/callback',
          'client_id':CLIENT_ID,'code_verifier':item['code_verifier']}
 if CLIENT_SECRET:payload['client_secret']=CLIENT_SECRET
 resp=requests.post(m['token_endpoint'],data=payload,timeout=10,allow_redirects=False)
 resp.raise_for_status();tokens=resp.json()
 raw=tokens.get('id_token')
 if not raw:raise ValueError('Missing ID token')
 # PyJWKClient verifies fetched JWK signature; acceptable algorithms are explicitly pinned.
 key=jwt.PyJWKClient(m['jwks_uri'],cache_jwk_set=True,lifespan=300).get_signing_key_from_jwt(raw)
 claims=jwt.decode(raw,key.key,algorithms=['RS256','PS256','ES256'],audience=CLIENT_ID,issuer=ISSUER,options={'require':['exp','iat','iss','sub','aud']},leeway=30)
 if claims.get('nonce')!=item['nonce']:raise ValueError('OIDC nonce mismatch')
 methods=claims.get('amr',[]);methods=methods if isinstance(methods,list) else []
 acr=str(claims.get('acr',''))
 mfa=('mfa' in methods or 'otp' in methods or 'hwk' in methods or 'webauthn' in methods or acr in {x.strip() for x in os.getenv('SCU_MFA_ACR_VALUES','').split(',') if x.strip()})
 if REQUIRE_MFA and not mfa:raise PermissionError('MFA assurance not confirmed by identity provider')
 role=claims.get(ROLE_CLAIM)
 if role not in ('student','professor','admin'):raise PermissionError('Role claim not authorized')
 username=ISSUER+'|'+str(claims['sub'])
 if len(username)>250:raise ValueError('Invalid subject')
 return username,role,mfa


def secure_cookie(token,maxage=SESSION_ABSOLUTE):
 name='__Host-scu_session' if MODE=='production' else 'scu_session'
 return f'{name}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={maxage}'+('; Secure' if MODE=='production' else '')
