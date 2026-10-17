"""Browser behavior against the canonical dashboard, with network calls intercepted."""
from pathlib import Path
import json
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import sync_playwright

DASH = (Path(__file__).resolve().parents[1] / "api/static/dashboard.html").as_uri()
ROOT_HTML = Path(__file__).resolve().parents[1] / "deploy/netlify/index.html"
CHROME = Path.home() / ".hermes/tools/chromium-1208/chrome-linux64/chrome"


def open_dashboard(settings=None, offers=None, auth=None):
    browser = sync_playwright().start()
    chrome = browser.chromium.launch(executable_path=str(CHROME), args=["--no-sandbox", "--disable-dev-shm-usage"])
    context = chrome.new_context()
    page = context.new_page()
    context.add_init_script("""(() => {
      const {settings,offers,auth}=__TEST_DATA__;
      window.requests=[];
      window.fetch=async (url,opts={}) => {
        let path=new URL(url,location.href).pathname;
        window.requests.push({url:String(url), method:opts.method||'GET',body:opts.body||'',authorization:opts.headers?.Authorization||''});
        let data={}, status=200;
        if(path==='/auth/v1/settings') data=settings;
        else if(path==='/auth/v1/signup') data={user:{id:'new'}};
        else if(path==='/auth/v1/user') {
          const token=(opts.headers?.Authorization||'').replace('Bearer ','');
          if(auth?.expired?.includes(token)) status=401;
          else data=auth?.users?.[token]||{id:'identity-1',email:'owner@example.test'};
        }
        else if(path==='/auth/v1/token' && new URL(url,location.href).searchParams.get('grant_type')==='refresh_token') {
          data=auth?.refresh||{}; status=auth?.refreshStatus||200;
        }
        else if(path==='/api/analytics/comparable_offers') {data=offers??{}; status=offers?.status||200;}
        else if(path==='/api/stats') data={per_chain:[],last_runs:[]};
        else if(path==='/api/movers') data={movers:[]};
        else if(path==='/api/list') data={email:'owner@example.test',items:[],chains:[]};
        else if(path==='/chains') data=[];
        else if(path==='/api/profile') data={preferred_chains:[],shopping_cadence:'',complete:false,list_item_count:0};
        return new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
      };
    })()""".replace('__TEST_DATA__', json.dumps({"settings": settings or {"disable_signup": False, "mailer_autoconfirm": True, "external": {"email": True, "google": False}}, "offers": offers, "auth": auth})))
    page.goto(DASH, wait_until="domcontentloaded")
    return browser, chrome, page


def test_email_magic_is_default_and_unsafe_providers_are_hidden():
    pw, chrome, page = open_dashboard()
    try:
        page.wait_for_function("window.requests.some(r => r.url.includes('/auth/v1/settings'))")
        assert page.locator('#form-magic').is_visible()
        assert not page.locator('#tab-signup').is_visible()
        assert not page.locator('#tab-google').is_visible()
        page.evaluate("switchAuthTab('signup')")
        assert not page.locator('#form-signup').is_visible()
        assert not page.evaluate("window.requests.some(r => r.url.includes('/auth/v1/signup'))")
    finally:
        chrome.close(); pw.stop()


def test_recovery_and_signup_use_redirect_query_not_body_options():
    pw, chrome, page = open_dashboard({"disable_signup": False, "mailer_autoconfirm": False,
                                        "external": {"email": True, "google": True}})
    try:
        page.wait_for_function("document.querySelector('#tab-signup').offsetParent !== null")
        assert page.locator('#tab-google').is_visible()
        page.locator('#tab-signup').click()
        page.locator('#signup-email').fill('new@example.test')
        page.locator('#signup-pass').fill('correct-horse')
        page.get_by_text('CREAR CUENTA', exact=True).click()
        page.wait_for_function("window.requests.some(r => r.url.includes('/auth/v1/signup'))")
        page.locator('#tab-login').click()
        page.locator('#recovery-link').click()
        page.locator('#recovery-email').fill('owner@example.test')
        page.locator('#recovery-send').click()
        page.wait_for_function("window.requests.some(r => r.url.includes('/auth/v1/recover'))")
        page.locator('#tab-magic').click()
        page.locator('#magic-email').fill('owner@example.test')
        page.get_by_text('ENVIAR ENLACE MÁGICO', exact=True).click()
        page.wait_for_function("window.requests.some(r => r.url.includes('/auth/v1/otp'))")
        reqs=page.evaluate("window.requests.filter(r => /auth\\/v1\\/(signup|recover|otp)/.test(r.url))")
        assert len(reqs)==3
        for r in reqs:
            assert 'redirect_to=' in r['url']
            redirect=parse_qs(urlparse(r['url']).query)['redirect_to'][0]
            assert parse_qs(urlparse(redirect).query)['plaza_auth_state'][0]
            assert 'options' not in json.loads(r['body'])
    finally:
        chrome.close(); pw.stop()


def test_unexpected_callback_never_switches_account_or_writes_pending():
    pw, chrome, page = open_dashboard()
    try:
        page.evaluate("""() => {
          localStorage.setItem('plaza_token','old-token');
          localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz',display_name:'Arroz'}]));
        }""")
        page.goto(DASH+'#access_token=attacker&refresh_token=attacker2&token_type=bearer', wait_until='domcontentloaded')
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("window.requests.some(r => r.url.includes('/api/list'))", timeout=3000)
        assert page.evaluate("localStorage.getItem('plaza_token')")=='old-token'
        assert page.evaluate("localStorage.getItem('plaza_pending')")
        assert not page.evaluate("window.requests.some(r => r.url.includes('/api/list/items'))")
        page.goto(DASH+'#error=access_denied&error_description=OAuth+cancelled&access_token=attacker', wait_until='domcontentloaded')
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#loginmsg').textContent.includes('expiró')",timeout=3000)
        assert page.locator('#toast').is_visible()
        assert 'expiró' in page.locator('#toast').inner_text()
        assert page.evaluate("localStorage.getItem('plaza_token')")=='old-token'
        assert not page.evaluate("window.requests.some(r => r.url.includes('/api/list/items'))")
    finally:
        chrome.close(); pw.stop()


def test_current_specials_render_coverage_dates_safe_source_and_no_forecast():
    payload={"as_of":"2026-10-17","scope":"advertised_specials_only","active_offers":5068,
             "active_chains":9,"matched_cohorts":235,"rows":[{
                "product_norm":"<img src=x onerror=alert(1)> Arroz", "brand":"Marca & Más",
                "size_canonical":"3 lb", "price_basis":"lb", "chains":[
                    {"chain_slug":"pueblo", "price_sale":3.49, "valid_from":"2026-10-16","valid_to":"2026-10-22","source_url":"https://example.test/ad", "promo":"sin raincheck <script>alert(1)</script>"},
                    {"chain_slug":"amigo", "price_sale":3.79, "valid_from":"2026-10-17","valid_to":"2026-10-23","source_url":"javascript:alert(1)"}]}]}
    pw, chrome, page = open_dashboard(offers=payload)
    try:
        page.wait_for_function("document.querySelector('#analytics-section').innerText.includes('Marca')")
        section=page.locator('#analytics-section')
        text=section.inner_text()
        for marker in ('2026-10-17','235','5068','9','Marca & Más','3 lb','lb','pueblo','amigo','2026-10-16','2026-10-23'):
            assert marker in text
        assert 'pronóstico' in text.lower() or 'predicción' in text.lower()
        assert not section.locator('img, script').count()
        assert 'sin raincheck' in text
        assert 'multicompra' in text.lower()
        assert 'heurística' in text.lower()
        assert 'no indica cobertura de cada producto' in text.lower()
        assert 'dos cadenas' not in text.lower()
        assert 'nueve cadenas' not in text.lower()
        assert '1 de 235' in section.locator('#analytics-status').inner_text()
        assert section.locator('a[href="javascript:alert(1)"]').count()==0
        assert section.locator('a[href="https://example.test/ad"]').count()==1
        assert not page.evaluate("window.requests.some(r => /basket_projections|category_comparison|analytics\\/overview/.test(r.url))")
        for word in ('Proyección de Canasta Básica', 'Supermercado Más Económico por Categoría', '2 sem', '4 sem'):
            assert word not in text
    finally:
        chrome.close(); pw.stop()


def test_correlated_callback_requires_review_before_pending_write():
    pw, chrome, page = open_dashboard()
    try:
        page.evaluate("localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz',display_name:'Arroz'}]))")
        target=page.evaluate("redirectFor('magic')")
        page.goto(target+'#access_token=accepted&refresh_token=renew&type=magiclink', wait_until='domcontentloaded')
        page.wait_for_function("localStorage.getItem('plaza_token')==='accepted'", timeout=3000)
        assert not page.evaluate("window.requests.some(r => r.url.includes('/api/list/items'))")
        review=page.locator('#pending-review')
        assert review.is_visible()
        assert 'owner@example.test' in review.inner_text()
        review.get_by_role('button',name='GUARDAR').click()
        page.wait_for_function("window.requests.some(r => r.url.includes('/api/list/items'))", timeout=3000)
        page.wait_for_function("localStorage.getItem('plaza_pending')===null", timeout=3000)
        assert page.evaluate("localStorage.getItem('plaza_pending')") is None
    finally:
        chrome.close(); pw.stop()


def test_magic_callback_in_second_tab_uses_shared_intent_once_without_writing():
    pw, chrome, sender = open_dashboard()
    try:
        sender.evaluate("localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz'}]))")
        target = sender.evaluate("redirectFor('magic')")
        receiver = sender.context.new_page()
        receiver.goto(target+'#access_token=second-tab&refresh_token=renew&type=magiclink',wait_until='domcontentloaded')
        receiver.wait_for_function("localStorage.getItem('plaza_token')==='second-tab'",timeout=3000)
        assert receiver.locator('#pending-review').is_visible()
        assert not receiver.evaluate("window.requests.some(r=>r.url.includes('/api/list/items'))")
        assert sender.evaluate("localStorage.getItem('plaza_auth_intent')") is None
        assert 'plaza_auth_state' not in receiver.url and 'access_token' not in receiver.url
    finally:
        chrome.close(); pw.stop()


def test_mismatched_callback_keeps_newer_intent_and_cannot_switch_account():
    pw, chrome, page=open_dashboard()
    try:
        first=page.evaluate("redirectFor('magic')")
        second=page.evaluate("redirectFor('magic')")
        expected=page.evaluate("localStorage.getItem('plaza_auth_intent')")
        assert first!=second
        page.goto(first+'#access_token=unmatched&refresh_token=other&type=magiclink',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#loginmsg').textContent.includes('Enlace no solicitado')",timeout=3000)
        assert page.evaluate("localStorage.getItem('plaza_token')") is None
        assert page.evaluate("localStorage.getItem('plaza_auth_intent')")==expected
    finally:
        chrome.close(); pw.stop()


def test_root_magic_forwarder_preserves_callback_state_and_fragment():
    with sync_playwright() as pw:
        chrome=pw.chromium.launch(executable_path=str(CHROME),args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            page=chrome.new_page()
            page.route('https://plaza.test/**',lambda route: route.fulfill(
                body=ROOT_HTML.read_text() if route.request.url.startswith('https://plaza.test/?') else '<html>app</html>',
                content_type='text/html'))
            page.goto('https://plaza.test/?plaza_auth_state=original-nonce&ref=email#access_token=opaque&refresh_token=other')
            page.wait_for_url('https://plaza.test/app/**')
            assert page.url == 'https://plaza.test/app/?plaza_auth_state=original-nonce&ref=email#access_token=opaque&refresh_token=other'
        finally:
            chrome.close()


def test_same_identity_callback_replaces_access_token_but_waits_for_pending_review():
    pw, chrome, page=open_dashboard()
    try:
        page.evaluate("""() => {
          localStorage.setItem('plaza_token','previous');
          localStorage.setItem('plaza_user_id','identity-1');
          localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz'}]));
        }""")
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#listview').offsetParent!==null")
        target=page.evaluate("redirectFor('magic')")
        page.goto(target+'#access_token=replaced&refresh_token=renewed&type=magiclink',wait_until='domcontentloaded')
        page.wait_for_function("localStorage.getItem('plaza_token')==='replaced'",timeout=3000)
        assert page.evaluate("localStorage.getItem('plaza_refresh')")=='renewed'
        assert page.locator('#pending-review').is_visible()
        assert not page.evaluate("window.requests.some(r=>r.url.includes('/api/list/items'))")
    finally:
        chrome.close(); pw.stop()


def test_same_identity_legacy_session_without_saved_id_accepts_verified_callback():
    pw, chrome, page=open_dashboard()
    try:
        page.evaluate("localStorage.setItem('plaza_token','legacy')")
        target=page.evaluate("redirectFor('magic')")
        page.goto(target+'#access_token=modern&refresh_token=new-refresh&type=magiclink',wait_until='domcontentloaded')
        page.wait_for_function("localStorage.getItem('plaza_token')==='modern'",timeout=3000)
        assert page.evaluate("localStorage.getItem('plaza_user_id')")=='identity-1'
    finally:
        chrome.close(); pw.stop()


def test_recovery_callback_for_same_identity_preserves_shopping_session():
    pw, chrome, page=open_dashboard()
    try:
        page.evaluate("""() => {localStorage.setItem('plaza_token','previous');
          localStorage.setItem('plaza_user_id','identity-1');}""")
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#listview').offsetParent!==null")
        target=page.evaluate("redirectFor('recovery')")
        page.goto(target+'#access_token=recover-token&refresh_token=not-shopping&type=recovery',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#form-reset').offsetParent!==null",timeout=3000)
        assert page.evaluate("localStorage.getItem('plaza_token')")=='previous'
        assert page.evaluate("AUTH.recoveryToken")=='recover-token'
        page.locator('#reset-pass').fill('new-password')
        page.get_by_role('button',name='CAMBIAR CONTRASEÑA').click()
        page.wait_for_function("window.requests.some(r=>r.url.includes('/auth/v1/user') && r.method==='PUT')",timeout=3000)
        page.wait_for_function("document.querySelector('#listview').offsetParent!==null",timeout=3000)
        assert page.evaluate("localStorage.getItem('plaza_token')")=='previous'
    finally:
        chrome.close(); pw.stop()


def test_correlated_other_identity_is_rejected_with_explicit_account_review():
    pw, chrome, page=open_dashboard(auth={'users':{'foreign':{'id':'identity-2','email':'other@example.test'}}})
    try:
        page.evaluate("""() => {localStorage.setItem('plaza_token','previous');
          localStorage.setItem('plaza_user_id','identity-1');
          localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz'}]));}""")
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#listview').offsetParent!==null")
        target=page.evaluate("redirectFor('magic')")
        page.goto(target+'#access_token=foreign&refresh_token=foreign-refresh&type=magiclink',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#toast').textContent.includes('other@example.test')",timeout=3000)
        assert 'owner@example.test' in page.locator('#toast').inner_text()
        assert page.evaluate("localStorage.getItem('plaza_token')")=='previous'
        assert page.evaluate("localStorage.getItem('plaza_pending')") is not None
        assert not page.evaluate("window.requests.some(r=>r.url.includes('/api/list/items'))")
    finally:
        chrome.close(); pw.stop()


def test_cross_device_magic_without_local_intent_requires_verified_user_confirmation():
    pw, chrome, page=open_dashboard()
    try:
        page.evaluate("localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz'}]))")
        page.goto(DASH+'?plaza_auth_state=other-device#access_token=cross-device&refresh_token=new-refresh&type=magiclink',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#auth-review')?.textContent.includes('owner@example.test')",timeout=3000)
        assert page.evaluate("localStorage.getItem('plaza_token')") is None
        assert page.evaluate("window.requests.some(r=>r.url.includes('/auth/v1/user') && r.authorization==='Bearer cross-device')")
        assert 'access_token' not in page.url and 'plaza_auth_state' not in page.url
        assert not page.evaluate("window.requests.some(r=>r.url.includes('/api/list/items'))")
        page.locator('#auth-review button').click()
        page.wait_for_function("localStorage.getItem('plaza_token')==='cross-device'",timeout=3000)
        assert page.locator('#pending-review').is_visible()
        assert not page.evaluate("window.requests.some(r=>r.url.includes('/api/list/items'))")
    finally:
        chrome.close(); pw.stop()


def test_cross_device_recovery_requires_verified_confirmation_without_shopping_login():
    pw, chrome, page=open_dashboard()
    try:
        page.evaluate("localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz'}]))")
        page.goto(DASH+'?plaza_auth_state=other-device#access_token=recover-cross&refresh_token=not-shopping&type=recovery',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#auth-review')?.textContent.includes('owner@example.test')",timeout=3000)
        assert page.evaluate("window.requests.some(r=>r.url.includes('/auth/v1/user') && r.authorization==='Bearer recover-cross')")
        assert not page.locator('#form-reset').is_visible()
        assert page.evaluate('AUTH.recoveryToken') is None
        assert page.evaluate("localStorage.getItem('plaza_token')") is None
        assert 'access_token' not in page.url and 'plaza_auth_state' not in page.url
        page.locator('#auth-review button').click()
        page.locator('#form-reset').wait_for(state='visible',timeout=3000)
        assert page.evaluate('AUTH.recoveryToken')=='recover-cross'
        assert page.evaluate("localStorage.getItem('plaza_token')") is None
        page.locator('#reset-pass').fill('new-password')
        page.get_by_role('button',name='CAMBIAR CONTRASEÑA').click()
        page.wait_for_function("window.requests.some(r=>r.url.includes('/auth/v1/user') && r.method==='PUT')",timeout=3000)
        assert page.evaluate("window.requests.find(r=>r.method==='PUT').authorization")=='Bearer recover-cross'
        assert page.evaluate("localStorage.getItem('plaza_pending')") is not None
        assert not page.evaluate("window.requests.some(r=>r.url.includes('/api/list/items'))")
    finally:
        chrome.close(); pw.stop()


def test_recovery_token_changes_password_without_becoming_shopping_session():
    pw, chrome, page = open_dashboard()
    try:
        target=page.evaluate("redirectFor('recovery')")
        page.goto(target+'#access_token=recover-token&refresh_token=not-shopping&type=recovery',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#form-reset').offsetParent!==null",timeout=3000)
        assert page.evaluate("localStorage.getItem('plaza_token')") is None
        page.locator('#reset-pass').fill('new-password')
        page.get_by_role('button',name='CAMBIAR CONTRASEÑA').click()
        page.wait_for_function("window.requests.some(r => r.url.includes('/auth/v1/user') && r.method==='PUT')",timeout=3000)
        assert page.evaluate("localStorage.getItem('plaza_token')") is None
        assert page.evaluate("window.requests.find(r => r.method==='PUT').authorization") == 'Bearer recover-token'
    finally:
        chrome.close(); pw.stop()



def test_stale_saved_identity_does_not_open_or_write_list():
    pw, chrome, page=open_dashboard()
    try:
        page.evaluate("""() => {localStorage.setItem('plaza_token','old-token');
          localStorage.setItem('plaza_user_id','different-account');
          localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz'}]));}""")
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("window.requests.some(r => r.url.includes('/auth/v1/user'))",timeout=3000)
        page.wait_for_function("localStorage.getItem('plaza_token')===null",timeout=3000)
        assert not page.evaluate("window.requests.some(r => r.url.includes('/api/list/items'))")
        assert page.evaluate("localStorage.getItem('plaza_pending')") is not None
    finally:
        chrome.close(); pw.stop()


def test_expired_saved_access_refreshes_verified_identity_without_losing_pending():
    pw, chrome, page=open_dashboard(auth={'expired':['expired-access'],
        'refresh':{'access_token':'fresh-access','refresh_token':'fresh-refresh'}})
    try:
        page.evaluate("""() => {localStorage.setItem('plaza_token','expired-access');
          localStorage.setItem('plaza_refresh','valid-refresh');
          localStorage.setItem('plaza_user_id','identity-1');
          localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz'}]));}""")
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("localStorage.getItem('plaza_token')==='fresh-access'",timeout=3000)
        page.wait_for_function("document.querySelector('#listview').offsetParent!==null",timeout=3000)
        assert page.evaluate("localStorage.getItem('plaza_refresh')")=='fresh-refresh'
        assert page.locator('#pending-review').is_visible()
        assert not page.evaluate("window.requests.some(r=>r.url.includes('/api/list/items'))")
        assert page.evaluate("window.requests.some(r=>r.url.includes('grant_type=refresh_token') && JSON.parse(r.body).refresh_token==='valid-refresh')")
    finally:
        chrome.close(); pw.stop()


def test_pending_write_401_never_retries_on_switched_account():
    pw, chrome, page = open_dashboard(auth={'users':{
        'b-token':{'id':'identity-2','email':'other@example.test'},
        'b-fresh':{'id':'identity-2','email':'other@example.test'}},
        'refresh':{'access_token':'b-fresh','refresh_token':'b-new-refresh'}})
    try:
        page.evaluate("""() => {localStorage.setItem('plaza_token','a-token');
          localStorage.setItem('plaza_refresh','a-refresh');
          localStorage.setItem('plaza_user_id','identity-1');
          localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz'}]));}""")
        page.reload(wait_until='domcontentloaded')
        page.locator('#pending-review button').wait_for()
        page.evaluate("""() => {
          const original=window.fetch;
          window.fetch=(url,opts={}) => {
            if(new URL(url,location.href).pathname==='/api/list/items'){
              window.writeCalls=(window.writeCalls||[]).concat(opts.headers.Authorization);
              if(window.writeCalls.length===1) return new Promise(resolve=>{
                window.releaseWrite=()=>resolve(new Response('{}',{status:401,headers:{'Content-Type':'application/json'}}));
              });
            }
            return original(url,opts);
          };
        }""")
        page.locator('#pending-review button').click()
        page.wait_for_function("window.releaseWrite !== undefined")
        page.evaluate("""() => {
          SESSION.token='b-token'; SESSION.refresh='b-refresh';
          SESSION.userId='identity-2'; SESSION.email='other@example.test';
          localStorage.setItem('plaza_token','b-token');
          localStorage.setItem('plaza_refresh','b-refresh');
          localStorage.setItem('plaza_user_id','identity-2');
          localStorage.setItem('plaza_email','other@example.test');
          window.releaseWrite();
        }""")
        page.wait_for_timeout(150)
        assert page.evaluate('window.writeCalls')==['Bearer a-token']
        assert page.evaluate("localStorage.getItem('plaza_pending')") is not None
        assert not page.evaluate("window.requests.some(r=>r.url.includes('grant_type=refresh_token'))")
    finally:
        chrome.close(); pw.stop()


def test_reviewed_pending_write_401_refreshes_same_account_and_clears_pending():
    pw, chrome, page=open_dashboard(auth={'refresh':{
        'access_token':'a-fresh','refresh_token':'refresh-fresh'}})
    try:
        page.evaluate("""() => {localStorage.setItem('plaza_token','a-token');
          localStorage.setItem('plaza_refresh','refresh-old');
          localStorage.setItem('plaza_user_id','identity-1');
          localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz'}]));}""")
        page.reload(wait_until='domcontentloaded')
        page.locator('#pending-review button').wait_for()
        page.evaluate("""() => {
          const original=window.fetch;
          window.writeCalls=[];
          window.fetch=(url,opts={}) => {
            if(new URL(url,location.href).pathname==='/api/list/items'){
              window.writeCalls.push(opts.headers.Authorization);
              if(window.writeCalls.length===1) return Promise.resolve(new Response('{}',{status:401}));
            }
            return original(url,opts);
          };
        }""")
        page.locator('#pending-review button').click()
        page.wait_for_function("window.writeCalls.length===2",timeout=3000)
        page.wait_for_function("localStorage.getItem('plaza_pending')===null",timeout=3000)
        assert page.evaluate('window.writeCalls')==['Bearer a-token','Bearer a-fresh']
        assert page.evaluate("localStorage.getItem('plaza_user_id')")=='identity-1'
    finally:
        chrome.close(); pw.stop()


def test_pending_success_arriving_after_account_switch_does_not_clear_pending():
    pw, chrome, page=open_dashboard()
    try:
        page.evaluate("""() => {localStorage.setItem('plaza_token','a-token');
          localStorage.setItem('plaza_user_id','identity-1');
          localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz'}]));}""")
        page.reload(wait_until='domcontentloaded')
        page.locator('#pending-review button').wait_for()
        page.evaluate("""() => {
          const original=window.fetch; window.writeCalls=[];
          window.fetch=(url,opts={}) => {
            if(new URL(url,location.href).pathname==='/api/list/items'){
              window.writeCalls.push(opts.headers.Authorization);
              return new Promise(resolve=>{
                window.releaseWrite=()=>resolve(new Response('{}',{status:200}));
              });
            }
            return original(url,opts);
          };
        }""")
        page.locator('#pending-review button').click()
        page.wait_for_function("window.releaseWrite !== undefined")
        page.evaluate("""() => {
          SESSION.token='b-token'; SESSION.userId='identity-2'; SESSION.email='other@example.test';
          localStorage.setItem('plaza_token','b-token');
          localStorage.setItem('plaza_user_id','identity-2');
          localStorage.setItem('plaza_email','other@example.test');
          window.releaseWrite();
        }""")
        page.wait_for_timeout(150)
        assert page.evaluate('window.writeCalls')==['Bearer a-token']
        assert page.evaluate("JSON.parse(localStorage.getItem('plaza_pending'))[0].product_norm")=='arroz'
    finally:
        chrome.close(); pw.stop()


def test_stale_tab_hides_review_and_preserves_other_tabs_session():
    pw, chrome, page=open_dashboard()
    try:
        page.evaluate("""() => {localStorage.setItem('plaza_token','a-token');
          localStorage.setItem('plaza_user_id','identity-1');
          localStorage.setItem('plaza_pending',JSON.stringify([{product_norm:'arroz'}]));}""")
        page.reload(wait_until='domcontentloaded')
        page.locator('#pending-review button').wait_for()
        other=page.context.new_page()
        other.goto(DASH,wait_until='domcontentloaded')
        other.evaluate("""() => {localStorage.setItem('plaza_token','b-token');
          localStorage.setItem('plaza_user_id','identity-2');
          localStorage.setItem('plaza_email','other@example.test');}""")
        page.wait_for_function("document.querySelector('#listview').classList.contains('hidden')",timeout=3000)
        assert not page.locator('#pending-review').is_visible()
        assert other.evaluate("localStorage.getItem('plaza_token')")=='b-token'
        assert page.evaluate("localStorage.getItem('plaza_pending')") is not None
        page.evaluate("flushPending({token:'a-token',id:'identity-1',email:'owner@example.test'})")
        assert not page.evaluate("window.requests.some(r=>r.url.includes('/api/list/items'))")
    finally:
        chrome.close(); pw.stop()


def test_stale_tab_logout_cannot_erase_newer_account_in_shared_storage():
    pw, chrome, page=open_dashboard()
    try:
        page.evaluate("""() => {localStorage.setItem('plaza_token','a-token');
          localStorage.setItem('plaza_user_id','identity-1');}""")
        page.reload(wait_until='domcontentloaded')
        page.locator('#listview').wait_for(state='visible')
        result=page.evaluate("""async () => {
          localStorage.setItem('plaza_token','b-token');
          localStorage.setItem('plaza_user_id','identity-2');
          localStorage.setItem('plaza_email','other@example.test');
          await logout();
          return {token:localStorage.getItem('plaza_token'),
            logoutRequests:window.requests.filter(r=>r.url.includes('/auth/v1/logout'))};
        }""")
        assert result=={'token':'b-token','logoutRequests':[]}
    finally:
        chrome.close(); pw.stop()


def test_login_identity_response_cannot_overwrite_newer_account():
    pw, chrome, page=open_dashboard()
    try:
        page.evaluate("""() => {localStorage.setItem('plaza_token','a-token');
          localStorage.setItem('plaza_user_id','identity-1');}""")
        page.reload(wait_until='domcontentloaded')
        page.locator('#listview').wait_for(state='visible')
        result=page.evaluate("""async () => {
          const original=window.fetch;
          window.fetch=(url,opts={}) => {
            if(new URL(url,location.href).pathname==='/auth/v1/user' &&
               opts.headers?.Authorization==='Bearer a-new')
              return new Promise(resolve=>{window.releaseIdentity=()=>resolve(new Response(
                JSON.stringify({id:'identity-1',email:'owner@example.test'}),{status:200}));});
            return original(url,opts);
          };
          const login=handleAuthSuccess({access_token:'a-new',refresh_token:'a-refresh'});
          localStorage.setItem('plaza_token','b-token');
          localStorage.setItem('plaza_user_id','identity-2');
          localStorage.setItem('plaza_email','other@example.test');
          window.releaseIdentity();
          try{await login;}catch(e){}
          return {token:localStorage.getItem('plaza_token'),
            writes:window.requests.filter(r=>r.url.includes('/api/list/items'))};
        }""")
        assert result=={'token':'b-token','writes':[]}
    finally:
        chrome.close(); pw.stop()


def test_load_list_keeps_verified_same_identity_response_after_token_refresh():
    pw, chrome, page=open_dashboard(auth={'refresh':{
        'access_token':'a-fresh','refresh_token':'refresh-fresh'}})
    try:
        page.evaluate("""() => {localStorage.setItem('plaza_token','a-token');
          localStorage.setItem('plaza_refresh','refresh-old');
          localStorage.setItem('plaza_user_id','identity-1');}""")
        page.reload(wait_until='domcontentloaded')
        page.locator('#listview').wait_for(state='visible')
        result=page.evaluate("""async () => {
          const original=window.fetch;
          window.listAttempts=[];
          window.fetch=(url,opts={}) => {
            if(new URL(url,location.href).pathname==='/api/list'){
              window.listAttempts.push(opts.headers.Authorization);
              const response=window.listAttempts.length===1 ?
                new Response('{}',{status:401}) :
                new Response(JSON.stringify({email:'owner@example.test',items:[
                  {item_id:7,product_norm:'arroz',display_name:'Arroz'}],chains:[]}),{status:200});
              return Promise.resolve(response);
            }
            return original(url,opts);
          };
          await loadList();
          return {attempts:window.listAttempts, items:LIST.items.map(x=>x.product_norm),
            token:SESSION.token,visible:!document.querySelector('#listview').classList.contains('hidden')};
        }""")
        assert result=={'attempts':['Bearer a-token','Bearer a-fresh'],
                        'items':['arroz'],'token':'a-fresh','visible':True}
    finally:
        chrome.close(); pw.stop()


def test_sign_out_calls_remote_logout_with_previous_token():
    pw, chrome, page=open_dashboard()
    try:
        page.evaluate("localStorage.setItem('plaza_token','signed-in-token')")
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#logoutbtn').offsetParent!==null",timeout=3000)
        page.locator('#logoutbtn').click()
        page.wait_for_function("window.requests.some(r => r.url.includes('/auth/v1/logout'))",timeout=3000)
        assert page.evaluate("localStorage.getItem('plaza_token')") is None
        assert page.evaluate("window.requests.find(r=>r.url.includes('/auth/v1/logout')).authorization") == 'Bearer signed-in-token'
    finally:
        chrome.close(); pw.stop()


@pytest.mark.parametrize('promo', ['2/$4.00', '2x1', '2 x 1', '2 por 1',
                                   'Oferta 2/$4', '2x$3'])
def test_multibuy_rows_are_withheld_even_when_api_older_than_filter(promo):
    payload={"as_of":"2026-10-17","scope":"advertised_specials_only","active_offers":2,
             "active_chains":2,"matched_cohorts":1,"rows":[{"product_norm":"Arroz","brand":"X",
             "size_canonical":"3 lb","price_basis":"lb","chains":[
               {"chain_slug":"pueblo","price_sale":2,"promo":promo,"valid_from":"2026-10-16","valid_to":"2026-10-22"},
               {"chain_slug":"amigo","price_sale":2.5,"valid_from":"2026-10-16","valid_to":"2026-10-22"}]}]}
    pw, chrome, page=open_dashboard(offers=payload)
    try:
        page.wait_for_function("document.querySelector('#analytics-status').textContent.includes('Sin ofertas')",timeout=3000)
        assert page.locator('#comparable-rows .offer-row').count()==0
        assert 'multicompra' in page.locator('#analytics-section').inner_text().lower()
    finally:
        chrome.close(); pw.stop()
def test_comparable_offers_fit_phones_and_desktop_with_long_names():
    long_name='Arroz integral marca local '+('presentación-extralarga-'*5)
    payload={"as_of":"2026-10-17","scope":"advertised_specials_only","active_offers":2,
             "active_chains":2,"matched_cohorts":1,"rows":[{"product_norm":long_name,
             "brand":"Brand-name-with-an-extended-qualification","size_canonical":"25 lb",
             "price_basis":"lb","chains":[{"chain_slug":slug,"price_sale":12.5,
               "valid_from":"2026-10-17","valid_to":"2026-10-22","source_url":"https://example.test/"}
               for slug in ('pueblo','amigo')]}]}
    pw, chrome, page=open_dashboard(offers=payload)
    try:
        page.wait_for_function("document.querySelector('#comparable-rows .offer-row')!==null",timeout=3000)
        for width in (320,375,1280):
            page.set_viewport_size({"width":width,"height":800})
            fit=page.evaluate("""() => ({viewport:innerWidth,doc:document.documentElement.scrollWidth,
                row:document.querySelector('.offer-row').getBoundingClientRect().right})""")
            assert fit['doc'] <= fit['viewport'], fit
            assert fit['row'] <= fit['viewport'], fit
    finally:
        chrome.close(); pw.stop()


@pytest.mark.parametrize('offers,expected', [({"as_of":"2026-10-17","scope":"advertised_specials_only","active_offers":0,"active_chains":0,"matched_cohorts":0,"rows":[]}, 'sin'), ({"status":503}, 'no se pudo')])
def test_analytics_empty_and_error_are_distinct_from_zero_comparisons(offers, expected):
    pw, chrome, page = open_dashboard(offers=offers)
    try:
        page.wait_for_function("document.querySelector('#analytics-status').textContent.toLowerCase().includes('"+expected+"')")
        assert expected in page.locator('#analytics-status').inner_text().lower()
        assert '0' not in page.locator('#analytics-status').inner_text() if expected=='no se pudo' else True
    finally:
        chrome.close(); pw.stop()
