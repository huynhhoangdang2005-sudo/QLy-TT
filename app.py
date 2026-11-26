"""Trọ Nhà: native Windows desktop app using Tkinter + SQL Server."""
from __future__ import annotations
import calendar, email.message, os, re, smtplib, ssl, sys, tempfile, threading, tkinter as tk
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import server as portal
import database as sqlstore

ROOT_DIR = Path(__file__).resolve().parent
TODAY = lambda: date.today().isoformat()
MONTH = lambda: date.today().strftime("%Y-%m")
MONEY = lambda n: f"{float(n or 0):,.0f} ₫"
DEFAULT_TENANT_PASSWORD = "tronha"


class PageDeck(ttk.Frame):
    """Notebook-like page selector without a visible tab strip."""
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.pages = []
        self.current = None

    def add(self, child, text=""):
        self.pages.append((child, text))
        child.place(relx=0, rely=0, relwidth=1, relheight=1)
        if self.current is None:
            self.select(0)

    def index(self, item):
        if item == "end": return len(self.pages)
        if isinstance(item, int): return item
        for i, (page, _title) in enumerate(self.pages):
            if str(page) == str(item): return i
        raise tk.TclError("Không tìm thấy trang")

    def tab(self, item, option=None):
        page, title = self.pages[self.index(item)]
        return title if option == "text" else {"text": title}

    def select(self, item=None):
        if item is None: return self.current
        index = self.index(item)
        self.current = index
        self.pages[index][0].tkraise()


class RentalApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Trọ Nhà — Quản lý phòng trọ")
        self.root.geometry("1280x780")
        self.root.minsize(940, 600)
        self.sending = set()
        self.temp_images=[]
        self.code_snapshot=self.read_code_snapshot()
        self.code_candidate=None
        self.code_candidate_stable=0
        try:
            config=sqlstore.load_config()
            save_connection_config=False
            ready=sqlstore.CONFIG_FILE.is_file() and config.get("server") and config.get("database") and (config.get("authentication")=="windows" or (config.get("username") and config.get("password")))
            if not ready:
                setup=sqlstore.configure_dialog(self.root)
                if not setup:self.root.destroy();return
                config=setup
                save_connection_config=True
            if config.get("authentication", "windows").lower()=="sql" and (not config.get("username") or not config.get("password")):
                messagebox.showerror("Thiếu SQL Login","Cần nhập tài khoản và mật khẩu SQL Server.",parent=self.root);self.root.destroy();return
            self.db=sqlstore.connect(config)
            if save_connection_config:sqlstore.save_config(config)
            self.create_tables()
            portal.init_schema(self.db)
        except Exception as exc:
            messagebox.showerror("Không kết nối được SQL Server",f"Trọ Nhà không khởi động vì không thể mở hoặc tạo database SQL Server.\n\n{exc}",parent=self.root)
            try:
                if hasattr(self,"db"):self.db.close()
            except Exception:pass
            self.root.destroy();return
        try:
            self.portal_address = portal.start_server()
        except RuntimeError as exc:
            self.portal_address = None
            messagebox.showwarning("Cổng khách thuê", f"Không khởi động được cổng ứng dụng khách thuê.\n{exc}")
        self.style()
        self.build_ui()
        self.month.set(MONTH())
        self.ensure_month(MONTH())
        self.refresh()
        self.retry_unsent(MONTH())
        self.root.after(60_000, self.timer)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(150, self.require_admin)

    def create_tables(self):
        sqlstore.ensure_schema(self.db)
        imported=sqlstore.migrate_legacy(self.db)
        self.db.commit()
        if imported:messagebox.showinfo("Đã chuyển dữ liệu",f"Đã chuyển {imported} bản ghi cũ vào SQL Server. Từ giờ ứng dụng đọc và ghi dữ liệu vận hành trên SQL Server.",parent=self.root)

    def style(self):
        s = ttk.Style(self.root)
        try: s.theme_use("clam")
        except tk.TclError: pass
        # Keep native ttk pages on the same warm, light palette as the dashboard.
        s.configure(".", font=("Segoe UI", 9), background="#f5f7f4", foreground="#26352d")
        s.configure("TFrame", background="#f5f7f4")
        s.configure("TLabel", background="#f5f7f4", foreground="#36473c", padding=2)
        s.configure("TButton", background="white", foreground="#34483c", padding=(12, 8),
                    borderwidth=0, relief="flat", font=("Segoe UI", 9))
        s.map("TButton", background=[("active", "#e8f3ed"), ("pressed", "#d9ebe1")],
              foreground=[("active", "#1d7255")])
        s.configure("Primary.TButton", background="#1d7255", foreground="white",
                    padding=(14, 9), borderwidth=0, font=("Segoe UI", 9, "bold"))
        s.map("Primary.TButton", background=[("active", "#175b44"), ("pressed", "#124a37")],
              foreground=[("active", "white")])
        s.configure("TEntry", fieldbackground="white", foreground="#26352d", padding=7,
                    borderwidth=1, relief="solid")
        s.configure("Treeview", background="white", fieldbackground="white", foreground="#35443b",
                    rowheight=36, font=("Segoe UI", 9), borderwidth=0, relief="flat")
        s.configure("Treeview.Heading", background="#f3f6f3", foreground="#5b695f",
                    font=("Segoe UI", 9, "bold"), padding=(10, 10), relief="flat")
        s.map("Treeview", background=[("selected", "#dcefe4")], foreground=[("selected", "#174c38")])
        s.map("Treeview.Heading", background=[("active", "#eaf0eb")])

    def build_ui(self):
        shell = tk.Frame(self.root, bg="#f5f7f4"); shell.pack(fill="both", expand=True)
        sidebar = tk.Frame(shell, bg="white", width=224, highlightbackground="#e4e9e5", highlightthickness=1)
        sidebar.pack(side="left", fill="y"); sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg="white", padx=17, pady=20); brand.pack(fill="x")
        tk.Label(brand, text="⌂", bg="#1d7255", fg="white", width=2, height=1, font=("Segoe UI",17,"bold")).pack(side="left", padx=(0,10))
        brand_text = tk.Frame(brand, bg="white"); brand_text.pack(side="left")
        tk.Label(brand_text, text="Trọ Nhà", bg="white", fg="#26352d", font=("Segoe UI",14,"bold")).pack(anchor="w")
        tk.Label(brand_text, text="Quản lý vận hành", bg="white", fg="#7a857e", font=("Segoe UI",8)).pack(anchor="w")
        tk.Label(sidebar, text="TỔNG QUAN", bg="white", fg="#9aa39d", font=("Segoe UI",8,"bold"), padx=17, pady=12).pack(anchor="w")
        self.nav_buttons = {}
        self._nav_button(sidebar, "▦", "Bảng điều khiển", "Tổng quan")
        tk.Label(sidebar, text="QUẢN LÝ", bg="white", fg="#9aa39d", font=("Segoe UI",8,"bold"), padx=17, pady=12).pack(anchor="w")
        self._nav_button(sidebar, "⌂", "Phòng trọ", "Phòng trọ")
        self._nav_button(sidebar, "◎", "Khách quan tâm", "Khách quan tâm")
        self._nav_button(sidebar, "▤", "Hợp đồng thuê", "Hợp đồng")
        self._nav_button(sidebar, "▧", "Hóa đơn tháng", "Hóa đơn tháng")
        self._nav_button(sidebar, "◉", "Chỉ số công tơ", "Chỉ số công tơ")
        self._nav_button(sidebar, "₫", "Thu chi", "Thu chi")
        tk.Frame(sidebar, bg="#e8ece8", height=1).pack(side="bottom", fill="x", padx=16, pady=(0,10))
        tk.Label(sidebar, text="Dữ liệu lưu trên SQL Server", bg="white", fg="#87918b", font=("Segoe UI",8), padx=17, pady=8).pack(side="bottom", anchor="w")

        main = tk.Frame(shell, bg="#f5f7f4"); main.pack(side="left", fill="both", expand=True)
        topbar = tk.Frame(main, bg="white", height=58, highlightbackground="#e4e9e5", highlightthickness=1)
        topbar.pack(fill="x"); topbar.pack_propagate(False)
        self.breadcrumb = tk.Label(topbar, text="Quản lý phòng trọ  /  Bảng điều khiển", bg="white", fg="#68746d", font=("Segoe UI",9))
        self.breadcrumb.pack(side="left", padx=22)
        tk.Label(topbar, text=date.today().strftime("%d/%m/%Y"), bg="white", fg="#68746d", font=("Segoe UI",9)).pack(side="right", padx=18)
        self.tabs = PageDeck(main); self.tabs.pack(fill="both", expand=True, padx=18, pady=17)
        self.dashboard_tab(); self.rooms_tab(); self.leads_tab(); self.contracts_tab(); self.invoices_tab(); self.meter_readings_tab(); self.payments_tab()
        self.open_tab("Tổng quan")

    def _nav_button(self, parent, icon, label, tab_name):
        button = tk.Button(parent, text=f"{icon}   {label}", anchor="w", command=lambda n=tab_name:self.open_tab(n),
                           bg="white", fg="#637068", activebackground="#e8f3ed", activeforeground="#1d7255",
                           relief="flat", bd=0, padx=17, pady=11, font=("Segoe UI",10))
        button.pack(fill="x", padx=8, pady=1)
        self.nav_buttons[tab_name] = button

    def table_tab(self, title, cols, actions):
        tab = tk.Frame(self.tabs, bg="#f5f7f4", padx=6, pady=6); self.tabs.add(tab, text=title)
        heading = tk.Frame(tab, bg="#f5f7f4")
        heading.pack(fill="x", pady=(0, 16))
        tk.Label(heading, text=title, bg="#f5f7f4", fg="#26352d",
                 font=("Segoe UI", 19, "bold")).pack(anchor="w")
        tk.Label(heading, text="Theo dõi và cập nhật thông tin trong khu trọ của bạn.",
                 bg="#f5f7f4", fg="#77827b", font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))

        card = tk.Frame(tab, bg="white", highlightbackground="#e2e9e4", highlightthickness=1)
        card.pack(fill="both", expand=True)
        bar = tk.Frame(card, bg="white", padx=14, pady=13)
        bar.pack(fill="x")
        tk.Label(bar, text="Danh sách", bg="white", fg="#27352d",
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=(0, 12))
        for i, (text, fn) in enumerate(actions):
            style = "Primary.TButton" if i == 0 else "TButton"
            ttk.Button(bar, text=text, command=fn, style=style).pack(side="left", padx=(0, 7))
        table_area = tk.Frame(card, bg="white", padx=14, pady=0)
        table_area.pack(fill="both", expand=True)
        tree = ttk.Treeview(table_area, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for key, label, width in cols:
            tree.heading(key, text=label); tree.column(key, width=width, minwidth=60, stretch=True)
        sb = ttk.Scrollbar(table_area, orient="vertical", command=tree.yview); tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        return tree

    def dashboard_tab(self):
        tab = tk.Frame(self.tabs, bg="#f5f7f4", padx=2, pady=2); self.tabs.add(tab, text="Tổng quan")
        top = tk.Frame(tab, bg="#f5f7f4"); top.pack(fill="x", pady=(0,15))
        intro = tk.Frame(top, bg="#f5f7f4"); intro.pack(side="left", fill="x", expand=True)
        tk.Label(intro, text="Xin chào 👋", bg="#f5f7f4", fg="#26352d", font=("Segoe UI",19,"bold")).pack(anchor="w")
        tk.Label(intro, text="Đây là tình hình vận hành khu trọ của bạn hôm nay.", bg="#f5f7f4", fg="#77827b", font=("Segoe UI",10)).pack(anchor="w", pady=(4,0))
        tk.Button(top, text="＋ Thêm khách", command=self.edit_lead, bg="#1d7255", fg="white", activebackground="#175b44", relief="flat", padx=14, pady=8, font=("Segoe UI",9,"bold")).pack(side="right")

        cards = tk.Frame(tab, bg="#f5f7f4"); cards.pack(fill="x", pady=(0,14))
        self.metrics = {}
        for col, (key, title, tint) in enumerate([
            ("rooms", "TỔNG SỐ PHÒNG", "#2f7559"), ("available", "PHÒNG CÒN TRỐNG", "#4d8d6e"),
            ("rented", "ĐANG CHO THUÊ", "#c07d31"), ("income", "TIỀN THUÊ / THÁNG", "#5279a5")]):
            card = tk.Frame(cards, bg="white", highlightbackground="#e2e9e4", highlightthickness=1, padx=15, pady=11)
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col==0 else 9, 0))
            tk.Label(card, text=title, bg="white", fg="#738078", font=("Segoe UI",8,"bold")).pack(anchor="w")
            value = tk.Label(card, text="0", bg="white", fg=tint, font=("Segoe UI",18,"bold")); value.pack(anchor="w", pady=(6,0))
            self.metrics[key] = value
            cards.columnconfigure(col, weight=1, uniform="metric")

        panels = tk.Frame(tab, bg="#f5f7f4"); panels.pack(fill="both", expand=True)
        occupancy = tk.Frame(panels, bg="white", highlightbackground="#e2e9e4", highlightthickness=1, padx=15, pady=13)
        occupancy.pack(side="left", fill="both", expand=True, padx=(0,9))
        title_row = tk.Frame(occupancy,bg="white");title_row.pack(fill="x")
        tk.Label(title_row,text="Tình trạng phòng",bg="white",fg="#27352d",font=("Segoe UI",11,"bold")).pack(side="left")
        tk.Button(title_row,text="Xem danh sách →",command=lambda:self.open_tab("Phòng trọ"),bg="white",fg="#1d7255",relief="flat",font=("Segoe UI",8)).pack(side="right")
        self.room_status = {}
        for status, color in [("Đang thuê","#2d805f"),("Trống","#d69b39"),("Đang sửa","#d26658"),("Đang giữ","#6e8daf")]:
            line=tk.Frame(occupancy,bg="white");line.pack(fill="x",pady=8)
            tk.Label(line,text=status,bg="white",fg="#68746d",width=13,anchor="w",font=("Segoe UI",9)).pack(side="left")
            bar=tk.Canvas(line,height=9,bg="#edf1ee",highlightthickness=0);bar.pack(side="left",fill="x",expand=True,padx=8)
            count_label=tk.Label(line,text="0",bg="white",fg="#526158",width=3,anchor="e",font=("Segoe UI",9,"bold"));count_label.pack(side="right")
            self.room_status[status]=(bar,color,count_label)
        self.empty_hint=tk.Label(occupancy,text="",bg="#fff5df",fg="#775b22",anchor="w",padx=9,pady=8,font=("Segoe UI",9));self.empty_hint.pack(fill="x",pady=(12,0))

        follow = tk.Frame(panels,bg="white",highlightbackground="#e2e9e4",highlightthickness=1,padx=14,pady=13,width=350)
        follow.pack(side="right",fill="both");follow.pack_propagate(False)
        head=tk.Frame(follow,bg="white");head.pack(fill="x")
        tk.Label(head,text="Khách cần theo dõi",bg="white",fg="#27352d",font=("Segoe UI",11,"bold")).pack(side="left")
        tk.Button(head,text="Xem tất cả →",command=lambda:self.open_tab("Khách quan tâm"),bg="white",fg="#1d7255",relief="flat",font=("Segoe UI",8)).pack(side="right")
        self.recent_tree=ttk.Treeview(follow,columns=("name","room","status"),show="headings",height=7)
        for key,label,width in [("name","Khách",120),("room","Phòng",70),("status","Trạng thái",115)]:self.recent_tree.heading(key,text=label);self.recent_tree.column(key,width=width,stretch=True)
        self.recent_tree.pack(fill="both",expand=True,pady=(10,0))

        recent = tk.Frame(tab,bg="white",highlightbackground="#e2e9e4",highlightthickness=1,padx=14,pady=12)
        recent.pack(fill="x",pady=(13,0))
        tk.Label(recent,text="Hợp đồng đang thuê",bg="white",fg="#27352d",font=("Segoe UI",11,"bold")).pack(anchor="w")
        self.active_tree=ttk.Treeview(recent,columns=("id","tenant","room","period","rent"),show="headings",height=3)
        for key,label,width in [("id","Mã hợp đồng",115),("tenant","Khách thuê",150),("room","Phòng",75),("period","Thời hạn",210),("rent","Tiền thuê/tháng",145)]:self.active_tree.heading(key,text=label);self.active_tree.column(key,width=width,stretch=True)
        self.active_tree.pack(fill="x",pady=(8,0))
        self.bill_summary = tk.Label(tab,text="",bg="#f5f7f4",fg="#758078",font=("Segoe UI",8),anchor="w")
        self.bill_summary.pack(fill="x",pady=(8,0))

    def open_tab(self, name):
        for i in range(self.tabs.index("end")):
            if self.tabs.tab(i, "text") == name:
                self.tabs.select(i)
                self.breadcrumb.configure(text=f"Quản lý phòng trọ  /  {name}")
                for key, button in self.nav_buttons.items():
                    button.configure(bg="#e8f3ed" if key == name else "white", fg="#1d7255" if key == name else "#637068")
                return

    def rooms_tab(self):
        tab=tk.Frame(self.tabs,bg="#f5f7f4",padx=6,pady=6);self.tabs.add(tab,text="Phòng trọ")
        heading=tk.Frame(tab,bg="#f5f7f4");heading.pack(fill="x",pady=(0,16))
        tk.Label(heading,text="Phòng trọ",bg="#f5f7f4",fg="#26352d",font=("Segoe UI",19,"bold")).pack(anchor="w")
        tk.Label(heading,text="Xem nhanh ảnh, giá thuê và tình trạng từng phòng.",bg="#f5f7f4",fg="#77827b",font=("Segoe UI",9)).pack(anchor="w",pady=(4,0))
        card=tk.Frame(tab,bg="white",highlightbackground="#e2e9e4",highlightthickness=1);card.pack(fill="both",expand=True)
        bar=tk.Frame(card,bg="white",padx=14,pady=13);bar.pack(fill="x")
        ttk.Label(bar,text="Danh sách phòng").pack(side="left",padx=(0,12))
        for i,(label,fn) in enumerate([("＋ Thêm phòng",lambda:self.edit_room()),("Sửa phòng",self.edit_room_selected),("Xem ảnh",self.open_room_photo),("Xóa phòng",self.delete_room)]):
            ttk.Button(bar,text=label,command=fn,style="Primary.TButton" if i==0 else "TButton").pack(side="left",padx=(0,7))
        area=tk.Frame(card,bg="white");area.pack(fill="both",expand=True,padx=12,pady=(0,12))
        self.room_canvas=tk.Canvas(area,bg="white",highlightthickness=0)
        sb=ttk.Scrollbar(area,orient="vertical",command=self.room_canvas.yview);self.room_canvas.configure(yscrollcommand=sb.set)
        self.room_canvas.pack(side="left",fill="both",expand=True);sb.pack(side="right",fill="y")
        self.room_grid=tk.Frame(self.room_canvas,bg="white");self.room_grid_window=self.room_canvas.create_window((0,0),window=self.room_grid,anchor="nw")
        self.room_grid.bind("<Configure>",lambda _e:self.room_canvas.configure(scrollregion=self.room_canvas.bbox("all")))
        self.room_canvas.bind("<Configure>",self.resize_room_grid)
        self.room_cards={};self.room_images=[];self.selected_room_id=None;self.room_rows=[]

    def resize_room_grid(self,event):
        self.room_canvas.itemconfigure(self.room_grid_window,width=event.width)
        cols=max(1,min(3,event.width//300))
        if cols!=getattr(self,"room_columns",None):
            self.room_columns=cols;self.render_room_cards()

    def select_room_card(self,room_id):
        self.selected_room_id=room_id
        for key,frame in self.room_cards.items():
            chosen=key==room_id
            frame.configure(highlightbackground="#1d7255" if chosen else "#e2e9e4",highlightthickness=2 if chosen else 1)

    def render_room_cards(self):
        if not hasattr(self,"room_grid"):return
        for child in self.room_grid.winfo_children():child.destroy()
        self.room_cards={};self.room_images=[]
        cols=max(1,getattr(self,"room_columns",3))
        for col in range(cols):self.room_grid.columnconfigure(col,weight=1,uniform="room-card")
        for index,row in enumerate(self.room_rows):
            room_id=row["id"];r,c=divmod(index,cols)
            outer=tk.Frame(self.room_grid,bg="white",highlightbackground="#1d7255" if room_id==self.selected_room_id else "#e2e9e4",highlightthickness=2 if room_id==self.selected_room_id else 1,cursor="hand2")
            outer.grid(row=r,column=c,sticky="nsew",padx=7,pady=7);self.room_cards[room_id]=outer
            photo_data=row["photo_data"]
            if photo_data:
                try:
                    from PIL import Image,ImageTk
                    import io
                    image=Image.open(io.BytesIO(bytes(photo_data))).convert("RGB");image.thumbnail((340,170))
                    photo=ImageTk.PhotoImage(image);self.room_images.append(photo)
                    pic=tk.Label(outer,image=photo,bg="#edf2ee",height=170)
                except Exception as exc:
                    pic=tk.Label(outer,text="Không đọc được ảnh",bg="#edf2ee",fg="#829087",height=10,font=("Segoe UI",10))
            else:pic=tk.Label(outer,text="⌂\nChưa có ảnh phòng",bg="#edf2ee",fg="#829087",height=10,font=("Segoe UI",12))
            pic.pack(fill="x")
            detail=tk.Frame(outer,bg="white",padx=14,pady=12);detail.pack(fill="both",expand=True)
            top=tk.Frame(detail,bg="white");top.pack(fill="x")
            tk.Label(top,text=f"Phòng {room_id}",bg="white",fg="#26352d",font=("Segoe UI",13,"bold")).pack(side="left")
            status_color={"Trống":"#9a6917","Đang thuê":"#28714f","Đang sửa":"#b35046","Đang giữ":"#54779a","Cần kiểm tra":"#8b6623"}.get(row["status"],"#65736a")
            tk.Label(top,text=row["status"],bg="#f0f5f1",fg=status_color,padx=8,pady=4,font=("Segoe UI",8,"bold")).pack(side="right")
            tk.Label(detail,text=MONEY(row["rent"])+" / tháng",bg="white",fg="#1d7255",font=("Segoe UI",14,"bold")).pack(anchor="w",pady=(8,4))
            meta="  ·  ".join(x for x in (row["area"] or "",row["floor"] or "",f"{row['size']:g} m²" if row["size"] is not None else "") if x)
            tk.Label(detail,text=meta or "Chưa có thông tin vị trí",bg="white",fg="#718078",font=("Segoe UI",9)).pack(anchor="w")
            if row["note"]:tk.Label(detail,text=row["note"],bg="white",fg="#829087",font=("Segoe UI",8),wraplength=275,justify="left").pack(anchor="w",pady=(7,0))
            for widget in (outer,*outer.winfo_children(),*detail.winfo_children(),*top.winfo_children()):widget.bind("<Button-1>",lambda _e,rid=room_id:self.select_room_card(rid))
        if not self.room_rows:
            tk.Label(self.room_grid,text="Chưa có phòng. Bấm ‘Thêm phòng’ để bắt đầu.",bg="white",fg="#77827b",font=("Segoe UI",11),pady=55).grid(row=0,column=0,columnspan=cols,sticky="nsew")

    def leads_tab(self):
        self.leads = self.table_tab("Khách quan tâm", [("id","Mã",55),("name","Khách",140),("phone","Điện thoại",110),("email","Email",160),("room","Phòng quan tâm",100),("date","Ngày liên hệ",100),("status","Trạng thái",115),("source","Nguồn",90)],
            [("Thêm khách",lambda:self.edit_lead()),("Sửa khách",self.edit_lead_selected),("Cập nhật trạng thái",self.lead_status),("Chốt thuê / tạo hợp đồng",self.convert_lead)])

    def contracts_tab(self):
        self.contracts = self.table_tab("Hợp đồng", [("id","Mã hợp đồng",115),("tenant","Khách thuê",140),("phone","Điện thoại",110),("room","Phòng",75),("start","Bắt đầu",95),("end","Kết thúc",95),("rent","Tiền thuê",110),("deposit","Tiền cọc",100),("status","Trạng thái",105)],
            [("Tạo tài khoản khách thuê",self.create_tenant_account),("Làm thủ tục trả phòng",self.checkout)])

    def invoices_tab(self):
        tab=tk.Frame(self.tabs,bg="#f5f7f4",padx=6,pady=6); self.tabs.add(tab,text="Hóa đơn tháng")
        tk.Label(tab,text="Hóa đơn tháng",bg="#f5f7f4",fg="#26352d",font=("Segoe UI",19,"bold")).pack(anchor="w")
        tk.Label(tab,text="Tạo hóa đơn chi tiết, theo dõi thanh toán và gửi cho khách thuê.",bg="#f5f7f4",fg="#77827b",font=("Segoe UI",9)).pack(anchor="w",pady=(4,16))
        card=tk.Frame(tab,bg="white",highlightbackground="#e2e9e4",highlightthickness=1);card.pack(fill="both",expand=True)
        bar=tk.Frame(card,bg="white",padx=14,pady=13);bar.pack(fill="x")
        ttk.Label(bar,text="Tháng hóa đơn").pack(side="left")
        self.month=tk.StringVar(value=MONTH());ttk.Entry(bar,textvariable=self.month,width=10).pack(side="left",padx=(6,12))
        for text,fn in [("Tải / tạo hóa đơn",self.load_month),("Nhập chỉ số / phí",self.enter_charges),("Đã thu",self.mark_paid),("Gửi email",self.send_selected),("Sao chép",self.copy_invoice),("Cấu hình email",self.email_settings)]:
            ttk.Button(bar,text=text,command=fn,style="Primary.TButton" if text=="Tải / tạo hóa đơn" else "TButton").pack(side="left",padx=3)
        cols=[("id","Mã hóa đơn",165),("tenant","Khách",130),("room","Phòng",65),("month","Tháng",70),("detail","Chi tiết phí",370),("due","Hạn",85),("total","Tổng",100),("status","Thanh toán",105),("mail","Email",90)]
        table_area=tk.Frame(card,bg="white",padx=14,pady=0);table_area.pack(fill="both",expand=True)
        self.inv_tree=ttk.Treeview(table_area,columns=[c[0] for c in cols],show="headings",selectmode="browse")
        for k,l,w in cols:self.inv_tree.heading(k,text=l);self.inv_tree.column(k,width=w,minwidth=60,stretch=True)
        sb=ttk.Scrollbar(table_area,orient="vertical",command=self.inv_tree.yview);self.inv_tree.configure(yscrollcommand=sb.set)
        self.inv_tree.pack(side="left",fill="both",expand=True);sb.pack(side="right",fill="y")

    def meter_readings_tab(self):
        self.meter_tree=self.table_tab("Chỉ số công tơ",[("id","Mã",55),("tenant","Khách",130),("room","Phòng",65),("month","Tháng",85),("utility","Loại",65),("reading","Chỉ số",85),("ocr","OCR gợi ý",95),("usage","Lượng dùng",95),("photo","Ảnh",60),("status","Trạng thái",95),("created","Gửi lúc",145)],
            [("Mở ảnh",self.open_meter_photo),("Làm mới",self.refresh_meter_readings)])

    def payments_tab(self):
        self.payments=self.table_tab("Thu chi",[("id","Mã",55),("date","Ngày",100),("tenant","Khách",135),("room","Phòng",70),("description","Nội dung",210),("amount","Số tiền",110),("note","Ghi chú",220)],[])

    def rows(self, sql, args=()): return self.db.execute(sql,args).fetchall()
    def selected(self, tree):
        sel=tree.selection();return tree.item(sel[0],"values") if sel else None
    def fill(self, tree, rows):
        tree.delete(*tree.get_children())
        for r in rows:tree.insert("","end",values=r)

    def refresh(self):
        room_rows=self.rows("SELECT id,area,floor,size,rent,status,photo_path,photo_data,note FROM rooms ORDER BY id")
        self.room_rows=room_rows
        if hasattr(self,"room_columns"):self.render_room_cards()
        self.fill(self.leads,[tuple(r) for r in self.rows("SELECT id,name,phone,email,room_id,contact_date,status,source FROM leads WHERE status<>N'Đã chốt' ORDER BY id DESC")])
        self.fill(self.contracts,[tuple(r) for r in self.rows("SELECT id,tenant,phone,room_id,start_date,end_date,rent,deposit,status FROM contracts ORDER BY start_date DESC")])
        self.fill(self.payments,[tuple(r) for r in self.rows("SELECT id,date,tenant,room,description,amount,note FROM payments ORDER BY id DESC")])
        self.refresh_invoices()
        if hasattr(self,"meter_tree"): self.refresh_meter_readings()
        counts={r["status"]:r["n"] for r in self.rows("SELECT status,COUNT(*) n FROM rooms GROUP BY status")}
        active=self.rows("SELECT COUNT(*) n,COALESCE(SUM(rent),0) rent FROM contracts WHERE status=N'Đang thuê'")[0]
        self.metrics["rooms"].configure(text=str(sum(counts.values())))
        self.metrics["available"].configure(text=str(counts.get("Trống",0)))
        self.metrics["rented"].configure(text=str(counts.get("Đang thuê",0)))
        self.metrics["income"].configure(text=MONEY(active["rent"]))
        self.empty_hint.configure(text="Chưa có phòng nào. Hãy bấm ‘Thêm phòng’ để bắt đầu." if not counts else f"Đang quản lý {sum(counts.values())} phòng. Chọn một thao tác nhanh hoặc mở tab tương ứng.", bg="#fff5df" if not counts else "#edf6ef", fg="#775b22" if not counts else "#386348")
        self.room_counts = counts
        for status, (bar, color, label) in self.room_status.items():
            label.configure(text=str(counts.get(status, 0)))
        self.root.after_idle(self.draw_room_status)
        self.fill(self.recent_tree, [tuple(r) for r in self.rows("SELECT TOP 7 name,room_id,status FROM leads WHERE status NOT IN (N'Đã chốt',N'Không thuê') ORDER BY id DESC")])
        active_rows=self.rows("SELECT TOP 5 id,tenant,room_id,start_date,end_date,rent FROM contracts WHERE status=N'Đang thuê' ORDER BY start_date DESC")
        self.fill(self.active_tree, [(r["id"],r["tenant"],r["room_id"],f"{r['start_date']} → {r['end_date'] or 'Không thời hạn'}",MONEY(r["rent"])) for r in active_rows])
        m=MONTH();unpaid=self.rows("SELECT COALESCE(SUM(l.amount),0) n FROM invoices i JOIN lines l ON l.invoice_id=i.id WHERE i.month=? AND i.status<>N'Đã thanh toán'",(m,))[0]["n"]
        self.bill_summary.configure(text=f"Tháng {m}\nCòn phải thu: {MONEY(unpaid)}\n\nHóa đơn được tạo tự động khi ứng dụng mở đầu tháng.")

    def draw_room_status(self):
        total=sum(self.room_counts.values()) if hasattr(self,"room_counts") else 0
        for status,(canvas,color,_label) in self.room_status.items():
            canvas.delete("all");width=max(canvas.winfo_width(),1);count=self.room_counts.get(status,0)
            if total and count:canvas.create_rectangle(0,0,width*count/total,9,fill=color,outline="")

    def refresh_invoices(self):
        m=self.month.get().strip() if hasattr(self,"month") else MONTH()
        rows=self.rows("SELECT i.*,c.tenant,c.email,c.room_id FROM invoices i JOIN contracts c ON c.id=i.contract_id WHERE i.month=? ORDER BY c.room_id",(m,))
        result=[]
        for i in rows:
            ls=self.rows("SELECT * FROM lines WHERE invoice_id=? ORDER BY id",(i["id"],));total=sum(x["amount"] for x in ls)
            detail=" | ".join(f"{x['name']}: {MONEY(x['amount'])}"+(f" ({x['qty']:g} {x['unit']} × {MONEY(x['rate'])})" if x["unit"] in ("kWh","m³") else "") for x in ls)
            mail="Đã gửi" if i["email_sent"] else ("Lỗi gửi" if i["email_error"] else ("Chưa có email" if not i["email"] else "Chưa gửi"))
            result.append((i["id"],i["tenant"],i["room_id"],i["month"],detail,i["due"],MONEY(total),i["status"],mail))
        self.fill(self.inv_tree,result)

    def refresh_meter_readings(self):
        rows=self.rows("SELECT x.id,c.tenant,c.room_id,x.month,x.utility,x.reading,x.ocr_reading,x.usage,CASE WHEN x.image_data IS NULL THEN N'—' ELSE N'Có ảnh' END AS photo,x.status,x.created_at FROM meter_readings x JOIN contracts c ON c.id=x.contract_id ORDER BY CASE x.status WHEN 'Chờ duyệt' THEN 0 ELSE 1 END,x.month DESC,x.id DESC")
        self.fill(self.meter_tree,[(r["id"],r["tenant"],r["room_id"],r["month"],r["utility"],r["reading"],r["ocr_reading"] if r["ocr_reading"] is not None else "—",r["usage"] if r["usage"] is not None else "Lần đầu",r["photo"],r["status"],r["created_at"]) for r in rows])

    def selected_meter(self):
        row=self.selected(self.meter_tree)
        return self.db.execute("SELECT x.*,c.tenant,c.room_id,c.email FROM meter_readings x JOIN contracts c ON c.id=x.contract_id WHERE x.id=?",(row[0],)).fetchone() if row else None

    def open_meter_photo(self):
        row=self.selected_meter()
        if not row:return messagebox.showinfo("Chỉ số công tơ","Chọn một dòng chỉ số trước.")
        if not row["image_data"]:return messagebox.showwarning("Không tìm thấy ảnh","Bản ghi này chưa có ảnh trong SQL Server.")
        path=self.write_temp_image(row["image_data"],row["image_mime"] or "image/jpeg")
        try:os.startfile(str(path))
        except OSError as exc:messagebox.showerror("Không mở được ảnh",str(exc))

    def write_temp_image(self,data,mime):
        suffix={"image/jpeg":".jpg","image/png":".png","image/webp":".webp","image/gif":".gif","image/bmp":".bmp"}.get(mime,".img")
        handle=tempfile.NamedTemporaryFile(prefix="tro-nha-",suffix=suffix,delete=False)
        handle.write(bytes(data));handle.close();path=Path(handle.name);self.temp_images.append(path);return path

    def approve_meter_reading(self):
        row=self.selected_meter()
        if not row:return messagebox.showinfo("Chỉ số công tơ","Chọn chỉ số cần duyệt.")
        if row["status"]!="Chờ duyệt":return messagebox.showinfo("Chỉ số công tơ","Chỉ số này đã được xử lý.")
        prior_invoice=self.db.execute("SELECT status FROM invoices WHERE contract_id=? AND month=?",(row["contract_id"],row["month"])).fetchone()
        if prior_invoice and prior_invoice["status"]=="Đã thanh toán":return messagebox.showwarning("Đã thanh toán","Hóa đơn tháng này đã được thanh toán; không thể thay đổi chỉ số đã chốt.")
        if not messagebox.askyesno("Duyệt chỉ số",f"Xác nhận {row['utility'].lower()} phòng {row['room_id']}: {row['reading']}?"):return
        previous=self.db.execute("SELECT TOP 1 reading FROM meter_readings WHERE contract_id=? AND utility=? AND status=N'Đã duyệt' AND month<? ORDER BY month DESC",(row["contract_id"],row["utility"],row["month"])).fetchone()
        prev=previous[0] if previous else None
        usage=float(row["reading"])-(float(prev) if prev is not None else float(row["reading"]))
        if usage<0:return messagebox.showerror("Chỉ số không hợp lệ","Chỉ số mới thấp hơn lần đã duyệt gần nhất.")
        self.db.execute("UPDATE meter_readings SET previous_reading=?,usage=?,status=N'Đã duyệt',reviewed_at=? WHERE id=?",(prev,usage,datetime.now().isoformat(timespec="minutes"),row["id"]))
        self.ensure_month(row["month"])
        inv=self.db.execute("SELECT id FROM invoices WHERE contract_id=? AND month=?",(row["contract_id"],row["month"])).fetchone()
        if inv:
            ch=self.db.execute("SELECT * FROM charges WHERE contract_id=? AND month=?",(row["contract_id"],row["month"])).fetchone()
            if row["utility"]=="Điện":self.db.execute("UPDATE charges SET electric=?,electric_rate=COALESCE(NULLIF(electric_rate,0),(SELECT electric_rate FROM rooms WHERE id=?)) WHERE contract_id=? AND month=?",(usage,row["room_id"],row["contract_id"],row["month"]))
            else:self.db.execute("UPDATE charges SET water=?,water_rate=COALESCE(NULLIF(water_rate,0),(SELECT water_rate FROM rooms WHERE id=?)) WHERE contract_id=? AND month=?",(usage,row["room_id"],row["contract_id"],row["month"]))
            approved=self.db.execute("SELECT COUNT(*) FROM meter_readings WHERE contract_id=? AND month=? AND status=N'Đã duyệt'",(row["contract_id"],row["month"])).fetchone()[0]
            self.recalc_invoice(inv["id"])
            if approved<2:self.db.execute("UPDATE invoices SET status=N'Thiếu chỉ số' WHERE id=?",(inv["id"],))
            else:
                self.notify_tenant_invoice(inv["id"],True)
                if self.setting("auto_send")=="1":self.send_invoice(inv["id"],True)
        self.db.commit();self.refresh()

    def reject_meter_reading(self):
        row=self.selected_meter()
        if not row:return messagebox.showinfo("Chỉ số công tơ","Chọn chỉ số cần từ chối.")
        reason=simpledialog.askstring("Từ chối chỉ số","Lý do (sẽ gửi thông báo cho khách):",parent=self.root)
        if reason is None:return
        self.db.execute("UPDATE meter_readings SET status=N'Cần gửi lại',reviewed_at=? WHERE id=?",(datetime.now().isoformat(timespec="minutes"),row["id"]))
        tenant=self.db.execute("SELECT id FROM users WHERE role='tenant' AND contract_id=? AND active=1",(row["contract_id"],)).fetchone()
        if tenant:portal._notify(self.db,tenant[0],"Cần gửi lại ảnh công tơ",reason.strip() or f"Ảnh {row['utility'].lower()} phòng {row['room_id']} chưa đủ rõ, vui lòng gửi lại.")
        self.db.commit();self.refresh()

    def require_admin(self):
        admins=self.db.execute("SELECT id FROM users WHERE role='admin' AND active=1").fetchone()
        if not admins:
            username=simpledialog.askstring("Thiết lập quản trị viên","Tạo tên đăng nhập admin:",parent=self.root)
            if not username:self.root.destroy();return
            password=simpledialog.askstring("Thiết lập quản trị viên","Tạo mật khẩu admin (tối thiểu 10 ký tự):",show="*",parent=self.root)
            if not password or len(password)<10:
                messagebox.showerror("Mật khẩu chưa đạt","Mật khẩu cần có ít nhất 10 ký tự.");self.root.destroy();return
            self.db.execute("INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)",(username.strip().lower(),"Quản trị viên",portal.hash_password(password),"admin",datetime.now().isoformat(timespec="minutes")));self.db.commit()
        for attempt in range(3):
            username=simpledialog.askstring("Đăng nhập quản trị","Tên đăng nhập admin:",parent=self.root)
            password=simpledialog.askstring("Đăng nhập quản trị","Mật khẩu:",show="*",parent=self.root)
            row=self.db.execute("SELECT * FROM users WHERE username=? AND role='admin' AND active=1",((username or "").strip().lower(),)).fetchone()
            if row and portal.check_password(password or "",row["password_hash"]):
                self.root.title("Trọ Nhà — Quản lý phòng trọ · Admin")
                self.show_portal_address()
                self.watch_code_changes()
                return
            messagebox.showerror("Đăng nhập thất bại","Thông tin admin chưa đúng.")
        self.root.destroy()

    def show_portal_address(self):
        if not self.portal_address:return
        import socket
        try:
            sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.connect(("8.8.8.8",80));ip=sock.getsockname()[0];sock.close()
        except OSError:ip="<IP-máy-tính>"
        messagebox.showinfo("Cổng khách thuê đã sẵn sàng",f"Kết nối điện thoại vào cùng Wi-Fi với máy tính, rồi mở:\n\nhttp://{ip}:8765\n\nKhách đăng nhập bằng tài khoản bạn tạo trong tab Hợp đồng.")

    def read_code_snapshot(self):
        snapshot={}
        for name in ("app.py","server.py","database.py"):
            path=ROOT_DIR/name
            try:
                stat=path.stat();snapshot[name]=(stat.st_mtime_ns,stat.st_size)
            except OSError:snapshot[name]=None
        return snapshot

    def watch_code_changes(self):
        current=self.read_code_snapshot()
        if current==self.code_snapshot:
            self.code_candidate=None;self.code_candidate_stable=0
        elif current==self.code_candidate:
            self.code_candidate_stable+=1
            if self.code_candidate_stable>=2:
                try:
                    for name in ("app.py","server.py","database.py"):
                        path=ROOT_DIR/name
                        if path.exists():compile(path.read_text(encoding="utf-8"),str(path),"exec")
                except (OSError,SyntaxError) as exc:
                    self.code_snapshot=current;self.code_candidate=None;self.code_candidate_stable=0
                    messagebox.showerror("Chưa thể cập nhật",f"Có lỗi cú pháp trong mã nguồn nên ứng dụng vẫn giữ phiên bản đang chạy.\n\n{exc}",parent=self.root)
                else:
                    if self.root.grab_current() is not None:
                        self.root.after(1200,self.watch_code_changes);return
                    self.code_snapshot=current;self.code_candidate=None;self.code_candidate_stable=0
                    messagebox.showinfo("Ứng dụng đã được cập nhật","Mã nguồn mới đã lưu. Trọ Nhà sẽ tự khởi động lại để nạp thay đổi.",parent=self.root)
                    self.root.after(600,self.restart_for_code_update);return
        else:
            self.code_candidate=current;self.code_candidate_stable=0
        self.root.after(1200,self.watch_code_changes)

    def restart_for_code_update(self):
        try:self.db.commit()
        except Exception:pass
        try:self.db.close()
        except Exception:pass
        try:portal.stop_server()
        except Exception:pass
        for path in self.temp_images:
            try:path.unlink(missing_ok=True)
            except OSError:pass
        self.root.destroy()
        os.execv(sys.executable,[sys.executable,*sys.argv])

    def create_tenant_account(self):
        selected=self.selected(self.contracts)
        if not selected:return messagebox.showinfo("Tài khoản khách thuê","Chọn hợp đồng trước.")
        contract=self.db.execute("SELECT * FROM contracts WHERE id=?",(selected[0],)).fetchone()
        if contract["status"]!="Đang thuê":return messagebox.showwarning("Hợp đồng không hoạt động","Chỉ tạo tài khoản cho hợp đồng đang thuê.")
        state,username=self.ensure_tenant_account(contract["id"],contract["tenant"],contract["phone"])
        self.db.commit()
        if state=="created":messagebox.showinfo("Đã tạo tài khoản",f"Tên đăng nhập: {username}\nMật khẩu mặc định: {DEFAULT_TENANT_PASSWORD}\n\nKhách có thể đổi mật khẩu sau khi đăng nhập.")
        elif state=="existing":messagebox.showinfo("Tài khoản đã có",f"Hợp đồng này đã có tài khoản: {username}.")
        elif state=="missing_phone":messagebox.showwarning("Thiếu số điện thoại hợp lệ","Không thể tạo tài khoản. Hãy kiểm tra số điện thoại trong hợp đồng.")
        else:messagebox.showwarning("Số điện thoại đã được dùng",f"Số {username} đang thuộc một tài khoản khác đang hoạt động.")

    def form(self,title,fields):
        has_photo=any(item[0]=="photo_path" for item in fields)
        win=tk.Toplevel(self.root);win.title(title);win.transient(self.root);win.grab_set();win.geometry(f"{'780' if has_photo else '540'}x{min(720,180+len(fields)*43)}");win.minsize(480,220)
        frame=ttk.Frame(win,padding=16);frame.pack(fill="both",expand=True);controls={};preview_label=None
        if has_photo:
            preview_card=tk.Frame(frame,bg="white",highlightbackground="#dfe7e1",highlightthickness=1,width=200,height=190)
            preview_card.grid(row=0,column=3,rowspan=len(fields),sticky="n",padx=(18,0),pady=6);preview_card.grid_propagate(False)
            preview_label=tk.Label(preview_card,text="Chưa chọn ảnh",bg="white",fg="#7a857e",font=("Segoe UI",9),wraplength=170)
            preview_label.pack(fill="both",expand=True,padx=8,pady=8)

        def show_preview(path):
            if not preview_label:return
            if not path or not os.path.isfile(path):
                preview_label.configure(image="",text="Chưa chọn ảnh");preview_label.image=None;return
            try:
                try:
                    from PIL import Image, ImageTk
                    image=Image.open(path);image.thumbnail((180,170));photo=ImageTk.PhotoImage(image)
                except ImportError:
                    photo=tk.PhotoImage(file=path)
                    factor=max(1,(photo.width()+179)//180,(photo.height()+169)//170)
                    if factor>1:photo=photo.subsample(factor,factor)
                preview_label.configure(image=photo,text="");preview_label.image=photo;win.preview_image=photo
            except Exception:
                preview_label.configure(image="",text=f"Đã chọn ảnh:\n{Path(path).name}\n\nCài Pillow để xem ảnh JPG trong ứng dụng.")
                preview_label.image=None

        for n,item in enumerate(fields):
            key,label,value,*rest=item;choices=rest[0] if rest else None;secret=rest[1] if len(rest)>1 else False
            ttk.Label(frame,text=label).grid(row=n,column=0,sticky="w",padx=(0,10),pady=5)
            if choices is not None:
                ctl=ttk.Combobox(frame,values=choices,state="readonly",width=36);ctl.set(value if value in choices else (choices[0] if choices else ""))
            else:ctl=ttk.Entry(frame,width=39,show="*" if secret else "");ctl.insert(0,str(value))
            ctl.grid(row=n,column=1,sticky="ew",pady=5);controls[key]=ctl
            if key=="photo_path":
                ttk.Button(frame,text="Chọn ảnh…",command=lambda c=ctl: self.choose_room_photo(c,show_preview)).grid(row=n,column=2,padx=(6,0))
                show_preview(value)
        frame.columnconfigure(1,weight=1);out={}
        def save():
            out.update({k:c.get().strip() for k,c in controls.items()});win.destroy()
        buttons=ttk.Frame(frame);buttons.grid(row=len(fields),column=0,columnspan=2,sticky="e",pady=(14,0))
        ttk.Button(buttons,text="Hủy",command=win.destroy).pack(side="right",padx=4);ttk.Button(buttons,text="Lưu",command=save).pack(side="right")
        win.bind("<Return>",lambda _e:save());self.root.wait_window(win);return out or None

    def edit_room(self, room_id=None):
        old=self.db.execute("SELECT * FROM rooms WHERE id=?",(room_id,)).fetchone() if room_id else None
        v=self.form("Thông tin phòng và chi phí",[("id","Mã phòng *",old["id"] if old else ""),("area","Khu trọ",old["area"] if old else "Khu A"),("floor","Tầng",old["floor"] if old else "Tầng 1"),("size","Diện tích m²",old["size"] if old else "20"),("rent","Giá thuê/tháng *",old["rent"] if old else ""),("status","Tình trạng",old["status"] if old else "Trống",["Trống","Đang giữ","Đang thuê","Đang sửa","Cần kiểm tra"]),("electric_rate","Đơn giá điện/kWh",old["electric_rate"] if old else "0"),("water_rate","Đơn giá nước/m³",old["water_rate"] if old else "0"),("internet_fee","Internet/tháng",old["internet_fee"] if old else "0"),("service_fee","Phí dịch vụ/tháng",old["service_fee"] if old else "0"),("parking_fee","Phí gửi xe/tháng",old["parking_fee"] if old else "0"),("photo_path","Ảnh phòng",old["photo_path"] if old else ""),("note","Ghi chú",old["note"] if old else "")])
        if not v:return
        try:
            size=float(v["size"] or 0);rent=float(v["rent"])
            rates=[float(v[k] or 0) for k in ("electric_rate","water_rate","internet_fee","service_fee","parking_fee")]
            assert v["id"] and (not old or v["id"]==room_id) and min([size,rent,*rates])>=0
        except (ValueError,AssertionError):return messagebox.showerror("Thông tin chưa hợp lệ","Nhập số không âm cho giá thuê, diện tích và các đơn giá; mã phòng không thể đổi sau khi tạo.")
        photo_path=(v["photo_path"] or "").strip();photo_data=old["photo_data"] if old else None;photo_mime=old["photo_mime"] if old else None
        if photo_path and os.path.isfile(photo_path):
            import mimetypes
            photo_data=Path(photo_path).read_bytes();photo_mime=mimetypes.guess_type(photo_path)[0] or "image/jpeg";photo_path=Path(photo_path).name
        elif old and photo_path==old["photo_path"]:
            pass
        else:photo_path="";photo_data=None;photo_mime=None
        exists=self.db.execute("SELECT 1 FROM rooms WHERE id=?",(v["id"],)).fetchone()
        values=(v["area"],v["floor"],size,rent,v["status"],v["note"],photo_path,*rates,photo_data,photo_mime,v["id"])
        if exists:self.db.execute("UPDATE rooms SET area=?,floor=?,size=?,rent=?,status=?,note=?,photo_path=?,electric_rate=?,water_rate=?,internet_fee=?,service_fee=?,parking_fee=?,photo_data=?,photo_mime=? WHERE id=?",values)
        else:self.db.execute("INSERT INTO rooms(area,floor,size,rent,status,note,photo_path,electric_rate,water_rate,internet_fee,service_fee,parking_fee,photo_data,photo_mime,id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",values)
        self.db.commit();self.refresh()

    def choose_room_photo(self, control, preview):
        path=filedialog.askopenfilename(title="Chọn ảnh phòng",filetypes=[("Ảnh phòng","*.png *.jpg *.jpeg *.gif *.bmp"),("Tất cả tệp","*.*")])
        if path:
            control.delete(0,"end");control.insert(0,path);preview(path)

    def open_room_photo(self):
        room_id=self.selected_room_id
        if not room_id:return messagebox.showinfo("Ảnh phòng","Hãy chọn một thẻ phòng trước.")
        row=self.db.execute("SELECT photo_data,photo_mime FROM rooms WHERE id=?",(room_id,)).fetchone()
        if not row or not row["photo_data"]:return messagebox.showinfo("Ảnh phòng","Phòng này chưa có ảnh trong SQL Server.")
        path=self.write_temp_image(row["photo_data"],row["photo_mime"] or "image/jpeg")
        try:os.startfile(path)
        except OSError as exc:messagebox.showerror("Không mở được ảnh",str(exc))

    def edit_room_selected(self):
        if not self.selected_room_id:return messagebox.showinfo("Trọ Nhà","Chọn thẻ phòng trước.")
        self.edit_room(self.selected_room_id)

    def delete_room(self):
        room_id=self.selected_room_id
        if not room_id:return messagebox.showinfo("Trọ Nhà","Chọn thẻ phòng trước.")
        if self.db.execute("SELECT 1 FROM contracts WHERE room_id=? AND status=N'Đang thuê'",(room_id,)).fetchone():return messagebox.showwarning("Không thể xóa","Phòng đang có hợp đồng.")
        if messagebox.askyesno("Xác nhận",f"Xóa phòng {room_id}?"):self.db.execute("DELETE FROM rooms WHERE id=?",(room_id,));self.db.commit();self.selected_room_id=None;self.refresh()

    def edit_lead(self, lead_id=None):
        old=self.db.execute("SELECT * FROM leads WHERE id=?",(lead_id,)).fetchone() if lead_id else None
        room_options=[r[0] for r in self.rows("SELECT id FROM rooms WHERE status=N'Trống' ORDER BY id")];old_room=old["room_id"] if old else ""
        if old_room and old_room not in room_options:room_options.insert(0,old_room)
        room_options.insert(0,"");statuses=["Mới liên hệ","Đã tư vấn","Đã hẹn xem","Đã xem","Đang cân nhắc","Đã chốt","Không thuê"]
        v=self.form("Khách quan tâm",[("name","Họ tên *",old["name"] if old else ""),("phone","Điện thoại *",old["phone"] if old else ""),("email","Email hóa đơn",old["email"] if old else ""),("room","Phòng quan tâm",old_room,room_options),("date","Ngày liên hệ",old["contact_date"] if old else TODAY()),("status","Trạng thái",old["status"] if old else statuses[0],statuses),("source","Nguồn khách",old["source"] if old else ""),("note","Ghi chú",old["note"] if old else "")])
        if not v:return
        if not v["name"] or not v["phone"]:return messagebox.showerror("Thiếu thông tin","Nhập họ tên và số điện thoại.")
        room=self.db.execute("SELECT status FROM rooms WHERE id=?",(v["room"],)).fetchone() if v["room"] else None
        if v["status"] in ("Đã hẹn xem","Đã xem") and (not room or room["status"]!="Trống"):return messagebox.showwarning("Phòng không trống","Chỉ có thể xem phòng đang trống.")
        if old:self.db.execute("UPDATE leads SET name=?,phone=?,email=?,room_id=?,contact_date=?,status=?,source=?,note=? WHERE id=?",(v["name"],v["phone"],v["email"],v["room"],v["date"],v["status"],v["source"],v["note"],lead_id))
        else:self.db.execute("INSERT INTO leads(name,phone,email,room_id,contact_date,status,source,note) VALUES(?,?,?,?,?,?,?,?)",(v["name"],v["phone"],v["email"],v["room"],v["date"],v["status"],v["source"],v["note"]))
        self.db.commit();self.refresh()

    def edit_lead_selected(self):
        r=self.selected(self.leads)
        if not r:return messagebox.showinfo("Trọ Nhà","Chọn khách trước.")
        self.edit_lead(int(r[0]))

    def lead_status(self):
        r=self.selected(self.leads)
        if not r:return messagebox.showinfo("Trọ Nhà","Chọn khách trước.")
        lead=self.db.execute("SELECT * FROM leads WHERE id=?",(r[0],)).fetchone()
        opts=["Mới liên hệ","Đã tư vấn","Đã hẹn xem","Đã xem","Đang cân nhắc","Không thuê"]
        v=self.form("Cập nhật trạng thái",[("status","Trạng thái",lead["status"],opts)])
        if not v:return
        room=self.db.execute("SELECT status FROM rooms WHERE id=?",(lead["room_id"],)).fetchone()
        if v["status"] in ("Đã hẹn xem","Đã xem") and (not room or room["status"]!="Trống"):return messagebox.showwarning("Phòng không trống","Không thể hẹn xem phòng đã thuê/giữ.")
        self.db.execute("UPDATE leads SET status=? WHERE id=?",(v["status"],lead["id"]));self.db.commit();self.refresh()

    def convert_lead(self):
        r=self.selected(self.leads)
        if not r:return messagebox.showinfo("Trọ Nhà","Chọn khách cần chốt.")
        lead=self.db.execute("SELECT * FROM leads WHERE id=?",(r[0],)).fetchone()
        room=self.db.execute("SELECT * FROM rooms WHERE id=? AND status=N'Trống'",(lead["room_id"],)).fetchone() if lead["room_id"] else None
        if not room:
            room_options=[x[0] for x in self.rows("SELECT id FROM rooms WHERE status=N'Trống' ORDER BY id")]
            if not room_options:return messagebox.showwarning("Chưa có phòng trống","Hãy thêm phòng hoặc chuyển trạng thái một phòng sang Trống trước khi chốt hợp đồng.")
            chosen=self.form("Chọn phòng cho khách",[("room","Phòng trống",room_options[0],room_options)])
            if not chosen:return
            room=self.db.execute("SELECT * FROM rooms WHERE id=? AND status=N'Trống'",(chosen["room"],)).fetchone()
            if not room:return messagebox.showwarning("Phòng vừa được chọn đã có khách","Tải lại danh sách rồi chọn một phòng khác.")
        v=self.form("Xác nhận chốt thuê",[("start","Ngày bắt đầu YYYY-MM-DD",TODAY()),("end","Ngày kết thúc nếu có",""),("rent","Tiền thuê/tháng",room["rent"]),("deposit","Tiền cọc",room["rent"]),("due","Ngày đến hạn",5)])
        if not v:return
        try:
            datetime.strptime(v["start"],"%Y-%m-%d");rent=float(v["rent"]);deposit=float(v["deposit"]);due=max(1,min(28,int(v["due"])))
            if v["end"]:datetime.strptime(v["end"],"%Y-%m-%d")
        except ValueError:return messagebox.showerror("Thông tin chưa hợp lệ","Kiểm tra ngày, giá thuê, tiền cọc và ngày đến hạn.")
        cid="HD-"+datetime.now().strftime("%y%m%d%H%M%S")
        self.db.execute("INSERT INTO contracts VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cid,lead["name"],lead["phone"],lead["email"],room["id"],v["start"],v["end"],rent,deposit,due,"Đang thuê"))
        self.db.execute("UPDATE rooms SET status=N'Đang thuê' WHERE id=?",(room["id"],));self.db.execute("UPDATE leads SET room_id=?,status=N'Đã chốt' WHERE id=?",(room["id"],lead["id"]))
        account_state,username=self.ensure_tenant_account(cid,lead["name"],lead["phone"])
        self.db.commit();self.ensure_month(MONTH());self.refresh()
        if account_state=="created":messagebox.showinfo("Đã chốt hợp đồng",f"Đã tạo tài khoản khách thuê.\n\nTên đăng nhập: {username}\nMật khẩu mặc định: {DEFAULT_TENANT_PASSWORD}\n\nKhách có thể đổi mật khẩu sau khi đăng nhập.")
        elif account_state=="existing":messagebox.showinfo("Đã chốt hợp đồng",f"Khách đã có tài khoản cho hợp đồng này: {username}.")
        elif account_state=="missing_phone":messagebox.showwarning("Thiếu số điện thoại hợp lệ","Hợp đồng đã tạo nhưng chưa tạo được tài khoản. Hãy kiểm tra số điện thoại khách có chứa chữ số.")
        else:messagebox.showwarning("Hợp đồng đã tạo, cần xử lý tài khoản",f"Không thể tự tạo tài khoản vì số điện thoại {username} đã gắn với một tài khoản khác đang hoạt động. Hãy xử lý tài khoản đó trong tab Hợp đồng.")

    def ensure_tenant_account(self,contract_id,tenant,phone):
        username=re.sub(r"\D","",str(phone or ""))
        if not username:return "missing_phone",""
        existing=self.db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
        if existing:
            if existing["role"]!="tenant":return "conflict",username
            if existing["contract_id"]==contract_id:return "existing",username
            linked=self.db.execute("SELECT status FROM contracts WHERE id=?",(existing["contract_id"],)).fetchone() if existing["contract_id"] else None
            if linked and linked["status"]=="Đang thuê":return "conflict",username
            self.db.execute("UPDATE users SET display_name=?,password_hash=?,contract_id=?,active=1 WHERE id=?",(tenant,portal.hash_password(DEFAULT_TENANT_PASSWORD),contract_id,existing["id"]))
            return "created",username
        self.db.execute("INSERT INTO users(username,display_name,password_hash,role,contract_id,created_at) VALUES(?,?,?,?,?,?)",(username,tenant,portal.hash_password(DEFAULT_TENANT_PASSWORD),"tenant",contract_id,datetime.now().isoformat(timespec="minutes")))
        return "created",username

    def checkout(self):
        r=self.selected(self.contracts)
        if not r:return messagebox.showinfo("Trọ Nhà","Chọn hợp đồng trước.")
        c=self.db.execute("SELECT * FROM contracts WHERE id=?",(r[0],)).fetchone()
        if c["status"]!="Đang thuê":return messagebox.showinfo("Trọ Nhà","Hợp đồng này đã kết thúc.")
        v=self.form("Làm thủ tục trả phòng",[("date","Ngày trả phòng",TODAY()),("deduct","Khấu trừ tiền cọc",0),("note","Ghi chú tình trạng phòng","")])
        if not v:return
        try:deduct=max(0,float(v["deduct"] or 0))
        except ValueError:return messagebox.showerror("Thông tin chưa hợp lệ","Khấu trừ phải là số.")
        refund=max(0,c["deposit"]-deduct)
        self.db.execute("UPDATE contracts SET status=N'Đã trả phòng',end_date=? WHERE id=?",(v["date"],c["id"]))
        self.db.execute("UPDATE rooms SET status=N'Cần kiểm tra' WHERE id=?",(c["room_id"],))
        self.db.execute("INSERT INTO payments(date,tenant,room,description,amount,note) VALUES(?,?,?,?,?,?)",(v["date"],c["tenant"],c["room_id"],"Hoàn cọc dự kiến (chờ xử lý)",refund,f"Khấu trừ {MONEY(deduct)}. {v['note']}"))
        self.db.commit();self.refresh();messagebox.showinfo("Đã ghi nhận",f"Tiền cọc dự kiến hoàn: {MONEY(refund)}. Phòng chuyển sang Cần kiểm tra.")

    def valid_month(self):
        m=self.month.get().strip()
        try:datetime.strptime(m,"%Y-%m");return m
        except ValueError:messagebox.showerror("Tháng không hợp lệ","Nhập theo dạng YYYY-MM, ví dụ 2026-11.");return None

    def load_month(self):
        m=self.valid_month()
        if m:self.ensure_month(m);self.refresh_invoices()

    def ensure_month(self,m):
        try:datetime.strptime(m,"%Y-%m")
        except ValueError:return
        first=f"{m}-01";last=f"{m}-{calendar.monthrange(int(m[:4]),int(m[5:7]))[1]:02d}"
        for c in self.rows("SELECT * FROM contracts WHERE status=N'Đang thuê'"):
            if c["start_date"]>last or (c["end_date"] and c["end_date"]<first):continue
            found=self.db.execute("SELECT id FROM invoices WHERE contract_id=? AND month=?",(c["id"],m)).fetchone()
            if found:iid=found["id"]
            else:
                iid=f"HD-{m.replace('-','')}-{c['room_id']}-{c['id'][-4:]}";due=f"{m}-{max(1,min(28,int(c['due_day'] or 5))):02d}"
                self.db.execute("INSERT INTO invoices(id,contract_id,month,due,status) VALUES(?,?,?,?,?)",(iid,c["id"],m,due,"Thiếu chỉ số"))
                self.db.executemany("INSERT INTO lines(invoice_id,name,qty,unit,rate,amount) VALUES(?,?,?,?,?,?)",[(iid,"Tiền thuê phòng",1,"tháng",c["rent"],c["rent"]),(iid,"Điện",0,"kWh",0,0),(iid,"Nước",0,"m³",0,0)])
            invoice=self.db.execute("SELECT status FROM invoices WHERE id=?",(iid,)).fetchone()
            has_charges=self.db.execute("SELECT 1 FROM charges WHERE contract_id=? AND month=?",(c["id"],m)).fetchone()
            if not has_charges and invoice["status"]!="Đã thanh toán":
                room=self.db.execute("SELECT * FROM rooms WHERE id=?",(c["room_id"],)).fetchone()
                self.db.execute("INSERT INTO charges(contract_id,month,electric,electric_rate,water,water_rate,internet,service,parking,other_name,other) VALUES(?,?,0,?,0,?,?,?,?,'Phí khác',0)",(c["id"],m,room["electric_rate"] or 0,room["water_rate"] or 0,room["internet_fee"] or 0,room["service_fee"] or 0,room["parking_fee"] or 0))
                self.db.commit();self.recalc_invoice(iid)
                if not found:self.db.execute("UPDATE invoices SET status=N'Thiếu chỉ số' WHERE id=?",(iid,))
        self.db.commit();self.refresh_invoices();self.retry_unsent(m)

    def recalc_invoice(self,iid):
        inv=self.db.execute("SELECT * FROM invoices WHERE id=?",(iid,)).fetchone()
        if not inv or inv["status"]=="Đã thanh toán":return
        c=self.db.execute("SELECT * FROM contracts WHERE id=?",(inv["contract_id"],)).fetchone()
        ch=self.db.execute("SELECT * FROM charges WHERE contract_id=? AND month=?",(inv["contract_id"],inv["month"])).fetchone()
        if not ch:return
        lines=[("Tiền thuê phòng",1,"tháng",c["rent"],c["rent"]),("Điện",ch["electric"],"kWh",ch["electric_rate"],ch["electric"]*ch["electric_rate"]),("Nước",ch["water"],"m³",ch["water_rate"],ch["water"]*ch["water_rate"])]
        for name,amt in [("Internet",ch["internet"]),("Phí dịch vụ/quản lý",ch["service"]),("Phí gửi xe",ch["parking"]),(ch["other_name"] or "Phí khác",ch["other"])]:
            if amt>0:lines.append((name,1,"khoản",amt,amt))
        self.db.execute("DELETE FROM lines WHERE invoice_id=?",(iid,));self.db.executemany("INSERT INTO lines(invoice_id,name,qty,unit,rate,amount) VALUES(?,?,?,?,?,?)",[(iid,*x) for x in lines])
        self.db.execute("UPDATE invoices SET status=N'Chưa thanh toán',email_error='' WHERE id=?",(iid,));self.db.commit()

    def selected_invoice(self):
        r=self.selected(self.inv_tree)
        return self.db.execute("SELECT i.*,c.tenant,c.email,c.room_id FROM invoices i JOIN contracts c ON c.id=i.contract_id WHERE i.id=?",(r[0],)).fetchone() if r else None

    def notify_tenant_invoice(self,iid,complete=True):
        inv=self.db.execute("SELECT i.*,c.room_id FROM invoices i JOIN contracts c ON c.id=i.contract_id WHERE i.id=?",(iid,)).fetchone()
        if not inv:return
        tenant=self.db.execute("SELECT id FROM users WHERE role='tenant' AND contract_id=? AND active=1",(inv["contract_id"],)).fetchone()
        if not tenant:return
        total=self.db.execute("SELECT COALESCE(SUM(amount),0) FROM lines WHERE invoice_id=?",(iid,)).fetchone()[0]
        title="Hóa đơn đã sẵn sàng" if complete else "Hóa đơn tạm tính đã cập nhật"
        body=(f"Hóa đơn tháng {inv['month']} phòng {inv['room_id']} đã được gửi vào ứng dụng. Tổng cộng {MONEY(total)}; hạn thanh toán {inv['due']}."
              if complete else f"Hóa đơn tạm tính tháng {inv['month']} phòng {inv['room_id']} vừa được cập nhật: {MONEY(total)}. Mở ứng dụng để xem chi tiết.")
        portal._notify(self.db,tenant["id"],title,body)

    def enter_charges(self):
        m=self.valid_month()
        if not m:return
        inv=self.selected_invoice()
        if not inv:self.ensure_month(m);inv=self.selected_invoice()
        if not inv:return messagebox.showinfo("Hóa đơn","Chọn hóa đơn trong danh sách.")
        if inv["status"]=="Đã thanh toán":return messagebox.showwarning("Đã thanh toán","Không thể sửa hóa đơn đã thu.")
        old=self.db.execute("SELECT * FROM charges WHERE contract_id=? AND month=?",(inv["contract_id"],m)).fetchone()
        room=self.db.execute("SELECT * FROM rooms WHERE id=?",(inv["room_id"],)).fetchone()
        v=self.form(f"Chỉ số và phí {m} — phòng {inv['room_id']}",[("electric","Điện dùng (kWh)",old["electric"] if old else 0),("electric_rate","Đơn giá điện/kWh",old["electric_rate"] if old else (room["electric_rate"] or 0)),("water","Nước dùng (m³)",old["water"] if old else 0),("water_rate","Đơn giá nước/m³",old["water_rate"] if old else (room["water_rate"] or 0)),("internet","Internet (₫)",old["internet"] if old else (room["internet_fee"] or 0)),("service","Phí dịch vụ (₫)",old["service"] if old else (room["service_fee"] or 0)),("parking","Phí gửi xe (₫)",old["parking"] if old else (room["parking_fee"] or 0)),("other_name","Tên khoản khác",old["other_name"] if old else "Phí khác"),("other","Số tiền khoản khác (₫)",old["other"] if old else 0)])
        if not v:return
        try:nums=[float(v[k] or 0) for k in ("electric","electric_rate","water","water_rate","internet","service","parking","other")];assert min(nums)>=0
        except (ValueError,AssertionError):return messagebox.showerror("Số liệu không hợp lệ","Nhập các lượng sử dụng/chi phí là số không âm.")
        args=(inv["contract_id"],m,nums[0],nums[1],nums[2],nums[3],nums[4],nums[5],nums[6],v["other_name"] or "Phí khác",nums[7])
        exists=self.db.execute("SELECT 1 FROM charges WHERE contract_id=? AND month=?",(inv["contract_id"],m)).fetchone()
        if exists:self.db.execute("UPDATE charges SET electric=?,electric_rate=?,water=?,water_rate=?,internet=?,service=?,parking=?,other_name=?,other=? WHERE contract_id=? AND month=?",(*nums[:7],v["other_name"] or "Phí khác",nums[7],inv["contract_id"],m))
        else:self.db.execute("INSERT INTO charges(contract_id,month,electric,electric_rate,water,water_rate,internet,service,parking,other_name,other) VALUES(?,?,?,?,?,?,?,?,?,?,?)",args)
        self.db.commit();self.recalc_invoice(inv["id"])
        self.notify_tenant_invoice(inv["id"],True)
        self.db.commit();self.refresh()
        if self.setting("auto_send")=="1":self.send_invoice(inv["id"],True)

    def mark_paid(self):
        inv=self.selected_invoice()
        if not inv:return messagebox.showinfo("Hóa đơn","Chọn hóa đơn cần đánh dấu.")
        if inv["status"]=="Thiếu chỉ số":return messagebox.showwarning("Thiếu chỉ số","Nhập chỉ số/phí trước khi ghi nhận thanh toán.")
        total=self.db.execute("SELECT COALESCE(SUM(amount),0) FROM lines WHERE invoice_id=?",(inv["id"],)).fetchone()[0]
        self.db.execute("UPDATE invoices SET status=N'Đã thanh toán' WHERE id=?",(inv["id"],))
        self.db.execute("INSERT INTO payments(date,tenant,room,description,amount,note) VALUES(?,?,?,?,?,?)",(TODAY(),inv["tenant"],inv["room_id"],f"Hóa đơn tháng {inv['month']}",total,inv["id"]))
        tenant_user=self.db.execute("SELECT id FROM users WHERE role='tenant' AND contract_id=? AND active=1",(inv["contract_id"],)).fetchone()
        if tenant_user:portal._notify(self.db,tenant_user[0],"Đã ghi nhận thanh toán",f"Hóa đơn tháng {inv['month']} phòng {inv['room_id']} đã được ghi nhận thanh toán.")
        self.db.commit();self.refresh()

    def copy_invoice(self):
        inv=self.selected_invoice()
        if not inv:return messagebox.showinfo("Hóa đơn","Chọn hóa đơn trước.")
        lines=self.rows("SELECT name,amount FROM lines WHERE invoice_id=?",(inv["id"],));total=sum(x["amount"] for x in lines)
        text=f"HÓA ĐƠN TIỀN PHÒNG {inv['month']}\nKhách: {inv['tenant']}\nPhòng: {inv['room_id']}\n"+"\n".join(f"• {x['name']}: {MONEY(x['amount'])}" for x in lines)+f"\nTổng: {MONEY(total)}\nHạn: {inv['due']}"
        self.root.clipboard_clear();self.root.clipboard_append(text);messagebox.showinfo("Đã sao chép","Đã sao chép nội dung hóa đơn.")

    def setting(self,k):
        r=self.db.execute("SELECT value FROM settings WHERE [key]=?",(k,)).fetchone();return r[0] if r else ""

    def email_settings(self):
        v=self.form("Cấu hình email SMTP",[("host","Máy chủ SMTP",self.setting("host")),("port","Cổng",self.setting("port") or "587"),("user","Tài khoản",self.setting("user")),("password","Mật khẩu / app password",self.setting("password"),None,True),("sender","Email người gửi",self.setting("sender")),("tls","Bật STARTTLS","Có" if self.setting("tls")!="0" else "Không",["Có","Không"]),("auto","Tự gửi sau khi nhập đủ phí","Có" if self.setting("auto_send")=="1" else "Không",["Có","Không"])])
        if not v:return
        cfg={"host":v["host"],"port":v["port"] or "587","user":v["user"],"password":v["password"],"sender":v["sender"],"tls":"1" if v["tls"]=="Có" else "0","auto_send":"1" if v["auto"]=="Có" else "0"}
        for key,value in cfg.items():
            if self.db.execute("SELECT 1 FROM settings WHERE [key]=?",(key,)).fetchone():self.db.execute("UPDATE settings SET value=? WHERE [key]=?",(value,key))
            else:self.db.execute("INSERT INTO settings([key],value) VALUES(?,?)",(key,value))
        self.db.commit()
        if cfg["auto_send"]=="1":self.retry_unsent(MONTH())
        messagebox.showinfo("Đã lưu","Đã lưu cấu hình SMTP trong database SQL Server.")

    def send_selected(self):
        inv=self.selected_invoice()
        if not inv:return messagebox.showinfo("Hóa đơn","Chọn hóa đơn cần gửi.")
        self.send_invoice(inv["id"],False)

    def send_invoice(self,iid,automatic=False):
        if iid in self.sending:return
        inv=self.db.execute("SELECT i.*,c.tenant,c.email,c.room_id FROM invoices i JOIN contracts c ON c.id=i.contract_id WHERE i.id=?",(iid,)).fetchone()
        if not inv:return
        if inv["email_sent"]:return
        if inv["status"]=="Thiếu chỉ số":
            if not automatic:messagebox.showwarning("Thiếu số liệu","Nhập chỉ số và các khoản phí trước khi gửi.")
            return
        cfg={k:self.setting(k) for k in ("host","port","user","password","sender","tls")}
        if not inv["email"] or not cfg["host"] or not cfg["sender"]:
            if not automatic:messagebox.showwarning("Thiếu cấu hình","Cần email khách và cấu hình SMTP.")
            return
        lines=self.rows("SELECT name,qty,unit,rate,amount FROM lines WHERE invoice_id=?",(iid,));total=sum(x["amount"] for x in lines)
        body=[f"HÓA ĐƠN TIỀN PHÒNG {inv['month']}",f"Khách thuê: {inv['tenant']}",f"Phòng: {inv['room_id']}",""]
        for x in lines:body.append(f"- {x['name']}: {MONEY(x['amount'])}"+(f" ({x['qty']:g} {x['unit']} × {MONEY(x['rate'])})" if x["unit"] in ("kWh","m³") else ""))
        body += ["",f"Tổng cộng: {MONEY(total)}",f"Hạn thanh toán: {inv['due']}"]
        msg=email.message.EmailMessage();msg["Subject"]=f"Hóa đơn tiền phòng {inv['month']} - {inv['room_id']}";msg["From"]=cfg["sender"];msg["To"]=inv["email"];msg.set_content("\n".join(body));self.sending.add(iid)
        def worker():
            error=""
            try:
                with smtplib.SMTP(cfg["host"],int(cfg["port"] or 587),timeout=25) as mail:
                    mail.ehlo()
                    if cfg["tls"]!="0":mail.starttls(context=ssl.create_default_context());mail.ehlo()
                    if cfg["user"]:mail.login(cfg["user"],cfg["password"])
                    mail.send_message(msg)
            except Exception as exc:error=str(exc)
            self.root.after(0,lambda:self.finish_email(iid,error,automatic))
        threading.Thread(target=worker,daemon=True).start()

    def finish_email(self,iid,error,automatic):
        self.sending.discard(iid)
        if error:self.db.execute("UPDATE invoices SET email_error=? WHERE id=?",(error[:500],iid))
        else:self.db.execute("UPDATE invoices SET email_sent=?,email_error='' WHERE id=?",(datetime.now().isoformat(timespec="minutes"),iid))
        self.db.commit();self.refresh()
        if error and not automatic:messagebox.showerror("Gửi email thất bại",error)
        if not error and not automatic:messagebox.showinfo("Đã gửi","Email hóa đơn đã được gửi.")

    def retry_unsent(self,m):
        if self.setting("auto_send")!="1":return
        for r in self.rows("SELECT i.id FROM invoices i JOIN contracts c ON c.id=i.contract_id JOIN charges x ON x.contract_id=i.contract_id AND x.month=i.month WHERE i.month=? AND i.status<>N'Đã thanh toán' AND i.email_sent='' AND i.email_error='' AND c.email!=''",(m,)):
            self.send_invoice(r[0],True)

    def timer(self):
        self.ensure_month(MONTH());self.root.after(60_000,self.timer)

    def close(self):
        self.db.commit();self.db.close();portal.stop_server()
        for path in self.temp_images:
            try:path.unlink(missing_ok=True)
            except OSError:pass
        self.root.destroy()


if __name__ == "__main__":
    window=tk.Tk();RentalApp(window);window.mainloop()
