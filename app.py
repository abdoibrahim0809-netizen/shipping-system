from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort
import sqlite3, os, hashlib, secrets
from datetime import datetime

BASE=os.path.dirname(__file__); DB=os.path.join(BASE,'shipping.db')
app=Flask(__name__); app.secret_key=os.environ.get('SECRET_KEY','change-this-secret')

STATUSES=['جديدة','استلمها المندوب','خرجت للتوصيل','تم التسليم','مرتجع','ملغاة']

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def hashpw(p): return hashlib.sha256(p.encode()).hexdigest()

def init():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT, name TEXT);
    CREATE TABLE IF NOT EXISTS merchants(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT, address TEXT, shipping_fee REAL DEFAULT 0, created_at TEXT);
    CREATE TABLE IF NOT EXISTS couriers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT, area TEXT, commission REAL DEFAULT 0, created_at TEXT);
    CREATE TABLE IF NOT EXISTS shipments(id INTEGER PRIMARY KEY, tracking TEXT UNIQUE, merchant_id INTEGER, courier_id INTEGER, recipient TEXT NOT NULL, phone TEXT, governorate TEXT, area TEXT, address TEXT, pieces INTEGER DEFAULT 1, amount REAL DEFAULT 0, shipping_fee REAL DEFAULT 0, status TEXT DEFAULT 'جديدة', notes TEXT, created_at TEXT, updated_at TEXT, FOREIGN KEY(merchant_id) REFERENCES merchants(id), FOREIGN KEY(courier_id) REFERENCES couriers(id));
    CREATE TABLE IF NOT EXISTS shipment_events(id INTEGER PRIMARY KEY, shipment_id INTEGER, status TEXT, note TEXT, created_at TEXT, FOREIGN KEY(shipment_id) REFERENCES shipments(id));
    ''')
    if not c.execute('SELECT 1 FROM users LIMIT 1').fetchone():
        c.execute('INSERT INTO users(username,password,role,name) VALUES(?,?,?,?)',('admin',hashpw('admin123'),'admin','مدير النظام'))
    c.commit(); c.close()

def login_required(): return 'uid' in session

def next_tracking(c):
    n=c.execute('SELECT COUNT(*) n FROM shipments').fetchone()['n']+1
    return f'SH-{n:06d}'

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=request.form.get('username','').strip(); p=request.form.get('password','')
        c=db(); user=c.execute('SELECT * FROM users WHERE username=? AND password=?',(u,hashpw(p))).fetchone(); c.close()
        if user:
            session.update(uid=user['id'],name=user['name'],role=user['role']); return redirect(url_for('dashboard'))
        return render_template('login.html',error='اسم المستخدم أو كلمة المرور غير صحيحة')
    return render_template('login.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/')
def dashboard():
    if not login_required(): return redirect(url_for('login'))
    c=db(); counts={s:c.execute('SELECT COUNT(*) n FROM shipments WHERE status=?',(s,)).fetchone()['n'] for s in STATUSES}
    total=c.execute('SELECT COUNT(*) n FROM shipments').fetchone()['n']; amount=c.execute('SELECT COALESCE(SUM(amount),0) x FROM shipments WHERE status="تم التسليم"').fetchone()['x']
    recent=c.execute('''SELECT s.*,m.name merchant,co.name courier FROM shipments s LEFT JOIN merchants m ON m.id=s.merchant_id LEFT JOIN couriers co ON co.id=s.courier_id ORDER BY s.id DESC LIMIT 10''').fetchall(); c.close()
    return render_template('dashboard.html',counts=counts,total=total,amount=amount,recent=recent,statuses=STATUSES)

@app.route('/shipments')
def shipments():
    if not login_required(): return redirect(url_for('login'))
    q=request.args.get('q','').strip(); status=request.args.get('status','')
    c=db(); sql='''SELECT s.*,m.name merchant,co.name courier FROM shipments s LEFT JOIN merchants m ON m.id=s.merchant_id LEFT JOIN couriers co ON co.id=s.courier_id WHERE 1=1'''; args=[]
    if q: sql+=' AND (s.tracking LIKE ? OR s.recipient LIKE ? OR s.phone LIKE ?)'; args += [f'%{q}%']*3
    if status: sql+=' AND s.status=?'; args.append(status)
    sql+=' ORDER BY s.id DESC'; rows=c.execute(sql,args).fetchall(); merchants=c.execute('SELECT * FROM merchants ORDER BY name').fetchall(); couriers=c.execute('SELECT * FROM couriers ORDER BY name').fetchall(); c.close()
    return render_template('shipments.html',rows=rows,merchants=merchants,couriers=couriers,statuses=STATUSES,q=q,status=status)

@app.route('/shipments/new',methods=['POST'])
def new_shipment():
    if not login_required(): return redirect(url_for('login'))
    c=db(); now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'); tracking=next_tracking(c)
    data=[tracking, request.form.get('merchant_id') or None, request.form.get('courier_id') or None, request.form.get('recipient',''), request.form.get('phone',''),request.form.get('governorate',''),request.form.get('area',''),request.form.get('address',''),int(request.form.get('pieces') or 1),float(request.form.get('amount') or 0),float(request.form.get('shipping_fee') or 0),'جديدة',request.form.get('notes',''),now,now]
    c.execute('''INSERT INTO shipments(tracking,merchant_id,courier_id,recipient,phone,governorate,area,address,pieces,amount,shipping_fee,status,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',data); sid=c.lastrowid; c.execute('INSERT INTO shipment_events(shipment_id,status,note,created_at) VALUES(?,?,?,?)',(sid,'جديدة','تم إنشاء الشحنة',now)); c.commit(); c.close(); return redirect(url_for('shipments'))

@app.route('/shipments/<int:sid>/status',methods=['POST'])
def change_status(sid):
    if not login_required(): return redirect(url_for('login'))
    st=request.form.get('status'); note=request.form.get('note','');
    if st not in STATUSES: abort(400)
    c=db(); now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'); c.execute('UPDATE shipments SET status=?,updated_at=? WHERE id=?',(st,now,sid)); c.execute('INSERT INTO shipment_events(shipment_id,status,note,created_at) VALUES(?,?,?,?)',(sid,st,note,now)); c.commit(); c.close(); return redirect(request.referrer or url_for('shipments'))

@app.route('/merchants',methods=['GET','POST'])
def merchants():
    if not login_required(): return redirect(url_for('login'))
    c=db()
    if request.method=='POST':
        c.execute('INSERT INTO merchants(name,phone,address,shipping_fee,created_at) VALUES(?,?,?,?,?)',(request.form['name'],request.form.get('phone',''),request.form.get('address',''),float(request.form.get('shipping_fee') or 0),datetime.now().strftime('%Y-%m-%d %H:%M:%S'))); c.commit()
    rows=c.execute('SELECT m.*,COUNT(s.id) shipments FROM merchants m LEFT JOIN shipments s ON s.merchant_id=m.id GROUP BY m.id ORDER BY m.id DESC').fetchall(); c.close(); return render_template('merchants.html',rows=rows)

@app.route('/couriers',methods=['GET','POST'])
def couriers():
    if not login_required(): return redirect(url_for('login'))
    c=db()
    if request.method=='POST':
        c.execute('INSERT INTO couriers(name,phone,area,commission,created_at) VALUES(?,?,?,?,?)',(request.form['name'],request.form.get('phone',''),request.form.get('area',''),float(request.form.get('commission') or 0),datetime.now().strftime('%Y-%m-%d %H:%M:%S'))); c.commit()
    rows=c.execute('SELECT co.*,COUNT(s.id) shipments FROM couriers co LEFT JOIN shipments s ON s.courier_id=co.id GROUP BY co.id ORDER BY co.id DESC').fetchall(); c.close(); return render_template('couriers.html',rows=rows)

@app.route('/track',methods=['GET','POST'])
def track():
    code=request.values.get('tracking','').strip(); row=None; events=[]
    if code:
        c=db(); row=c.execute('''SELECT s.*,m.name merchant,co.name courier FROM shipments s LEFT JOIN merchants m ON m.id=s.merchant_id LEFT JOIN couriers co ON co.id=s.courier_id WHERE s.tracking=?''',(code,)).fetchone();
        if row: events=c.execute('SELECT * FROM shipment_events WHERE shipment_id=? ORDER BY id',(row['id'],)).fetchall()
        c.close()
    return render_template('track.html',row=row,events=events,code=code)

@app.route('/api/shipments/<tracking>')
def api_tracking(tracking):
    c=db(); row=c.execute('SELECT tracking,recipient,governorate,area,status,updated_at FROM shipments WHERE tracking=?',(tracking,)).fetchone(); c.close()
    return jsonify(dict(row) if row else {'error':'not_found'}), (200 if row else 404)

if __name__=='__main__': init(); app.run(host='0.0.0.0',port=5000,debug=False)
