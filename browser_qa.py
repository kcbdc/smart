"""Local Chromium smoke test: UI navigation, language, senior mode and mobile overflow."""
import os, subprocess, time, socket, urllib.request, urllib.error, tempfile, urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent
s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close()
tmp=tempfile.TemporaryDirectory()
proc=subprocess.Popen(['python','server.py'],cwd=ROOT,env={**os.environ,'PORT':str(port),'SCU_DB':str(Path(tmp.name)/'browser.sqlite3')},stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
try:
 for i in range(50):
  try:
   with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=.5) as response:
    print('HTTP health:',response.read().decode());break
  except Exception:time.sleep(.15)
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  def dispatch(route):
   request=route.request
   path=urllib.parse.urlsplit(request.url).path
   query=urllib.parse.urlsplit(request.url).query
   target=f'http://127.0.0.1:{port}'+path+('?' + query if query else '')
   headers={'Host':'campus.test'}
   for k,v in request.headers.items():
    if k.lower() in ('content-type','cookie','x-csrf-token'):headers[k]=v
   if request.method=='POST':headers['Origin']='http://campus.test'
   req=urllib.request.Request(target,data=request.post_data_buffer if request.method=='POST' else None,headers=headers,method=request.method)
   try:
    with urllib.request.urlopen(req,timeout=5) as response:
     body=response.read();status=response.status;h=dict(response.headers.items())
   except urllib.error.HTTPError as e:
    body=e.read();status=e.code;h=dict(e.headers.items())
   keep={k:v for k,v in h.items() if k.lower() in ('content-type','set-cookie','cache-control')}
   route.fulfill(status=status,headers=keep,body=body)
  for label,device in [('desktop' ,{'viewport':{'width':1440,'height':900}}),('mobile',{'viewport':{'width':390,'height':844},'is_mobile':True,'device_scale_factor':1})]:
   context=browser.new_context(**device)
   context.route('**/*',dispatch)
   page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
   page.goto('http://campus.test/',wait_until='domcontentloaded')
   page.wait_for_timeout(900)
   page.screenshot(path=str(ROOT/f'{label}_v6.png'),full_page=True)
   page.locator('#loginOpen').click();page.locator('#loginForm button[type=submit]').click();page.wait_for_timeout(800)
   page.screenshot(path=str(ROOT/f'{label}_dashboard_v6.png'),full_page=True)
   page.locator('#lang').select_option('en');page.locator('#easy').check();page.wait_for_timeout(200)
   overflow=page.evaluate('document.documentElement.scrollWidth > window.innerWidth + 3')
   print(label,'title:',page.title(),'user:',page.locator('#profileText').inner_text(),'overflow:',overflow,'pageerrors:',errors)
   assert not overflow, f'{label}: horizontal overflow'
   assert not errors, f'{label}: JS errors {errors}'
   assert page.locator('body').evaluate('(e)=>e.classList.contains("senior")')
   context.close()
  browser.close()
finally:
 proc.terminate();proc.wait(timeout=5);tmp.cleanup()
