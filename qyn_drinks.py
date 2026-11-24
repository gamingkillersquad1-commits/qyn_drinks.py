"""
QYN DRINKS - complete website + order backend + admin panel + Gmail alerts. ONE FILE.

SETUP (once):
    pip install flask

GMAIL SETUP (so new orders land in your Gmail):
    1. Google Account > Security > turn on 2-Step Verification
    2. Google Account > Security > App passwords > create one named "Qyn"
    3. Set these before running (Windows: use `set` instead of `export`):
         export QYN_GMAIL="nandikondaaparna@gmail.com"
         export QYN_APP_PASSWORD="sakshithxqyn"
         export QYN_ADMIN_PASSWORD="sakshithxqyn"
         export QYN_SECRET="any-long-random-text"

RUN:
    python qyn_drinks.py
    Shop:  http://localhost:5000
    Admin: http://localhost:5000/admin
"""
import os, json, sqlite3, smtplib, threading, secrets
from email.message import EmailMessage
from functools import wraps
from flask import Flask, request, jsonify, session

GMAIL = os.environ.get("QYN_GMAIL", "")
APP_PW = os.environ.get("QYN_APP_PASSWORD", "")
ADMIN_PW = os.environ.get("QYN_ADMIN_PASSWORD", "change-me")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qyn.db")

app = Flask(__name__)
app.secret_key = os.environ.get("QYN_SECRET", secrets.token_hex(16))

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def init():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS flavours(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, descr TEXT,
        price REAL, color TEXT, emoji TEXT, active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT,
        email TEXT, address TEXT, note TEXT, items TEXT, total REAL, status TEXT DEFAULT 'New',
        created TEXT DEFAULT CURRENT_TIMESTAMP);""")
    defaults = {"brand": "Qyn Drinks", "tagline": "Six flavours. One cold sip.",
        "hero_sub": "Small-batch fruit drinks, chilled and delivered to your door.",
        "currency": "₹", "contact": "+91 00000 00000", "notify_email": GMAIL, "accepting": "1"}
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v))
    if not c.execute("SELECT 1 FROM flavours").fetchone():
        seed = [("Mango Blaze", "Ripe alphonso mango with a hint of chilli.", 60, "#ffb703", "🥭"),
                ("Berry Burst", "Wild strawberry and blueberry, tart and sweet.", 70, "#e63978", "🫐"),
                ("Lime Mint", "Sharp lime, fresh mint, over crushed ice.", 50, "#2ec4b6", "🍋"),
                ("Passion Pulse", "Tropical passion fruit with a bright finish.", 75, "#ff7b00", "🍹"),
                ("Watermelon Wave", "Juicy watermelon with a splash of rose.", 55, "#ff4d6d", "🍉"),
                ("Coconut Dream", "Creamy tender coconut and a touch of vanilla.", 65, "#9d8cff", "🥥")]
        c.executemany("INSERT INTO flavours(name,descr,price,color,emoji) VALUES(?,?,?,?,?)", seed)
    c.commit(); c.close()

def settings():
    c = db(); r = {x["k"]: x["v"] for x in c.execute("SELECT * FROM settings")}; c.close(); return r

def send_mail(to, subject, body):
    if not (GMAIL and APP_PW and to): print("[mail skipped - Gmail not configured]\n", subject); return
    def go():
        try:
            m = EmailMessage(); m["From"] = GMAIL; m["To"] = to; m["Subject"] = subject; m.set_content(body)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                s.login(GMAIL, APP_PW.replace(" ", "")); s.send_message(m)
        except Exception as e: print("[mail error]", e)
    threading.Thread(target=go, daemon=True).start()

def admin_only(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"): return jsonify(error="Login required"), 401
        return f(*a, **k)
    return w

# ---------- public API ----------
@app.get("/api/public")
def public():
    c = db(); fl = [dict(r) for r in c.execute("SELECT * FROM flavours WHERE active=1 ORDER BY id")]; c.close()
    return jsonify(settings=settings(), flavours=fl)

@app.post("/api/order")
def order():
    d = request.get_json(force=True); s = settings()
    if s.get("accepting") != "1": return jsonify(error="Orders are paused right now."), 400
    name, phone, addr = (d.get("name") or "").strip(), (d.get("phone") or "").strip(), (d.get("address") or "").strip()
    if not (name and phone and addr): return jsonify(error="Name, phone and address are required."), 400
    c = db(); items, total = [], 0
    for fid, q in (d.get("items") or {}).items():
        try: q = int(q)
        except: continue
        r = c.execute("SELECT * FROM flavours WHERE id=? AND active=1", (fid,)).fetchone()
        if r and 0 < q <= 100: items.append({"name": r["name"], "qty": q, "price": r["price"]}); total += q * r["price"]
    if not items: c.close(); return jsonify(error="Your cart is empty."), 400
    cur = c.execute("INSERT INTO orders(name,phone,email,address,note,items,total) VALUES(?,?,?,?,?,?,?)",
        (name, phone, (d.get("email") or "").strip(), addr, (d.get("note") or "").strip()[:500], json.dumps(items), total))
    oid = cur.lastrowid; c.commit(); c.close()
    lines = "\n".join(f"  {i['qty']} x {i['name']}  ({s['currency']}{i['price']*i['qty']:g})" for i in items)
    send_mail(s.get("notify_email") or GMAIL, f"New Qyn order #{oid} - {s['currency']}{total:g}",
        f"New order #{oid}\n\nName: {name}\nPhone: {phone}\nEmail: {d.get('email','')}\nAddress: {addr}\nNote: {d.get('note','')}\n\n{lines}\n\nTotal: {s['currency']}{total:g}")
    if d.get("email"):
        send_mail(d["email"], f"Your {s['brand']} order #{oid}",
            f"Hi {name},\n\nThanks for your order!\n\n{lines}\n\nTotal: {s['currency']}{total:g}\n\nWe will contact you on {phone} shortly.\n- {s['brand']}")
    return jsonify(ok=True, id=oid)

# ---------- admin API ----------
@app.post("/api/admin/login")
def login():
    if secrets.compare_digest((request.get_json(force=True).get("password") or ""), ADMIN_PW):
        session["admin"] = True; return jsonify(ok=True)
    return jsonify(error="Wrong password"), 401

@app.post("/api/admin/logout")
def logout(): session.clear(); return jsonify(ok=True)

@app.get("/api/admin/orders")
@admin_only
def orders():
    c = db(); r = [dict(x) for x in c.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 300")]; c.close()
    for o in r: o["items"] = json.loads(o["items"])
    return jsonify(r)

@app.post("/api/admin/orders/<int:oid>")
@admin_only
def order_status(oid):
    st = request.get_json(force=True).get("status", "New")
    c = db(); c.execute("UPDATE orders SET status=? WHERE id=?", (st, oid)); c.commit(); c.close(); return jsonify(ok=True)

@app.get("/api/admin/flavours")
@admin_only
def all_flavours():
    c = db(); r = [dict(x) for x in c.execute("SELECT * FROM flavours ORDER BY id")]; c.close(); return jsonify(r)

@app.post("/api/admin/flavours")
@admin_only
def save_flavour():
    d = request.get_json(force=True); c = db()
    v = (d["name"], d["descr"], float(d["price"]), d["color"], d["emoji"], 1 if d.get("active") else 0)
    if d.get("id"): c.execute("UPDATE flavours SET name=?,descr=?,price=?,color=?,emoji=?,active=? WHERE id=?", v + (d["id"],))
    else: c.execute("INSERT INTO flavours(name,descr,price,color,emoji,active) VALUES(?,?,?,?,?,?)", v)
    c.commit(); c.close(); return jsonify(ok=True)

@app.delete("/api/admin/flavours/<int:fid>")
@admin_only
def del_flavour(fid):
    c = db(); c.execute("DELETE FROM flavours WHERE id=?", (fid,)); c.commit(); c.close(); return jsonify(ok=True)

@app.route("/api/admin/settings", methods=["GET", "POST"])
@admin_only
def admin_settings():
    if request.method == "POST":
        c = db()
        for k, v in request.get_json(force=True).items(): c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, str(v)))
        c.commit(); c.close()
    return jsonify(settings())

@app.post("/api/admin/test-mail")
@admin_only
def test_mail():
    send_mail(settings().get("notify_email") or GMAIL, "Qyn Drinks test email", "Gmail notifications are working."); return jsonify(ok=True)

# ---------- storefront ----------
SHOP = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qyn Drinks</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,800&family=Nunito:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{--ink:#1d1030;--paper:#fff8f0;--accent:#ff4d6d}
*{box-sizing:border-box;margin:0}
body{font-family:Nunito,system-ui,sans-serif;color:#fff;min-height:100vh;background:linear-gradient(135deg,#2b0a4d,#7a1f5c 45%,#ff6b4a 80%,#ffb703);background-size:300% 300%;animation:bg 22s ease infinite;overflow-x:hidden}
@keyframes bg{50%{background-position:100% 100%}}
.blob{position:fixed;border-radius:50%;filter:blur(70px);opacity:.45;z-index:-1;animation:fl 18s ease-in-out infinite alternate}
@keyframes fl{to{transform:translate(60px,-80px) scale(1.2)}}
@media(prefers-reduced-motion:reduce){body,.blob{animation:none}}
header{display:flex;justify-content:space-between;align-items:center;padding:20px 5vw}
.logo{font:800 1.7rem Fraunces,serif;letter-spacing:.5px}
.cartbtn{background:#fff;color:var(--ink);border:0;border-radius:99px;padding:10px 20px;font:700 1rem Nunito;cursor:pointer}
.hero{text-align:center;padding:9vh 5vw 6vh}
.hero h1{font:800 clamp(2.6rem,8vw,6rem)/1 Fraunces,serif;text-wrap:balance}
.hero p{max-width:34em;margin:20px auto 0;font-size:1.2rem;opacity:.92}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:24px;padding:20px 5vw 60px;max-width:1200px;margin:auto}
.card{background:rgba(255,255,255,.14);backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.3);border-radius:28px;padding:26px;transition:transform .25s}
.card:hover{transform:translateY(-6px)}
.bottle{height:120px;border-radius:20px;display:grid;place-items:center;font-size:4rem;margin-bottom:16px}
.card h3{font:800 1.5rem Fraunces,serif}.card p{opacity:.9;margin:8px 0 14px;min-height:3em}
.row{display:flex;justify-content:space-between;align-items:center}
.price{font-weight:800;font-size:1.3rem}
.qty{display:flex;align-items:center;gap:10px}
.qty button{width:34px;height:34px;border-radius:50%;border:0;background:#fff;color:var(--ink);font-size:1.2rem;font-weight:800;cursor:pointer}
.panel{position:fixed;right:0;top:0;height:100%;width:min(420px,100%);background:var(--paper);color:var(--ink);padding:26px;transform:translateX(105%);transition:transform .3s;overflow:auto;z-index:9}
.panel.open{transform:none}
.panel h2{font:800 1.8rem Fraunces,serif;margin-bottom:12px}
.panel input,.panel textarea{width:100%;padding:12px;border:2px solid #e8d9c8;border-radius:12px;margin:5px 0;font:inherit}
.panel input:focus,.panel textarea:focus,button:focus-visible{outline:3px solid var(--accent)}
.go{width:100%;margin-top:10px;padding:14px;border:0;border-radius:14px;background:var(--accent);color:#fff;font:800 1.1rem Nunito;cursor:pointer}
.line{display:flex;justify-content:space-between;padding:6px 0}
.msg{margin-top:10px;font-weight:700}
footer{text-align:center;padding:30px;opacity:.8}
</style></head><body>
<div class="blob" style="width:420px;height:420px;background:#ffb703;top:-100px;left:-100px"></div>
<div class="blob" style="width:380px;height:380px;background:#2ec4b6;bottom:-80px;right:-60px;animation-delay:-6s"></div>
<header><div class="logo" id="brand"></div><button class="cartbtn" onclick="tog()">Cart (<span id="cnt">0</span>)</button></header>
<section class="hero"><h1 id="tag"></h1><p id="sub"></p></section>
<main class="grid" id="grid"></main>
<footer id="foot"></footer>
<aside class="panel" id="panel"><h2>Your order</h2><div id="lines"></div>
<div class="line"><b>Total</b><b id="tot"></b></div><hr style="margin:12px 0;border:1px solid #e8d9c8">
<input id="n" placeholder="Your name" autocomplete="name"><input id="p" placeholder="Phone number" autocomplete="tel">
<input id="e" placeholder="Email (for confirmation, optional)" autocomplete="email"><textarea id="a" rows="2" placeholder="Delivery address"></textarea>
<textarea id="o" rows="2" placeholder="Note (optional)"></textarea>
<button class="go" onclick="place()">Place order</button><div class="msg" id="msg"></div>
<button class="cartbtn" style="margin-top:14px;background:#eee" onclick="tog()">Close</button></aside>
<script>
let D,cart={};const $=i=>document.getElementById(i);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function load(){D=await(await fetch('/api/public')).json();const s=D.settings;
document.title=s.brand;$('brand').textContent=s.brand;$('tag').textContent=s.tagline;$('sub').textContent=s.hero_sub;
$('foot').textContent=s.brand+' · Call or WhatsApp '+s.contact;
$('grid').innerHTML=D.flavours.map(f=>`<div class="card"><div class="bottle" style="background:linear-gradient(160deg,${esc(f.color)},${esc(f.color)}88)">${esc(f.emoji)}</div>
<h3>${esc(f.name)}</h3><p>${esc(f.descr)}</p><div class="row"><span class="price">${esc(s.currency)}${f.price}</span>
<div class="qty"><button onclick="ch(${f.id},-1)" aria-label="Remove one">−</button><b id="q${f.id}">0</b><button onclick="ch(${f.id},1)" aria-label="Add one">+</button></div></div></div>`).join('');draw()}
function ch(id,d){cart[id]=Math.max(0,(cart[id]||0)+d);draw()}
function draw(){let t=0,n=0,h='';const c=D.settings.currency;
D.flavours.forEach(f=>{const q=cart[f.id]||0;if($('q'+f.id))$('q'+f.id).textContent=q;if(q){t+=q*f.price;n+=q;h+=`<div class="line"><span>${q} × ${esc(f.name)}</span><span>${esc(c)}${q*f.price}</span></div>`}});
$('lines').innerHTML=h||'<p>Add a flavour to start your order.</p>';$('tot').textContent=c+t;$('cnt').textContent=n}
function tog(){$('panel').classList.toggle('open')}
async function place(){const m=$('msg');m.textContent='Sending…';
const r=await fetch('/api/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('n').value,phone:$('p').value,email:$('e').value,address:$('a').value,note:$('o').value,items:cart})});
const j=await r.json();if(j.ok){m.textContent='Order #'+j.id+' placed. We will call you soon!';cart={};draw()}else m.textContent=j.error}
load();
</script></body></html>"""

# ---------- admin panel ----------
ADMIN = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qyn Admin</title><style>
*{box-sizing:border-box}body{font-family:system-ui,sans-serif;margin:0;background:#f4f0f8;color:#1d1030}
header{background:#2b0a4d;color:#fff;padding:14px 20px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
nav button,.b{border:0;border-radius:8px;padding:9px 16px;font:600 .95rem system-ui;cursor:pointer;background:#e4d9f2;color:#2b0a4d}
nav button.on,.b.p{background:#ff4d6d;color:#fff}.b.d{background:#b00020;color:#fff}
main{max-width:1000px;margin:20px auto;padding:0 14px}
.box{background:#fff;border-radius:14px;padding:16px;margin-bottom:14px;box-shadow:0 2px 8px #0001}
input,select,textarea{padding:9px;border:1.5px solid #cdbfe0;border-radius:8px;font:inherit;width:100%}
input[type=color]{padding:2px;height:40px}label{font-size:.85rem;font-weight:600;display:block;margin-top:8px}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;align-items:end}
.hide{display:none}.tag{padding:3px 10px;border-radius:99px;background:#ffe1e6;font-weight:700;font-size:.8rem}
#login{max-width:340px;margin:12vh auto}
</style></head><body>
<div id="login" class="box"><h2>Qyn admin</h2><input id="pw" type="password" placeholder="Admin password"><br><br>
<button class="b p" onclick="login()">Sign in</button><p id="le" style="color:#b00020"></p></div>
<div id="app" class="hide"><header><b>Qyn Drinks admin</b><nav><button id="t-o" onclick="tab('o')">Orders</button> <button id="t-f" onclick="tab('f')">Flavours</button> <button id="t-s" onclick="tab('s')">Website settings</button> <button onclick="out()">Log out</button></nav></header>
<main><div id="o"></div><div id="f" class="hide"></div><div id="s" class="hide"></div></main></div>
<script>
const $=i=>document.getElementById(i);let known=0,first=true;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api=async(u,m='GET',b)=>{const r=await fetch(u,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});if(r.status==401){location.reload();return}return r.json()};
async function login(){const r=await fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:$('pw').value})});
if(r.ok){$('login').classList.add('hide');$('app').classList.remove('hide');tab('o');setInterval(orders,15000)}else $('le').textContent='Wrong password'}
async function out(){await api('/api/admin/logout','POST');location.reload()}
function tab(t){['o','f','s'].forEach(x=>{$(x).classList.toggle('hide',x!=t);$('t-'+x).classList.toggle('on',x==t)});({o:orders,f:flavs,s:sets})[t]()}
async function orders(){const L=await api('/api/admin/orders');if(!L)return;
if(!first&&L.length&&L[0].id>known){try{new AudioContext().resume();const a=new AudioContext(),o=a.createOscillator();o.connect(a.destination);o.start();setTimeout(()=>o.stop(),300)}catch(e){}document.title='New order!'}
if(L.length)known=Math.max(known,L[0].id);first=false;
$('o').innerHTML=L.length?L.map(o=>`<div class="box"><div style="display:flex;justify-content:space-between"><b>#${o.id} · ${esc(o.name)}</b><span class="tag">${esc(o.status)}</span></div>
<p>${o.items.map(i=>i.qty+' × '+esc(i.name)).join(', ')} — <b>${o.total}</b></p><p>📞 ${esc(o.phone)} ${o.email?'· ✉️ '+esc(o.email):''}<br>📍 ${esc(o.address)}<br>${o.note?'📝 '+esc(o.note)+'<br>':''}<small>${esc(o.created)} UTC</small></p>
<select onchange="st(${o.id},this.value)">${['New','Preparing','Out for delivery','Delivered','Cancelled'].map(s=>`<option ${s==o.status?'selected':''}>${s}</option>`).join('')}</select></div>`).join(''):'<div class="box">No orders yet. New orders appear here automatically.</div>'}
async function st(id,s){await api('/api/admin/orders/'+id,'POST',{status:s});orders()}
async function flavs(){const L=await api('/api/admin/flavours');$('f').innerHTML='<button class="b p" onclick="addf()">+ Add flavour</button><br><br>'+L.map(f=>row(f)).join('')}
function row(f){return `<div class="box g" data-id="${f.id||''}"><div><label>Name</label><input class="n" value="${esc(f.name)}"></div><div><label>Emoji</label><input class="e" value="${esc(f.emoji)}"></div>
<div><label>Price</label><input class="p" type="number" value="${f.price}"></div><div><label>Colour</label><input class="c" type="color" value="${esc(f.color)}"></div>
<div style="grid-column:1/-1"><label>Description</label><input class="d" value="${esc(f.descr)}"></div>
<label><input class="a" type="checkbox" style="width:auto" ${f.active?'checked':''}> Show on website</label>
<div><button class="b p" onclick="sf(this)">Save</button> ${f.id?`<button class="b d" onclick="df(${f.id})">Delete</button>`:''}</div></div>`}
function addf(){$('f').insertAdjacentHTML('afterbegin',row({name:'',emoji:'🥤',price:50,color:'#ff7b00',descr:'',active:1}))}
async function sf(b){const r=b.closest('.box'),q=s=>r.querySelector(s);await api('/api/admin/flavours','POST',{id:r.dataset.id||null,name:q('.n').value,emoji:q('.e').value,price:q('.p').value,color:q('.c').value,descr:q('.d').value,active:q('.a').checked});flavs()}
async function df(id){if(confirm('Delete this flavour?')){await api('/api/admin/flavours/'+id,'DELETE');flavs()}}
const F=[['brand','Business name'],['tagline','Hero headline'],['hero_sub','Hero sub-text'],['currency','Currency symbol'],['contact','Phone / WhatsApp'],['notify_email','Send order alerts to (your Gmail)']];
async function sets(){const s=await api('/api/admin/settings');$('s').innerHTML='<div class="box">'+F.map(([k,l])=>`<label>${l}</label><input id="s_${k}" value="${esc(s[k])}">`).join('')+
`<label>Accepting orders</label><select id="s_accepting"><option value="1" ${s.accepting=='1'?'selected':''}>Yes</option><option value="0" ${s.accepting!='1'?'selected':''}>Paused</option></select><br>
<button class="b p" onclick="ss()">Save settings</button> <button class="b" onclick="api('/api/admin/test-mail','POST');alert('Test email sent (check Gmail)')">Send test email</button></div>`}
async function ss(){const b={accepting:$('s_accepting').value};F.forEach(([k])=>b[k]=$('s_'+k).value);await api('/api/admin/settings','POST',b);alert('Saved')}
</script></body></html>"""

@app.get("/")
def home(): return SHOP

@app.get("/admin")
def admin(): return ADMIN

if __name__ == "__main__":
    init()
    if ADMIN_PW == "change-me": print("WARNING: set QYN_ADMIN_PASSWORD before going live!")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
