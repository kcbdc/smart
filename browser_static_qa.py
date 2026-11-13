"""Static UI-only Chromium QA (HTTP navigation blocked by isolated test environment)."""
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parent
html=(root/'index.html').read_text();js=(root/'assets/v5.js').read_text();css=(root/'assets/v5.css').read_text()
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
 for name,width,height in [('desktop',1440,900),('mobile',390,844)]:
  c=browser.new_context(viewport={'width':width,'height':height})
  page=c.new_page();errors=[]
  page.on('pageerror',lambda error:errors.append(str(error)))
  page.add_init_script("""window.fetch=async(path,opts)=>({ok:true,status:200,json:async()=>path==='/api/health'?{status:'ok',version:'v6',mode:'demo'}:{user:null,csrf_token:null}});""")
  page.set_content(html,wait_until='domcontentloaded')
  page.add_style_tag(content=css)
  page.evaluate("Object.defineProperty(window,'localStorage',{configurable:true,value:{getItem(){return null},setItem(){},removeItem(){}}})")
  page.add_script_tag(content=js)
  page.wait_for_timeout(600)
  page.screenshot(path=str(root/f'{name}_v6_static.png'),full_page=True)
  page.locator('#lang').select_option('en')
  page.locator('#easy').check()
  page.wait_for_timeout(150)
  overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth+3')
  print(name,'title:',page.title(),'overflow:',overflow,'errors:',errors,'senior:',page.locator('body').evaluate('(el)=>el.classList.contains("senior")'))
  assert not overflow
  assert not errors
  c.close()
 browser.close()
