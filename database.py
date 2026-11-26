"""SQL Server persistence and one-time import of the former SQLite store."""
from __future__ import annotations

import json
import os
import sqlite3
import base64
import ctypes
from ctypes import wintypes
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
LEGACY_DB = ROOT_DIR / "tro_nha.db"
CONFIG_FILE = ROOT_DIR / "sqlserver.json"
DEFAULT_CONFIG = {
    "server": r"(localdb)\MSSQLLocalDB",
    "database": "QuanLyNhaTro",
    "authentication": "sql",
    "driver": "ODBC Driver 18 for SQL Server",
}


class DatabaseError(Exception):
    pass


class IntegrityError(DatabaseError):
    pass


class Row:
    def __init__(self, columns, values):
        self._columns = tuple(columns)
        self._values = tuple(values)
        self._indexes = {name.lower(): index for index, name in enumerate(self._columns)}

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._indexes[key.lower()]]
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._columns


class Result:
    def __init__(self, cursor):
        self._cursor = cursor
        self._columns = tuple(item[0] for item in (cursor.description or ()))

    def fetchone(self):
        row = self._cursor.fetchone()
        return Row(self._columns, row) if row is not None else None

    def fetchall(self):
        return [Row(self._columns, row) for row in self._cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, statement, parameters=()):
        cursor = self.raw.cursor()
        try:
            cursor.execute(statement, parameters)
        except Exception as exc:
            try:
                import pyodbc
                if isinstance(exc, pyodbc.Error) and ("23000" in str(exc) or "2601" in str(exc) or "2627" in str(exc)):
                    raise IntegrityError(str(exc)) from exc
            except ImportError:
                pass
            raise
        return Result(cursor)

    def executemany(self, statement, rows):
        cursor = self.raw.cursor()
        cursor.fast_executemany = True
        try:
            cursor.executemany(statement, rows)
        except Exception as exc:
            try:
                import pyodbc
                if isinstance(exc, pyodbc.Error) and ("23000" in str(exc) or "2601" in str(exc) or "2627" in str(exc)):
                    raise IntegrityError(str(exc)) from exc
            except ImportError:
                pass
            raise
        return Result(cursor)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, _tb):
        try:
            self.commit() if exc_type is None else self.rollback()
        finally:
            self.close()


def load_config():
    config = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.is_file():
        try:
            stored = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            config.update({key: stored[key] for key in ("server", "database", "authentication", "driver") if key in stored})
            config["username"] = stored.get("username", "")
            protected = stored.get("password_dpapi", "")
            config["password"] = _unprotect(protected) if protected else ""
        except (OSError, ValueError):
            raise DatabaseError(f"Không đọc được cấu hình SQL Server: {CONFIG_FILE.name}")
    config["server"] = os.environ.get("TRONHA_SQLSERVER", config["server"])
    config["database"] = os.environ.get("TRONHA_DATABASE", config["database"])
    return config


def configure_dialog(parent):
    import tkinter as tk
    from tkinter import messagebox, ttk
    config=load_config();win=tk.Toplevel(parent);win.title("Kết nối SQL Server");win.transient(parent);win.grab_set();win.resizable(False,False)
    frame=ttk.Frame(win,padding=18);frame.pack(fill="both",expand=True);controls={}
    fields=[("server","Máy chủ / instance SQL Server",config["server"]),("database","Tên database",config["database"]),("username","SQL Login",config.get("username","")),("password","Mật khẩu SQL Login",config.get("password",""))]
    for n,(key,label,value) in enumerate(fields):
        ttk.Label(frame,text=label).grid(row=n,column=0,sticky="w",padx=(0,14),pady=7)
        ctl=ttk.Entry(frame,width=42,show="*" if key=="password" else "");ctl.insert(0,value);ctl.grid(row=n,column=1,sticky="ew",pady=7);controls[key]=ctl
    ttk.Label(frame,text="Đăng nhập").grid(row=4,column=0,sticky="w",padx=(0,14),pady=7)
    auth=ttk.Combobox(frame,values=["SQL Login","Windows Authentication"],state="readonly",width=39)
    auth.set("Windows Authentication" if config["authentication"].lower()=="windows" else "SQL Login");auth.grid(row=4,column=1,sticky="ew",pady=7)
    ttk.Label(frame,text="LocalDB trong ảnh chỉ hỗ trợ Windows Authentication. Muốn dùng SQL Login, nhập tên một SQL Server thông thường đã bật Mixed Mode.",wraplength=470).grid(row=5,column=0,columnspan=2,sticky="w",pady=(6,14))
    result={}
    def save():
        result.update({key:ctl.get().strip() for key,ctl in controls.items()})
        result["authentication"]="windows" if auth.get()=="Windows Authentication" else "sql"
        result["driver"]=_driver(config);win.destroy()
    buttons=ttk.Frame(frame);buttons.grid(row=6,column=0,columnspan=2,sticky="e")
    ttk.Button(buttons,text="Hủy",command=win.destroy).pack(side="right",padx=5)
    ttk.Button(buttons,text="Lưu cấu hình",command=save).pack(side="right")
    parent.wait_window(win)
    if not result:return None
    if not result["server"] or not result["database"]:messagebox.showerror("Thiếu thông tin","Nhập máy chủ và tên database.",parent=parent);return None
    if result["authentication"]=="sql" and (not result["username"] or not result["password"]):messagebox.showerror("Thiếu thông tin","Nhập SQL Login và mật khẩu.",parent=parent);return None
    return result


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _protect(value):
    if os.name != "nt":
        raise DatabaseError("SQL Login được lưu bằng mã hóa Windows DPAPI; chỉ hỗ trợ Windows.")
    raw = value.encode("utf-8")
    source_buffer = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    result = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    if not crypt32.CryptProtectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return base64.b64encode(ctypes.string_at(result.pbData, result.cbData)).decode("ascii")
    finally:
        ctypes.WinDLL("kernel32", use_last_error=True).LocalFree(result.pbData)


def _unprotect(value):
    if os.name != "nt":
        raise DatabaseError("Không thể giải mã cấu hình SQL Login ngoài Windows.")
    raw = base64.b64decode(value)
    source_buffer = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    result = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.pbData, result.cbData).decode("utf-8")
    finally:
        ctypes.WinDLL("kernel32", use_last_error=True).LocalFree(result.pbData)


def save_config(config):
    stored = {key: config.get(key, DEFAULT_CONFIG.get(key, "")) for key in ("server", "database", "authentication", "driver", "username")}
    password = config.get("password", "")
    if stored["authentication"].lower() == "sql" and password:
        stored["password_dpapi"] = _protect(password)
    elif stored["authentication"].lower() == "sql":
        try:
            old=json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if old.get("username")==stored.get("username") and old.get("server")==stored.get("server"):
                stored["password_dpapi"]=old.get("password_dpapi","")
        except (OSError,ValueError):pass
    CONFIG_FILE.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")


def _driver(config):
    return config.get("driver") or "ODBC Driver 18 for SQL Server"


def _connection_string(config, database_name):
    def quoted(value):
        return "{" + str(value).replace("}", "}}") + "}"
    parts = [f"DRIVER={quoted(_driver(config))}", f"SERVER={quoted(config['server'])}", f"DATABASE={quoted(database_name)}", "TrustServerCertificate=yes", "Connection Timeout=12"]
    authentication = config.get("authentication", "windows").lower()
    if authentication == "windows":
        parts.append("Trusted_Connection=yes")
    elif authentication == "sql":
        if not config.get("username") or not config.get("password"):
            raise DatabaseError("Cần nhập tên đăng nhập và mật khẩu SQL Login.")
        parts.extend((f"UID={quoted(config.get('username', ''))}", f"PWD={quoted(config.get('password', ''))}"))
    else:
        raise DatabaseError("Kiểu đăng nhập SQL Server phải là windows hoặc sql.")
    return ";".join(parts) + ";"


def connect(config=None):
    config = config or load_config()
    try:
        import pyodbc
    except ImportError as exc:
        raise DatabaseError("Thiếu thư viện pyodbc. Hãy cài các gói trong requirements.txt bằng Python 3.11.") from exc
    database_name = str(config.get("database", "")).strip()
    server_name = str(config.get("server", "")).strip()
    if not database_name or not server_name:
        raise DatabaseError("Cần cấu hình tên máy chủ và database SQL Server.")
    try:
        master = pyodbc.connect(_connection_string(config, "master"), timeout=12, autocommit=True)
        try:
            found = master.cursor().execute("SELECT DB_ID(?)", database_name).fetchone()[0]
            if found is None:
                safe_name = database_name.replace("]", "]]" )
                master.cursor().execute(f"CREATE DATABASE [{safe_name}]")
        finally:
            master.close()
        raw = pyodbc.connect(_connection_string(config, database_name), timeout=12, autocommit=False)
        return Connection(raw)
    except Exception as exc:
        if isinstance(exc, DatabaseError):
            raise
        raise DatabaseError(f"Không kết nối được SQL Server {server_name}, database {database_name}: {exc}") from exc


SCHEMA = [
    """IF OBJECT_ID(N'dbo.rooms',N'U') IS NULL CREATE TABLE dbo.rooms(
      id NVARCHAR(255) NOT NULL PRIMARY KEY,area NVARCHAR(255),floor NVARCHAR(100),size FLOAT,rent FLOAT,status NVARCHAR(100),note NVARCHAR(MAX),
      photo_path NVARCHAR(1000) NOT NULL CONSTRAINT DF_rooms_photo DEFAULT N'',electric_rate FLOAT NOT NULL CONSTRAINT DF_rooms_er DEFAULT 0,
      water_rate FLOAT NOT NULL CONSTRAINT DF_rooms_wr DEFAULT 0,internet_fee FLOAT NOT NULL CONSTRAINT DF_rooms_if DEFAULT 0,
      service_fee FLOAT NOT NULL CONSTRAINT DF_rooms_sf DEFAULT 0,parking_fee FLOAT NOT NULL CONSTRAINT DF_rooms_pf DEFAULT 0,
      photo_data VARBINARY(MAX) NULL,photo_mime NVARCHAR(100) NULL)""",
    """IF OBJECT_ID(N'dbo.leads',N'U') IS NULL CREATE TABLE dbo.leads(
      id INT IDENTITY(1,1) PRIMARY KEY,name NVARCHAR(500),phone NVARCHAR(100),email NVARCHAR(500),room_id NVARCHAR(255),contact_date NVARCHAR(50),
      status NVARCHAR(100),source NVARCHAR(255),note NVARCHAR(MAX))""",
    """IF OBJECT_ID(N'dbo.contracts',N'U') IS NULL CREATE TABLE dbo.contracts(
      id NVARCHAR(255) NOT NULL PRIMARY KEY,tenant NVARCHAR(500),phone NVARCHAR(100),email NVARCHAR(500),room_id NVARCHAR(255),
      start_date NVARCHAR(50),end_date NVARCHAR(50),rent FLOAT,deposit FLOAT,due_day INT,status NVARCHAR(100))""",
    """IF OBJECT_ID(N'dbo.charges',N'U') IS NULL CREATE TABLE dbo.charges(
      contract_id NVARCHAR(255) NOT NULL,month CHAR(7) NOT NULL,electric FLOAT,electric_rate FLOAT,water FLOAT,water_rate FLOAT,
      internet FLOAT,service FLOAT,parking FLOAT,other_name NVARCHAR(500),other FLOAT,CONSTRAINT PK_charges PRIMARY KEY(contract_id,month))""",
    """IF OBJECT_ID(N'dbo.invoices',N'U') IS NULL CREATE TABLE dbo.invoices(
      id NVARCHAR(255) NOT NULL PRIMARY KEY,contract_id NVARCHAR(255) NOT NULL,month CHAR(7) NOT NULL,due NVARCHAR(50),status NVARCHAR(100),
      email_sent NVARCHAR(100) NOT NULL CONSTRAINT DF_invoices_es DEFAULT N'',email_error NVARCHAR(1000) NOT NULL CONSTRAINT DF_invoices_ee DEFAULT N'',
      CONSTRAINT UQ_invoices_contract_month UNIQUE(contract_id,month))""",
    """IF OBJECT_ID(N'dbo.lines',N'U') IS NULL CREATE TABLE dbo.lines(
      id INT IDENTITY(1,1) PRIMARY KEY,invoice_id NVARCHAR(255),name NVARCHAR(500),qty FLOAT,unit NVARCHAR(100),rate FLOAT,amount FLOAT)""",
    """IF OBJECT_ID(N'dbo.payments',N'U') IS NULL CREATE TABLE dbo.payments(
      id INT IDENTITY(1,1) PRIMARY KEY,date NVARCHAR(50),tenant NVARCHAR(500),room NVARCHAR(255),description NVARCHAR(1000),amount FLOAT,note NVARCHAR(MAX))""",
    """IF OBJECT_ID(N'dbo.settings',N'U') IS NULL CREATE TABLE dbo.settings([key] NVARCHAR(255) NOT NULL PRIMARY KEY,value NVARCHAR(MAX))""",
    """IF OBJECT_ID(N'dbo.users',N'U') IS NULL CREATE TABLE dbo.users(
      id INT IDENTITY(1,1) PRIMARY KEY,username NVARCHAR(255) NOT NULL UNIQUE,display_name NVARCHAR(500) NOT NULL,password_hash NVARCHAR(255) NOT NULL,
      role NVARCHAR(20) NOT NULL,contract_id NVARCHAR(255) NULL UNIQUE,active BIT NOT NULL CONSTRAINT DF_users_active DEFAULT 1,created_at NVARCHAR(50) NOT NULL)""",
    """IF OBJECT_ID(N'dbo.sessions',N'U') IS NULL CREATE TABLE dbo.sessions(
      token_hash NVARCHAR(128) NOT NULL PRIMARY KEY,user_id INT NOT NULL,expires BIGINT NOT NULL)""",
    """IF OBJECT_ID(N'dbo.meter_readings',N'U') IS NULL CREATE TABLE dbo.meter_readings(
      id INT IDENTITY(1,1) PRIMARY KEY,contract_id NVARCHAR(255) NOT NULL,month CHAR(7) NOT NULL,utility NVARCHAR(50) NOT NULL,
      reading FLOAT NOT NULL,previous_reading FLOAT NULL,usage FLOAT NULL,ocr_reading FLOAT NULL,image_path NVARCHAR(1000) NOT NULL CONSTRAINT DF_meter_path DEFAULT N'',
      image_data VARBINARY(MAX) NULL,image_mime NVARCHAR(100) NULL,status NVARCHAR(50) NOT NULL CONSTRAINT DF_meter_status DEFAULT N'Chờ duyệt',
      created_at NVARCHAR(50) NOT NULL,reviewed_at NVARCHAR(50) NULL,CONSTRAINT UQ_meter_month UNIQUE(contract_id,month,utility))""",
    """IF COL_LENGTH(N'dbo.meter_readings',N'image_data') IS NULL ALTER TABLE dbo.meter_readings ADD image_data VARBINARY(MAX) NULL""",
    """IF COL_LENGTH(N'dbo.meter_readings',N'image_mime') IS NULL ALTER TABLE dbo.meter_readings ADD image_mime NVARCHAR(100) NULL""",
    """IF COL_LENGTH(N'dbo.rooms',N'photo_data') IS NULL ALTER TABLE dbo.rooms ADD photo_data VARBINARY(MAX) NULL""",
    """IF COL_LENGTH(N'dbo.rooms',N'photo_mime') IS NULL ALTER TABLE dbo.rooms ADD photo_mime NVARCHAR(100) NULL""",
    """IF OBJECT_ID(N'dbo.notifications',N'U') IS NULL CREATE TABLE dbo.notifications(
      id INT IDENTITY(1,1) PRIMARY KEY,user_id INT NOT NULL,title NVARCHAR(500) NOT NULL,body NVARCHAR(MAX) NOT NULL,created_at NVARCHAR(50) NOT NULL,read_at NVARCHAR(50) NULL)""",
    """IF OBJECT_ID(N'dbo.legacy_imports',N'U') IS NULL CREATE TABLE dbo.legacy_imports(
      source_name NVARCHAR(255) NOT NULL PRIMARY KEY,imported_at NVARCHAR(50) NOT NULL,rows_imported INT NOT NULL)""",
]


def ensure_schema(db):
    for statement in SCHEMA:
        db.execute(statement)
    for key in ("host","port","user","password","sender","tls","auto_send"):
        if not db.execute("SELECT 1 FROM dbo.settings WHERE [key]=?",(key,)).fetchone():
            db.execute("INSERT INTO dbo.settings([key],value) VALUES(?,?)",(key,{"host":"","port":"587","user":"","password":"","sender":"","tls":"1","auto_send":"0"}[key]))
    db.commit()


LEGACY_TABLES = [
    ("rooms", ["id","area","floor","size","rent","status","note","photo_path","electric_rate","water_rate","internet_fee","service_fee","parking_fee","photo_data","photo_mime"], ["id"], False),
    ("leads", ["id","name","phone","email","room_id","contact_date","status","source","note"], ["id"], True),
    ("contracts", ["id","tenant","phone","email","room_id","start_date","end_date","rent","deposit","due_day","status"], ["id"], False),
    ("charges", ["contract_id","month","electric","electric_rate","water","water_rate","internet","service","parking","other_name","other"], ["contract_id","month"], False),
    ("invoices", ["id","contract_id","month","due","status","email_sent","email_error"], ["id"], False),
    ("lines", ["id","invoice_id","name","qty","unit","rate","amount"], ["id"], True),
    ("payments", ["id","date","tenant","room","description","amount","note"], ["id"], True),
    ("settings", ["key","value"], ["key"], False),
    ("users", ["id","username","display_name","password_hash","role","contract_id","active","created_at"], ["username"], True),
    ("sessions", ["token_hash","user_id","expires"], ["token_hash"], False),
    ("meter_readings", ["id","contract_id","month","utility","reading","previous_reading","usage","ocr_reading","image_path","image_data","image_mime","status","created_at","reviewed_at"], ["contract_id","month","utility"], True),
    ("notifications", ["id","user_id","title","body","created_at","read_at"], ["id"], True),
]


def migrate_legacy(db):
    if not LEGACY_DB.is_file():
        return 0
    if db.execute("SELECT 1 FROM dbo.legacy_imports WHERE source_name=?", (LEGACY_DB.name,)).fetchone():
        return 0
    src = sqlite3.connect(LEGACY_DB)
    src.row_factory = sqlite3.Row
    tables = {row[0] for row in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    imported = 0
    try:
        for table, target_columns, keys, identity in LEGACY_TABLES:
            if table not in tables:
                continue
            source_columns = {row["name"] for row in src.execute(f"PRAGMA table_info([{table}])")}
            available = [column for column in target_columns if column in source_columns or column in ("image_data","image_mime","photo_data","photo_mime")]
            if not available:
                continue
            records = src.execute(f"SELECT * FROM [{table}]").fetchall()
            if identity:
                db.execute(f"SET IDENTITY_INSERT dbo.[{table}] ON")
            try:
                for old in records:
                    values = {column: old[column] if column in source_columns else None for column in available}
                    if table == "rooms":
                        for name, default in (("photo_path",""),("electric_rate",0),("water_rate",0),("internet_fee",0),("service_fee",0),("parking_fee",0)):
                            values.setdefault(name, default)
                        path=values.get("photo_path")
                        if path and Path(path).is_file():
                            import mimetypes
                            values["photo_data"]=Path(path).read_bytes();values["photo_mime"]=mimetypes.guess_type(path)[0] or "image/jpeg";values["photo_path"]=Path(path).name
                        else:
                            values.setdefault("photo_data",None);values.setdefault("photo_mime",None)
                    if table == "invoices":
                        values.setdefault("email_sent", ""); values.setdefault("email_error", "")
                    if table == "users":
                        values.setdefault("active", 1)
                    if table == "meter_readings":
                        values.setdefault("image_data", None); values.setdefault("image_mime", None)
                        path = values.get("image_path")
                        if path and Path(path).is_file():
                            import mimetypes
                            values["image_data"] = Path(path).read_bytes()
                            values["image_mime"] = mimetypes.guess_type(path)[0] or "image/jpeg"
                        elif path:
                            local_photo = ROOT_DIR / "meter_photos" / Path(path).name
                            if local_photo.is_file():
                                values["image_data"] = local_photo.read_bytes(); values["image_mime"] = "image/jpeg"
                    where = " AND ".join(f"[{key}]=?" for key in keys)
                    if db.execute(f"SELECT 1 FROM dbo.[{table}] WHERE {where}", tuple(values[key] for key in keys)).fetchone():
                        continue
                    columns = ",".join(f"[{column}]" for column in available)
                    marks = ",".join("?" for _ in available)
                    db.execute(f"INSERT INTO dbo.[{table}] ({columns}) VALUES ({marks})", tuple(values.get(column) for column in available))
                    imported += 1
            finally:
                if identity:
                    db.execute(f"SET IDENTITY_INSERT dbo.[{table}] OFF")
        db.execute("INSERT INTO dbo.legacy_imports(source_name,imported_at,rows_imported) VALUES(?,?,?)", (LEGACY_DB.name, __import__("datetime").datetime.now().isoformat(timespec="minutes"), imported))
        db.commit()
        return imported
    except Exception:
        db.rollback()
        raise
    finally:
        src.close()
