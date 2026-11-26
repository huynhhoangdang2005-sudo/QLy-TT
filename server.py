"""LAN API and mobile tenant portal for the Trọ Nhà desktop application.

Run app.py on the property manager's computer, then open
http://<computer-lan-address>:8765 on a tenant's phone.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import database as sqlstore

ROOT = Path(__file__).resolve().parent
MAX_BODY = 8 * 1024 * 1024
_server = None
_thread = None
_lock = threading.Lock()
_write_lock = threading.Lock()


def connect():
    return sqlstore.connect()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return base64.urlsafe_b64encode(salt + digest).decode()


def check_password(password: str, encoded: str) -> bool:
    try:
        raw = base64.urlsafe_b64decode(encoded.encode())
        return hmac.compare_digest(raw[16:], hashlib.pbkdf2_hmac("sha256", password.encode(), raw[:16], 240_000))
    except (ValueError, TypeError):
        return False


def init_schema(db):
    sqlstore.ensure_schema(db)


def initialize():
    with connect() as db:
        init_schema(db)


def _json(handler, status=200, payload=None):
    data = json.dumps(payload or {}, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(data)


def _body(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0 or length > MAX_BODY:
        raise ValueError("Ảnh hoặc dữ liệu vượt quá giới hạn 8 MB.")
    return json.loads(handler.rfile.read(length))


def _token(handler):
    value = handler.headers.get("Authorization", "")
    return value[7:] if value.startswith("Bearer ") else ""


def _user(db, handler):
    token = _token(handler)
    if not token:
        return None
    row = db.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.active=1",
                     (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
    return row


def _notify(db, user_id, title, body):
    db.execute("INSERT INTO notifications(user_id,title,body,created_at) VALUES(?,?,?,?)",
               (user_id, title, body, datetime.now().isoformat(timespec="minutes")))


def _invoice_json(db, contract_id):
    rows = db.execute("SELECT i.*,c.room_id,c.tenant FROM invoices i JOIN contracts c ON c.id=i.contract_id WHERE i.contract_id=? ORDER BY i.month DESC", (contract_id,)).fetchall()
    output = []
    for inv in rows:
        lines = db.execute("SELECT name,qty,unit,rate,amount FROM lines WHERE invoice_id=? ORDER BY id", (inv["id"],)).fetchall()
        output.append({"id": inv["id"], "month": inv["month"], "due": inv["due"], "status": inv["status"],
                       "room": inv["room_id"], "total": sum(x["amount"] or 0 for x in lines),
                       "lines": [dict(x) for x in lines], "email_sent": bool(inv["email_sent"]),
                       "meter_status": {r["utility"]: r["status"] for r in db.execute("SELECT utility,status FROM meter_readings WHERE contract_id=? AND month=?", (contract_id, inv["month"]))} })
    return output


def _ensure_invoice(db, contract_id, month):
    contract=db.execute("SELECT * FROM contracts WHERE id=?",(contract_id,)).fetchone()
    if not contract:return None
    inv=db.execute("SELECT * FROM invoices WHERE contract_id=? AND month=?",(contract_id,month)).fetchone()
    if inv:return inv
    room=db.execute("SELECT * FROM rooms WHERE id=?",(contract["room_id"],)).fetchone()
    if not room:return None
    due_day=max(1,min(28,int(contract["due_day"] or 5)))
    invoice_id=f"HD-{month.replace('-','')}-{contract['room_id']}-{contract['id'][-4:]}"
    due=f"{month}-{due_day:02d}"
    db.execute("INSERT INTO invoices(id,contract_id,month,due,status,email_sent,email_error) VALUES(?,?,?,?,N'Thiếu chỉ số',N'',N'')",(invoice_id,contract_id,month,due))
    db.execute("INSERT INTO charges(contract_id,month,electric,electric_rate,water,water_rate,internet,service,parking,other_name,other) VALUES(?,?,0,?,0,?,?,?,?,N'Phí khác',0)",
               (contract_id,month,room["electric_rate"] or 0,room["water_rate"] or 0,room["internet_fee"] or 0,room["service_fee"] or 0,room["parking_fee"] or 0))
    return db.execute("SELECT * FROM invoices WHERE id=?",(invoice_id,)).fetchone()


def _recalculate_invoice(db, invoice_id):
    inv=db.execute("SELECT * FROM invoices WHERE id=?",(invoice_id,)).fetchone()
    if not inv or inv["status"]=="Đã thanh toán":return None
    contract=db.execute("SELECT * FROM contracts WHERE id=?",(inv["contract_id"],)).fetchone()
    charges=db.execute("SELECT * FROM charges WHERE contract_id=? AND month=?",(inv["contract_id"],inv["month"])).fetchone()
    if not contract or not charges:return None
    lines=[("Tiền thuê phòng",1,"tháng",contract["rent"],contract["rent"]),
           ("Điện",charges["electric"] or 0,"kWh",charges["electric_rate"] or 0,(charges["electric"] or 0)*(charges["electric_rate"] or 0)),
           ("Nước",charges["water"] or 0,"m³",charges["water_rate"] or 0,(charges["water"] or 0)*(charges["water_rate"] or 0))]
    for name,amount in (("Internet",charges["internet"]),("Phí dịch vụ/quản lý",charges["service"]),("Phí gửi xe",charges["parking"]),(charges["other_name"] or "Phí khác",charges["other"])):
        if amount and amount>0:lines.append((name,1,"khoản",amount,amount))
    db.execute("DELETE FROM lines WHERE invoice_id=?",(invoice_id,))
    db.executemany("INSERT INTO lines(invoice_id,name,qty,unit,rate,amount) VALUES(?,?,?,?,?,?)",[(invoice_id,*line) for line in lines])
    return sum(line[4] for line in lines)


class Handler(BaseHTTPRequestHandler):
    server_version = "TroNha/1.0"

    def log_message(self, *_):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/app.js", "/manifest.webmanifest", "/sw.js", "/styles.css"):
            name = "index.html" if path in ("/", "/index.html") else path[1:]
            file = ROOT / "tenant_app" / name
            if not file.is_file():
                self.send_error(404); return
            data = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(file))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data); return
        with connect() as db:
            user = _user(db, self)
            if not user:
                _json(self, 401, {"error": "Vui lòng đăng nhập lại."}); return
            if path == "/api/me":
                _json(self, payload={"name": user["display_name"], "role": user["role"]}); return
            if user["role"] != "tenant" or not user["contract_id"]:
                _json(self, 403, {"error": "Chức năng này dành cho khách thuê."}); return
            if path == "/api/invoices":
                _json(self, payload={"invoices": _invoice_json(db, user["contract_id"])}); return
            if path == "/api/notifications":
                rows = db.execute("SELECT TOP 50 id,title,body,created_at,read_at FROM notifications WHERE user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
                _json(self, payload={"notifications": [dict(r) for r in rows]}); return
            if path == "/api/readings":
                rows = db.execute("SELECT id,month,utility,reading,previous_reading,usage,ocr_reading,status,created_at FROM meter_readings WHERE contract_id=? ORDER BY month DESC", (user["contract_id"],)).fetchall()
                _json(self, payload={"readings": [dict(r) for r in rows]}); return
            _json(self, 404, {"error": "Không tìm thấy chức năng."})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = _body(self)
        except (ValueError, json.JSONDecodeError):
            _json(self, 400, {"error": "Dữ liệu gửi lên không hợp lệ hoặc quá lớn."}); return
        if path == "/api/login":
            with connect() as db:
                row = db.execute("SELECT * FROM users WHERE username=? AND active=1", (str(data.get("username", "")).strip().lower(),)).fetchone()
                if not row or not check_password(str(data.get("password", "")), row["password_hash"]):
                    _json(self, 401, {"error": "Tên đăng nhập hoặc mật khẩu không đúng."}); return
                token = secrets.token_urlsafe(32)
                db.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), row["id"], int(time.time()) + 60 * 60 * 24 * 30))
                _json(self, payload={"token": token, "name": row["display_name"], "role": row["role"]}); return
        if path == "/api/logout":
            with connect() as db:
                token = _token(self)
                db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)); _json(self); return
        with connect() as db:
            user = _user(db, self)
            if not user:
                _json(self, 401, {"error": "Vui lòng đăng nhập lại."}); return
            if user["role"] != "tenant" or not user["contract_id"]:
                _json(self, 403, {"error": "Chỉ khách thuê được gửi chỉ số."}); return
            if path == "/api/readings":
                contract = db.execute("SELECT status,room_id FROM contracts WHERE id=?", (user["contract_id"],)).fetchone()
                if not contract or contract["status"] != "Đang thuê":
                    _json(self, 403, {"error": "Tài khoản không còn hợp đồng thuê đang hoạt động."}); return
                utility = str(data.get("utility", ""))
                if utility not in ("Điện", "Nước"):
                    _json(self, 400, {"error": "Chọn điện hoặc nước."}); return
                try:
                    reading = float(data.get("reading"))
                    ocr = float(data.get("ocr_reading")) if data.get("ocr_reading") not in (None, "") else None
                except (TypeError, ValueError):
                    _json(self, 400, {"error": "Chỉ số phải là số."}); return
                if reading < 0 or (ocr is not None and ocr < 0):
                    _json(self, 400, {"error": "Chỉ số không thể âm."}); return
                image = str(data.get("image", ""))
                if not image.startswith("data:image/") or ";base64," not in image:
                    _json(self, 400, {"error": "Vui lòng chụp hoặc chọn ảnh công tơ."}); return
                mime, encoded = image[5:].split(";base64,", 1)
                if mime not in ("image/jpeg", "image/png", "image/webp"):
                    _json(self, 400, {"error": "Ảnh phải là JPG, PNG hoặc WebP."}); return
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except (ValueError, base64.binascii.Error):
                    _json(self, 400, {"error": "Ảnh không đọc được."}); return
                if len(raw) > 5 * 1024 * 1024:
                    _json(self, 400, {"error": "Ảnh tối đa 5 MB."}); return
                month = datetime.now().strftime("%Y-%m")
                paid=db.execute("SELECT status FROM invoices WHERE contract_id=? AND month=?",(user["contract_id"],month)).fetchone()
                if paid and paid["status"]=="Đã thanh toán":
                    _json(self,409,{"error":"Hóa đơn tháng này đã thanh toán; không thể thay đổi chỉ số."});return
                prior = db.execute("SELECT TOP 1 reading FROM meter_readings WHERE contract_id=? AND utility=? AND status IN (N'Đã cập nhật',N'Đã duyệt') AND month<? ORDER BY month DESC", (user["contract_id"], utility, month)).fetchone()
                previous = prior[0] if prior else None
                previous_reading = previous if previous is not None else reading
                usage = reading - previous_reading
                if usage < 0:
                    _json(self, 400, {"error": "Chỉ số nhỏ hơn lần đã duyệt gần nhất; hãy kiểm tra lại hoặc liên hệ quản lý."}); return
                try:
                    existing=db.execute("SELECT id FROM meter_readings WHERE contract_id=? AND month=? AND utility=?",(user["contract_id"],month,utility)).fetchone()
                    if existing:
                        db.execute("UPDATE meter_readings SET reading=?,previous_reading=?,usage=?,ocr_reading=?,image_data=?,image_mime=?,image_path=N'',status=N'Đã cập nhật',created_at=?,reviewed_at=? WHERE id=?",
                                   (reading,previous_reading,usage,ocr,raw,mime,datetime.now().isoformat(timespec="minutes"),datetime.now().isoformat(timespec="minutes"),existing["id"]))
                    else:
                        db.execute("INSERT INTO meter_readings(contract_id,month,utility,reading,previous_reading,usage,ocr_reading,image_data,image_mime,image_path,status,created_at,reviewed_at) VALUES(?,?,?,?,?,?,?,?,?,N'',N'Đã cập nhật',?,?)",
                                   (user["contract_id"],month,utility,reading,previous_reading,usage,ocr,raw,mime,datetime.now().isoformat(timespec="minutes"),datetime.now().isoformat(timespec="minutes")))
                    inv=_ensure_invoice(db,user["contract_id"],month)
                    if not inv:
                        _json(self,500,{"error":"Không tạo được hóa đơn cho hợp đồng này."});return
                    if utility=="Điện":
                        db.execute("UPDATE charges SET electric=? WHERE contract_id=? AND month=?",(usage,user["contract_id"],month))
                    else:
                        db.execute("UPDATE charges SET water=? WHERE contract_id=? AND month=?",(usage,user["contract_id"],month))
                    total=_recalculate_invoice(db,inv["id"])
                    utilities={r[0] for r in db.execute("SELECT utility FROM meter_readings WHERE contract_id=? AND month=? AND status=N'Đã cập nhật'",(user["contract_id"],month)).fetchall()}
                    complete={"Điện","Nước"}.issubset(utilities)
                    invoice_status="Chưa thanh toán" if complete else "Thiếu chỉ số"
                    db.execute("UPDATE invoices SET status=?,email_error=N'' WHERE id=? AND status<>N'Đã thanh toán'",(invoice_status,inv["id"]))
                except Exception:
                    _json(self, 500, {"error": "Không lưu được chỉ số."}); return
                admin_ids = [r[0] for r in db.execute("SELECT id FROM users WHERE role='admin' AND active=1")]
                for aid in admin_ids:
                    _notify(db, aid, "Chỉ số đã tự cập nhật", f"Phòng {contract['room_id']}, {utility.lower()} tháng {month}: {reading}. Lượng dùng {usage}; hóa đơn đã tính lại tự động.")
                tenant_title="Hóa đơn đã cập nhật" if complete else "Đã cập nhật chỉ số"
                tenant_body=(f"Hóa đơn tháng {month} đã đủ điện nước và được tính tự động: {total:,.0f} ₫." if complete else f"Đã ghi nhận {utility.lower()} phòng {contract['room_id']}, mức dùng {usage}. Hóa đơn tạm tính hiện là {total:,.0f} ₫; sẽ cập nhật tiếp khi gửi đủ điện và nước.")
                _notify(db,user["id"],tenant_title,tenant_body)
                db.commit()
                _json(self, payload={"ok": True, "status": invoice_status, "usage": usage, "invoice_total": total, "complete": complete}); return
            if path == "/api/notifications/read":
                nid = int(data.get("id", 0))
                db.execute("UPDATE notifications SET read_at=? WHERE id=? AND user_id=?", (datetime.now().isoformat(timespec="minutes"), nid, user["id"]))
                _json(self); return
            if path == "/api/password":
                old = str(data.get("old_password", "")); new = str(data.get("new_password", ""))
                if len(new) < 10 or len(new) > 200:
                    _json(self, 400, {"error": "Mật khẩu mới cần có từ 10 đến 200 ký tự."}); return
                if not check_password(old, user["password_hash"]):
                    _json(self, 400, {"error": "Mật khẩu hiện tại không đúng."}); return
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), user["id"]))
                db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash!=?", (user["id"], hashlib.sha256(_token(self).encode()).hexdigest()))
                _json(self, payload={"ok": True}); return
            _json(self, 404, {"error": "Không tìm thấy chức năng."})


def start_server(host="0.0.0.0", port=8765):
    global _server, _thread
    with _lock:
        if _server:
            return _server.server_address
        initialize()
        try:
            _server = ThreadingHTTPServer((host, port), Handler)
        except OSError as exc:
            _server = None
            raise RuntimeError(f"Không thể mở cổng {port}: {exc}") from exc
        _server.daemon_threads = True
        _thread = threading.Thread(target=_server.serve_forever, name="TroNhaServer", daemon=True)
        _thread.start()
        return _server.server_address


def stop_server():
    global _server, _thread
    with _lock:
        if _server:
            _server.shutdown(); _server.server_close(); _server = None; _thread = None
