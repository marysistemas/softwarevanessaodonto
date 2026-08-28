import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import shutil
import os
import json
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
 
# ── Dependências opcionais ─────────────────────────────────────────────
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
 
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request as GRequest
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False
 
# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR  = Path.home() / "ClinicaDental"
DB_PATH   = BASE_DIR / "clinica.db"
FILES_DIR = BASE_DIR / "pacientes"
TOKEN_PATH = BASE_DIR / "google_token.json"
CREDS_PATH = BASE_DIR / "google_credentials.json"
 
BASE_DIR.mkdir(exist_ok=True)
FILES_DIR.mkdir(exist_ok=True)
 
# ── Google Drive ───────────────────────────────────────────────────────
GDRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
 
def get_gdrive_service():
    """Retorna serviço autenticado do Google Drive ou None."""
    if not HAS_GOOGLE:
        return None
    if not CREDS_PATH.exists():
        return None
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), GDRIVE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(GRequest())
            except Exception:
                creds = None
        if not creds:
            try:
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), GDRIVE_SCOPES)
                creds = flow.run_local_server(port=0)
                TOKEN_PATH.write_text(creds.to_json())
            except Exception:
                return None
    try:
        return build("drive", "v3", credentials=creds)
    except Exception:
        return None
 
def gdrive_get_or_create_folder(service, name, parent_id=None):
    """Cria pasta no Drive se não existir e retorna o ID."""
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    results = service.files().list(q=q, fields="files(id,name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]
 
def gdrive_upload_file(service, local_path: Path, folder_id: str):
    """Faz upload de arquivo para o Drive e retorna o link."""
    import mimetypes
    mime, _ = mimetypes.guess_type(str(local_path))
    mime = mime or "application/octet-stream"
    meta = {"name": local_path.name, "parents": [folder_id]}
    media = MediaFileUpload(str(local_path), mimetype=mime, resumable=True)
    f = service.files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
    return f.get("webViewLink", "")
 
# ── Palette ────────────────────────────────────────────────────────────
C = {
    "bg":        "#F7F5F2",
    "sidebar":   "#1B4F72",
    "sidebar_h": "#2471A3",
    "accent":    "#2471A3",
    "card":      "#FFFFFF",
    "border":    "#DDE1E7",
    "text":      "#1A1A2E",
    "muted":     "#6B7280",
    "success":   "#27AE60",
    "danger":    "#E74C3C",
    "mint":      "#EAF4F0",
    "teal":      "#17A589",
    "white":     "#FFFFFF",
    "gold":      "#F39C12",
}
 
FONT_H1   = ("Helvetica", 20, "bold")
FONT_H2   = ("Helvetica", 14, "bold")
FONT_BODY = ("Helvetica", 10)
FONT_SM   = ("Helvetica", 9)
FONT_BOLD = ("Helvetica", 10, "bold")
 
# ── Database ───────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS pacientes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo      TEXT UNIQUE,
            nome        TEXT NOT NULL,
            cpf         TEXT UNIQUE,
            nascimento  TEXT,
            telefone    TEXT,
            email       TEXT,
            cep         TEXT,
            endereco    TEXT,
            numero      TEXT,
            bairro      TEXT,
            cidade      TEXT,
            estado      TEXT,
            convenio    TEXT,
            obs         TEXT,
            criado_em   TEXT DEFAULT (datetime('now','localtime')),
            atualizado_em TEXT
        );
        CREATE TABLE IF NOT EXISTS anamnese (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id   INTEGER NOT NULL,
            data          TEXT DEFAULT (datetime('now','localtime')),
            queixa        TEXT,
            historico_med TEXT,
            medicamentos  TEXT,
            alergias      TEXT,
            doencas       TEXT,
            cirurgias     TEXT,
            habitos       TEXT,
            obs           TEXT,
            FOREIGN KEY(paciente_id) REFERENCES pacientes(id)
        );
        CREATE TABLE IF NOT EXISTS consultas (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id  INTEGER NOT NULL,
            data         TEXT DEFAULT (datetime('now','localtime')),
            tipo         TEXT,
            procedimento TEXT,
            valor        REAL,
            pago         INTEGER DEFAULT 0,
            obs          TEXT,
            odontograma  TEXT,
            FOREIGN KEY(paciente_id) REFERENCES pacientes(id)
        );
        CREATE TABLE IF NOT EXISTS arquivos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id  INTEGER NOT NULL,
            nome         TEXT,
            tipo         TEXT,
            caminho      TEXT,
            drive_link   TEXT,
            adicionado   TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(paciente_id) REFERENCES pacientes(id)
        );
        CREATE TABLE IF NOT EXISTS atualizacoes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id  INTEGER NOT NULL,
            tipo         TEXT,
            descricao    TEXT,
            data         TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(paciente_id) REFERENCES pacientes(id)
        );
    """)
 
    cols = [r[1] for r in c.execute("PRAGMA table_info(pacientes)").fetchall()]
    for col in ("numero", "bairro", "cidade", "estado", "cep", "atualizado_em"):
        if col not in cols:
            c.execute(f"ALTER TABLE pacientes ADD COLUMN {col} TEXT")
 
    if "codigo" not in cols:
        c.execute("ALTER TABLE pacientes ADD COLUMN codigo TEXT")
        for (pid,) in c.execute("SELECT id FROM pacientes WHERE codigo IS NULL").fetchall():
            c.execute("UPDATE pacientes SET codigo=? WHERE id=?", (f"VR-{pid:05d}", pid))
        try:
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pacientes_codigo ON pacientes(codigo)")
        except sqlite3.OperationalError:
            pass
 
    arq_cols = [r[1] for r in c.execute("PRAGMA table_info(arquivos)").fetchall()]
    if "drive_link" not in arq_cols:
        c.execute("ALTER TABLE arquivos ADD COLUMN drive_link TEXT")
 
    cons_cols = [r[1] for r in c.execute("PRAGMA table_info(consultas)").fetchall()]
    if "odontograma" not in cons_cols:
        c.execute("ALTER TABLE consultas ADD COLUMN odontograma TEXT")
 
    conn.commit()
    conn.close()
 
def get_conn():
    return sqlite3.connect(DB_PATH)
 
def gerar_proximo_codigo(conn):
    rows = conn.execute("SELECT codigo FROM pacientes WHERE codigo LIKE 'VR-%'").fetchall()
    max_num = 0
    for (codigo,) in rows:
        try:
            num = int(codigo.split("-")[1])
            max_num = max(max_num, num)
        except (IndexError, ValueError):
            continue
    return f"VR-{max_num + 1:05d}"
 
def pasta_paciente(codigo):
    p = FILES_DIR / codigo
    p.mkdir(parents=True, exist_ok=True)
    return p
 
def registrar_atualizacao(conn, pac_id, tipo, descricao):
    conn.execute(
        "INSERT INTO atualizacoes(paciente_id,tipo,descricao) VALUES(?,?,?)",
        (pac_id, tipo, descricao))
    conn.execute(
        "UPDATE pacientes SET atualizado_em=datetime('now','localtime') WHERE id=?",
        (pac_id,))
 
def obter_odontograma_acumulado(paciente_id):
    """Busca no banco todos os odontogramas anteriores e mescla em ordem cronológica."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT odontograma FROM consultas WHERE paciente_id=? AND odontograma IS NOT NULL AND odontograma != '' ORDER BY data ASC",
        (paciente_id,)
    ).fetchall()
    conn.close()
    
    odonto_acumulado = {}
    for (odonto_str,) in rows:
        try:
            dados = json.loads(odonto_str)
            if isinstance(dados, dict):
                odonto_acumulado.update(dados)
        except (json.JSONDecodeError, TypeError):
            continue
    return odonto_acumulado

# ══════════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Clínica Dental - Dra. Vanessa Rente CRO 33318 RS")
        self.geometry("1150x720")
        self.minsize(900, 600)
        self.configure(bg=C["bg"])
        self.gdrive = None
        init_db()
        self._build_layout()
        self.show_section("pacientes")
        threading.Thread(target=self._init_gdrive, daemon=True).start()
 
    def _init_gdrive(self):
        svc = get_gdrive_service()
        if svc:
            self.gdrive = svc
            self.after(0, self._update_drive_status, True)
 
    def _update_drive_status(self, connected):
        color = C["success"] if connected else C["muted"]
        txt = "☁️ Drive conectado" if connected else "☁️ Drive desconectado"
        self.lbl_drive.configure(text=txt, fg=color)
 
    def _build_layout(self):
        self.sidebar = tk.Frame(self, bg=C["sidebar"], width=210)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
 
        logo_frame = tk.Frame(self.sidebar, bg=C["sidebar"], pady=20)
        logo_frame.pack(fill="x")
        tk.Label(logo_frame, text="🦷", font=("Helvetica", 28),
                 bg=C["sidebar"], fg=C["white"]).pack()
        tk.Label(logo_frame, text="Clínica Odontológica", font=("Helvetica", 11, "bold"), 
                 bg=C["sidebar"], fg=C["white"]).pack()
        tk.Label(logo_frame, text="Dra. Vanessa Rente", font=("Helvetica", 11, "bold"), 
                 bg=C["sidebar"], fg=C["white"]).pack()
        tk.Label(logo_frame, text="CRO 33318 RS", font=("Helvetica", 10), 
                 bg=C["sidebar"], fg=C["white"]).pack()
        tk.Label(logo_frame, text="Gestão de Pacientes", font=FONT_SM,
                 bg=C["sidebar"], fg="#90C4E8").pack()
 
        ttk.Separator(self.sidebar, orient="horizontal").pack(fill="x", pady=8)
 
        self.nav_buttons = {}
        nav_items = [
            ("pacientes",    "👤  Pacientes",        self.show_pacientes),
            ("anamnese",     "📋  Anamnese",         self.show_anamnese),
            ("consultas",    "📅  Histórico",        self.show_historico),
            ("arquivos",     "📁  Arquivos",         self.show_arquivos),
            ("atualizacoes", "🔔  Atualizações",    self.show_atualizacoes),
            ("drive",        "☁️  Google Drive",     self.show_drive_config),
        ]
        for key, label, cmd in nav_items:
            btn = tk.Button(self.sidebar, text=label, anchor="w",
                            padx=20, pady=10, bd=0, cursor="hand2",
                            font=FONT_BODY, bg=C["sidebar"], fg=C["white"],
                            activebackground=C["sidebar_h"], activeforeground=C["white"],
                            command=cmd)
            btn.pack(fill="x")
            self.nav_buttons[key] = btn
 
        ttk.Separator(self.sidebar, orient="horizontal").pack(fill="x", pady=8, side="bottom")
        self.lbl_drive = tk.Label(self.sidebar, text="☁️ Drive desconectado",
                                   font=FONT_SM, bg=C["sidebar"], fg=C["muted"])
        self.lbl_drive.pack(side="bottom", pady=6)
 
        self.content = tk.Frame(self, bg=C["bg"])
        self.content.pack(side="left", fill="both", expand=True)
 
    def _set_active_nav(self, key):
        for k, btn in self.nav_buttons.items():
            btn.configure(bg=C["sidebar_h"] if k == key else C["sidebar"])
 
    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()
 
    def show_section(self, key):
        self._set_active_nav(key)
 
    def show_pacientes(self):
        self._clear_content()
        self._set_active_nav("pacientes")
 
        hdr = tk.Frame(self.content, bg=C["bg"], pady=16, padx=20)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Pacientes", font=FONT_H1,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
        tk.Button(hdr, text="+ Novo Paciente", font=FONT_BOLD,
                  bg=C["accent"], fg=C["white"], bd=0, padx=14, pady=7,
                  cursor="hand2", command=self._novo_paciente).pack(side="right")
 
        search_frame = tk.Frame(self.content, bg=C["bg"], padx=20)
        search_frame.pack(fill="x")
        tk.Label(search_frame, text="🔍", bg=C["bg"], font=("Helvetica", 12)).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *a: self._load_pacientes())
        tk.Entry(search_frame, textvariable=self.search_var, font=FONT_BODY,
                 relief="flat", bg=C["card"], bd=1,
                 highlightbackground=C["border"], highlightthickness=1,
                 width=35).pack(side="left", padx=8, ipady=5)
 
        frame = tk.Frame(self.content, bg=C["bg"], padx=20, pady=10)
        frame.pack(fill="both", expand=True)
 
        cols = ("codigo", "nome", "cpf", "telefone", "cidade", "convenio", "atualizado_em")
        self.tree_pac = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        heads = {
            "codigo":        ("Cód.", 90),
            "nome":          ("Nome", 190),
            "cpf":           ("CPF", 110),
            "telefone":      ("Telefone", 105),
            "cidade":        ("Cidade", 120),
            "convenio":      ("Convênio", 110),
            "atualizado_em": ("Atualizado", 120),
        }
        for col, (label, w) in heads.items():
            self.tree_pac.heading(col, text=label)
            self.tree_pac.column(col, width=w, minwidth=70)
 
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree_pac.yview)
        self.tree_pac.configure(yscrollcommand=sb.set)
        self.tree_pac.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree_pac.bind("<Double-1>", self._abrir_paciente)
 
        act = tk.Frame(self.content, bg=C["bg"], padx=20, pady=6)
        act.pack(fill="x")
        tk.Label(act, text="Duplo clique para abrir o paciente",
                 font=FONT_SM, bg=C["bg"], fg=C["muted"]).pack(side="left")
        tk.Button(act, text="✏️ Editar", font=FONT_SM, bg=C["card"],
                  fg=C["text"], bd=1, padx=10, cursor="hand2",
                  command=self._editar_paciente_sel).pack(side="right", padx=4)
        tk.Button(act, text="🗑 Remover", font=FONT_SM, bg=C["card"],
                  fg=C["danger"], bd=1, padx=10, cursor="hand2",
                  command=self._remover_paciente).pack(side="right", padx=4)
 
        self._load_pacientes()
 
    def _load_pacientes(self, *_):
        self.tree_pac.delete(*self.tree_pac.get_children())
        q = f"%{self.search_var.get()}%" if hasattr(self, "search_var") else "%%"
        conn = get_conn()
        rows = conn.execute(
            "SELECT id,codigo,nome,cpf,telefone,cidade,convenio,atualizado_em "
            "FROM pacientes WHERE nome LIKE ? OR cpf LIKE ? OR codigo LIKE ? "
            "ORDER BY nome", (q, q, q)).fetchall()
        conn.close()
        for r in rows:
            upd = r[7][:10] if r[7] else "—"
            self.tree_pac.insert("", "end", iid=r[0],
                values=(r[1] or "—", r[2], r[3] or "—", r[4] or "—",
                        r[5] or "—", r[6] or "—", upd))
 
    def _abrir_paciente(self, event=None):
        sel = self.tree_pac.focus()
        if sel:
            PacienteWindow(self, int(sel))
 
    def _editar_paciente_sel(self):
        sel = self.tree_pac.focus()
        if sel:
            FormPaciente(self, int(sel), callback=self._load_pacientes)
        else:
            messagebox.showinfo("Selecione", "Selecione um paciente primeiro.")
 
    def _remover_paciente(self):
        sel = self.tree_pac.focus()
        if not sel:
            messagebox.showinfo("Selecione", "Selecione um paciente primeiro.")
            return
        nome = self.tree_pac.item(sel)["values"][1]
        if messagebox.askyesno("Confirmar", f"Remover paciente '{nome}'?"):
            conn = get_conn()
            conn.execute("DELETE FROM pacientes WHERE id=?", (sel,))
            conn.commit()
            conn.close()
            self._load_pacientes()
 
    def _novo_paciente(self):
        FormPaciente(self, callback=self._load_pacientes)
 
    def show_anamnese(self):
        self._clear_content()
        self._set_active_nav("anamnese")
 
        hdr = tk.Frame(self.content, bg=C["bg"], pady=16, padx=20)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Anamneses", font=FONT_H1,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
 
        frame = tk.Frame(self.content, bg=C["bg"], padx=20, pady=10)
        frame.pack(fill="both", expand=True)
 
        cols = ("paciente", "data", "queixa", "alergias")
        tree = ttk.Treeview(frame, columns=cols, show="headings")
        for col, (label, w) in {"paciente": ("Paciente", 200), "data": ("Data", 130),
                                  "queixa": ("Queixa principal", 260),
                                  "alergias": ("Alergias", 150)}.items():
            tree.heading(col, text=label)
            tree.column(col, width=w)
 
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
 
        conn = get_conn()
        rows = conn.execute(
            "SELECT p.nome, a.data, a.queixa, a.alergias FROM anamnese a "
            "JOIN pacientes p ON p.id=a.paciente_id ORDER BY a.data DESC").fetchall()
        conn.close()
        for r in rows:
            tree.insert("", "end", values=(r[0], r[1][:16] if r[1] else "—",
                                            r[2] or "—", r[3] or "—"))
 
        tk.Label(self.content,
                 text="Para adicionar anamnese, abra o paciente na aba Pacientes.",
                 font=FONT_SM, bg=C["bg"], fg=C["muted"]).pack(pady=4)
 
    def show_historico(self):
        self._clear_content()
        self._set_active_nav("consultas")
 
        hdr = tk.Frame(self.content, bg=C["bg"], pady=16, padx=20)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Histórico de Consultas", font=FONT_H1,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
 
        frame = tk.Frame(self.content, bg=C["bg"], padx=20, pady=10)
        frame.pack(fill="both", expand=True)
 
        cols = ("paciente", "data", "tipo", "procedimento", "valor", "pago")
        tree = ttk.Treeview(frame, columns=cols, show="headings")
        for col, (label, w) in {
            "paciente": ("Paciente", 180), "data": ("Data", 130),
            "tipo": ("Tipo", 110), "procedimento": ("Procedimento", 200),
            "valor": ("Valor R$", 90), "pago": ("Pago?", 70)}.items():
            tree.heading(col, text=label)
            tree.column(col, width=w)
 
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
 
        conn = get_conn()
        rows = conn.execute(
            "SELECT p.nome, c.data, c.tipo, c.procedimento, c.valor, c.pago "
            "FROM consultas c JOIN pacientes p ON p.id=c.paciente_id "
            "ORDER BY c.data DESC").fetchall()
        conn.close()
        for r in rows:
            val = f"R$ {r[4]:.2f}" if r[4] else "—"
            tree.insert("", "end",
                values=(r[0], r[1][:16] if r[1] else "—", r[2] or "—",
                        r[3] or "—", val, "✅" if r[5] else "❌"))
 
    def show_arquivos(self):
        self._clear_content()
        self._set_active_nav("arquivos")
 
        hdr = tk.Frame(self.content, bg=C["bg"], pady=16, padx=20)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Arquivos", font=FONT_H1,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
 
        frame = tk.Frame(self.content, bg=C["bg"], padx=20, pady=10)
        frame.pack(fill="both", expand=True)
 
        cols = ("paciente", "nome", "tipo", "drive", "adicionado")
        tree = ttk.Treeview(frame, columns=cols, show="headings")
        for col, (label, w) in {
            "paciente": ("Paciente", 180), "nome": ("Arquivo", 240),
            "tipo": ("Tipo", 70), "drive": ("Drive", 60),
            "adicionado": ("Adicionado em", 130)}.items():
            tree.heading(col, text=label)
            tree.column(col, width=w)
 
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
 
        conn = get_conn()
        rows = conn.execute(
            "SELECT p.nome, a.nome, a.tipo, a.drive_link, a.adicionado "
            "FROM arquivos a JOIN pacientes p ON p.id=a.paciente_id "
            "ORDER BY a.adicionado DESC").fetchall()
        conn.close()
        for r in rows:
            drive_txt = "☁️ Sim" if r[3] else "💾 Local"
            tree.insert("", "end",
                values=(r[0], r[1], r[2] or "—", drive_txt,
                        r[4][:16] if r[4] else "—"))
 
    def show_atualizacoes(self):
        self._clear_content()
        self._set_active_nav("atualizacoes")
 
        hdr = tk.Frame(self.content, bg=C["bg"], pady=16, padx=20)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🔔 Atualizações Recentes", font=FONT_H1,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
 
        flt = tk.Frame(self.content, bg=C["bg"], padx=20)
        flt.pack(fill="x", pady=(0, 6))
        tk.Label(flt, text="Filtrar paciente:", font=FONT_SM,
                 bg=C["bg"], fg=C["muted"]).pack(side="left")
        self.upd_filter = tk.StringVar()
        self.upd_filter.trace("w", lambda *a: self._load_atualizacoes())
        tk.Entry(flt, textvariable=self.upd_filter, font=FONT_BODY,
                 relief="flat", bg=C["card"],
                 highlightbackground=C["border"], highlightthickness=1,
                 width=28).pack(side="left", padx=8, ipady=4)
        tk.Button(flt, text="Atualizar", font=FONT_SM, bg=C["accent"],
                  fg=C["white"], bd=0, padx=10, cursor="hand2",
                  command=self._load_atualizacoes).pack(side="left")
 
        frame = tk.Frame(self.content, bg=C["bg"], padx=20, pady=4)
        frame.pack(fill="both", expand=True)
 
        cols = ("data", "paciente", "codigo", "tipo", "descricao")
        self.tree_upd = ttk.Treeview(frame, columns=cols, show="headings")
        for col, (label, w) in {
            "data":      ("Data/Hora", 130),
            "paciente":  ("Paciente", 190),
            "codigo":    ("Código", 80),
            "tipo":      ("Tipo", 110),
            "descricao": ("Descrição", 360)}.items():
            self.tree_upd.heading(col, text=label)
            self.tree_upd.column(col, width=w, minwidth=60)
 
        self.tree_upd.tag_configure("cadastro",  background="#EBF5FB")
        self.tree_upd.tag_configure("anamnese",  background="#E8F8F5")
        self.tree_upd.tag_configure("consulta",  background="#FEF9E7")
        self.tree_upd.tag_configure("arquivo",   background="#FDEDEC")
 
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree_upd.yview)
        self.tree_upd.configure(yscrollcommand=sb.set)
        self.tree_upd.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
 
        det_frame = tk.Frame(self.content, bg=C["card"],
                             highlightbackground=C["border"], highlightthickness=1,
                             padx=14, pady=10)
        det_frame.pack(fill="x", padx=20, pady=(6, 12))
        self.lbl_det = tk.Label(det_frame,
                                text="Selecione uma linha para ver detalhes do paciente.",
                                font=FONT_BODY, bg=C["card"], fg=C["muted"],
                                wraplength=900, justify="left")
        self.lbl_det.pack(anchor="w")
        self.tree_upd.bind("<<TreeviewSelect>>", self._show_upd_detail)
 
        self._load_atualizacoes()
 
    def _load_atualizacoes(self, *_):
        self.tree_upd.delete(*self.tree_upd.get_children())
        q = f"%{self.upd_filter.get()}%" if hasattr(self, "upd_filter") else "%%"
        conn = get_conn()
        rows = conn.execute(
            "SELECT a.data, p.nome, p.codigo, a.tipo, a.descricao, a.paciente_id "
            "FROM atualizacoes a JOIN pacientes p ON p.id=a.paciente_id "
            "WHERE p.nome LIKE ? OR p.codigo LIKE ? "
            "ORDER BY a.data DESC LIMIT 200", (q, q)).fetchall()
        conn.close()
        tag_map = {"Cadastro": "cadastro", "Anamnese": "anamnese",
                   "Consulta": "consulta", "Arquivo": "arquivo"}
        for r in rows:
            tag = tag_map.get(r[3], "")
            self.tree_upd.insert("", "end",
                values=(r[0][:16] if r[0] else "—", r[1], r[2] or "—",
                        r[3] or "—", r[4] or "—"),
                iid=None, tags=(tag,))
 
    def _show_upd_detail(self, event=None):
        sel = self.tree_upd.focus()
        if not sel:
            return
        vals = self.tree_upd.item(sel)["values"]
        if not vals:
            return
        nome, codigo = vals[1], vals[2]
        conn = get_conn()
        r = conn.execute(
            "SELECT telefone, cidade, estado, convenio, atualizado_em "
            "FROM pacientes WHERE nome=?", (nome,)).fetchone()
        conn.close()
        if r:
            self.lbl_det.configure(
                fg=C["text"],
                text=f"👤 {nome}  ({codigo})   📞 {r[0] or '—'}   "
                     f"📍 {r[1] or '—'}/{r[2] or '—'}   "
                     f"🏥 {r[3] or '—'}   "
                     f"⏱ Última atualização: {r[4][:16] if r[4] else '—'}")
 
    def show_drive_config(self):
        self._clear_content()
        self._set_active_nav("drive")
 
        hdr = tk.Frame(self.content, bg=C["bg"], pady=16, padx=20)
        hdr.pack(fill="x")
        tk.Label(hdr, text="☁️ Google Drive", font=FONT_H1,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
 
        card = tk.Frame(self.content, bg=C["card"], padx=28, pady=24,
                        highlightbackground=C["border"], highlightthickness=1)
        card.pack(fill="x", padx=20, pady=16)
 
        status = "✅ Conectado ao Google Drive" if self.gdrive else "❌ Não conectado"
        cor = C["success"] if self.gdrive else C["danger"]
        tk.Label(card, text=status, font=FONT_H2, bg=C["card"], fg=cor).pack(anchor="w")
 
        tk.Label(card, bg=C["card"], height=1).pack()
 
        instrucoes = (
            "Para conectar ao Google Drive:\n\n"
            "1. Acesse console.cloud.google.com e crie um projeto.\n"
            "2. Ative a API 'Google Drive API'.\n"
            "3. Em 'Credenciais', crie um OAuth 2.0 Client ID (tipo: Aplicativo para desktop).\n"
            "4. Baixe o JSON de credenciais e salve como:\n"
            f"   {CREDS_PATH}\n\n"
            "5. Clique em 'Conectar ao Drive' abaixo — uma janela do navegador abrirá para autorizar.\n\n"
            "Após conectar, os arquivos e dados dos pacientes serão sincronizados\n"
            "automaticamente em pastas separadas por paciente e por data."
        )
        tk.Label(card, text=instrucoes, font=FONT_BODY, bg=C["card"],
                 fg=C["text"], justify="left").pack(anchor="w")
 
        tk.Label(card, bg=C["card"], height=1).pack()
 
        btn_frame = tk.Frame(card, bg=C["card"])
        btn_frame.pack(anchor="w")
 
        tk.Button(btn_frame, text="🔗 Conectar ao Drive", font=FONT_BOLD,
                  bg=C["accent"], fg=C["white"], bd=0, padx=16, pady=9,
                  cursor="hand2", command=self._conectar_drive).pack(side="left", padx=(0, 10))
 
        if self.gdrive:
            tk.Button(btn_frame, text="🔄 Reconectar", font=FONT_BOLD,
                      bg=C["card"], fg=C["text"], bd=1, padx=14, pady=9,
                      cursor="hand2", command=self._reconectar_drive).pack(side="left")
 
        if not HAS_GOOGLE:
            tk.Label(card, bg=C["card"],
                     text="⚠️ Bibliotecas do Google não instaladas.\n"
                          "Execute: pip install google-auth google-auth-oauthlib google-api-python-client",
                     fg=C["danger"], font=FONT_SM).pack(anchor="w", pady=(10, 0))
 
    def _conectar_drive(self):
        if not HAS_GOOGLE:
            messagebox.showerror("Bibliotecas ausentes",
                "Instale as bibliotecas:\npip install google-auth google-auth-oauthlib google-api-python-client")
            return
        if not CREDS_PATH.exists():
            messagebox.showerror("Arquivo não encontrado",
                f"Coloque o arquivo de credenciais em:\n{CREDS_PATH}")
            return
        messagebox.showinfo("Autenticação",
            "Uma janela do navegador será aberta para você autorizar o acesso ao Google Drive.")
        def _auth():
            svc = get_gdrive_service()
            if svc:
                self.gdrive = svc
                self.after(0, self._update_drive_status, True)
                self.after(0, lambda: messagebox.showinfo("Sucesso",
                    "✅ Conectado ao Google Drive com sucesso!"))
                self.after(0, self.show_drive_config)
            else:
                self.after(0, lambda: messagebox.showerror("Falha",
                    "Não foi possível conectar. Verifique o arquivo de credenciais."))
        threading.Thread(target=_auth, daemon=True).start()
 
    def _reconectar_drive(self):
        if TOKEN_PATH.exists():
            TOKEN_PATH.unlink()
        self.gdrive = None
        self._update_drive_status(False)
        self._conectar_drive()

# ══════════════════════════════════════════════════════════════════════
#  FORMULÁRIO DE PACIENTE (com CEP + busca ViaCEP)
# ══════════════════════════════════════════════════════════════════════
ESTADOS_BR = ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG",
              "PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"]

class FormPaciente(tk.Toplevel):
    def __init__(self, master, pac_id=None, callback=None):
        super().__init__(master)
        self.pac_id = pac_id
        self.callback = callback
        self.title("Novo Paciente" if not pac_id else "Editar Paciente")
        self.configure(bg=C["bg"])
        self.resizable(True, True)
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        win_w = min(620, screen_w - 40)
        win_h = min(800, screen_h - 80)
        self.geometry(f"{win_w}x{win_h}")
        self.minsize(440, 440)
        self._snapshot = {}
        self._build()
        if pac_id:
            self._load()
            self._take_snapshot()
 
    def _only_digits(self, var, max_len=None):
        def on_write(*_):
            raw = "".join(ch for ch in var.get() if ch.isdigit())
            if max_len:
                raw = raw[:max_len]
            if raw != var.get():
                var.set(raw)
        var.trace_add("write", on_write)
 
    def _date_mask(self, var):
        def on_write(*_):
            raw = "".join(ch for ch in var.get() if ch.isdigit())[:8]
            parts = []
            if len(raw) >= 1:
                parts.append(raw[:2])
            if len(raw) >= 3:
                parts.append(raw[2:4])
            if len(raw) >= 5:
                parts.append(raw[4:8])
            new_val = "/".join(parts) if len(parts) > 1 else (parts[0] if parts else "")
            if new_val != var.get():
                var.set(new_val)
        var.trace_add("write", on_write)
 
    def _buscar_cep(self):
        cep = "".join(ch for ch in self.vars["cep"].get() if ch.isdigit())
        if len(cep) != 8:
            messagebox.showwarning("CEP inválido", "Digite um CEP com 8 dígitos.")
            return
        if not HAS_REQUESTS:
            messagebox.showwarning("requests ausente",
                "Instale a biblioteca: pip install requests")
            return
        self.btn_cep.configure(text="🔄 Buscando...", state="disabled")
 
        def _fetch():
            try:
                resp = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=5)
                data = resp.json()
            except Exception as e:
                self.after(0, lambda: (
                    self.btn_cep.configure(text="🔍 Buscar CEP", state="normal"),
                    messagebox.showerror("Erro na busca", f"Não foi possível consultar o CEP:\n{e}")
                ))
                return
 
            if data.get("erro"):
                self.after(0, lambda: (
                    self.btn_cep.configure(text="🔍 Buscar CEP", state="normal"),
                    messagebox.showwarning("CEP não encontrado", "CEP não localizado na base dos Correios.")
                ))
                return
 
            self.after(0, lambda: self._preencher_endereco(data))
 
        threading.Thread(target=_fetch, daemon=True).start()
 
    def _preencher_endereco(self, data):
        self.vars["endereco"].set(data.get("logradouro", ""))
        self.vars["bairro"].set(data.get("bairro", ""))
        self.vars["cidade"].set(data.get("localidade", ""))
        self.vars["estado"].set(data.get("uf", ""))
        self.btn_cep.configure(text="🔍 Buscar CEP", state="normal")
        self.entry_numero.focus_set()
 
    def _build(self):
        tk.Label(self, text="Dados do Paciente", font=FONT_H2,
                 bg=C["bg"], fg=C["text"]).pack(pady=(18, 6))
 
        body = tk.Frame(self, bg=C["bg"])
        body.pack(side="top", fill="both", expand=True)
 
        canvas = tk.Canvas(body, bg=C["bg"], bd=0, highlightthickness=0)
        sb = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        form = tk.Frame(canvas, bg=C["bg"], padx=30)
        form_window = canvas.create_window((0, 0), window=form, anchor="nw")
 
        form.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(form_window, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
 
        def _on_mousewheel(event):
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel)
        canvas.bind_all("<Button-5>", _on_mousewheel)
        self.bind("<Destroy>",
            lambda e: (canvas.unbind_all("<MouseWheel>"),
                       canvas.unbind_all("<Button-4>"),
                       canvas.unbind_all("<Button-5>")) if e.widget is self else None)
 
        self.vars = {}
 
        def add_field(parent, label, key, width=45, **entry_kwargs):
            tk.Label(parent, text=label, font=FONT_SM, bg=C["bg"],
                     fg=C["muted"]).pack(anchor="w", pady=(8, 0))
            v = tk.StringVar()
            e = tk.Entry(parent, textvariable=v, font=FONT_BODY, relief="flat",
                         bg=C["card"], highlightbackground=C["border"],
                         highlightthickness=1, width=width, **entry_kwargs)
            e.pack(fill="x", ipady=5)
            self.vars[key] = v
            return v, e
 
        add_field(form, "Nome completo*", "nome")
        add_field(form, "CPF", "cpf")
 
        v_nasc, _ = add_field(form, "Data de nascimento (DD/MM/AAAA)", "nascimento")
        self._date_mask(v_nasc)
 
        v_tel, _ = add_field(form, "Telefone / WhatsApp (somente números)", "telefone")
        self._only_digits(v_tel, max_len=11)
 
        add_field(form, "E-mail", "email")
 
        tk.Label(form, text="Endereço", font=FONT_BOLD, bg=C["bg"],
                 fg=C["text"]).pack(anchor="w", pady=(16, 4))
 
        cep_row = tk.Frame(form, bg=C["bg"])
        cep_row.pack(fill="x", pady=(4, 0))
        tk.Label(cep_row, text="CEP", font=FONT_SM, bg=C["bg"],
                 fg=C["muted"]).pack(anchor="w")
        cep_inner = tk.Frame(cep_row, bg=C["bg"])
        cep_inner.pack(fill="x")
        v_cep = tk.StringVar()
        self._only_digits(v_cep, max_len=8)
        tk.Entry(cep_inner, textvariable=v_cep, font=FONT_BODY, relief="flat",
                 bg=C["card"], highlightbackground=C["border"],
                 highlightthickness=1, width=12).pack(side="left", ipady=5)
        self.vars["cep"] = v_cep
        self.btn_cep = tk.Button(cep_inner, text="🔍 Buscar CEP", font=FONT_SM,
                                  bg=C["accent"], fg=C["white"], bd=0, padx=12,
                                  cursor="hand2", command=self._buscar_cep)
        self.btn_cep.pack(side="left", padx=8, ipady=4)
        if not HAS_REQUESTS:
            tk.Label(cep_inner, text="(instale requests)", font=FONT_SM,
                     bg=C["bg"], fg=C["muted"]).pack(side="left")
 
        add_field(form, "Logradouro (rua/avenida)", "endereco")
 
        row1 = tk.Frame(form, bg=C["bg"])
        row1.pack(fill="x", pady=(8, 0))
        col_num = tk.Frame(row1, bg=C["bg"])
        col_num.pack(side="left", padx=(0, 8))
        col_bairro = tk.Frame(row1, bg=C["bg"])
        col_bairro.pack(side="left", fill="x", expand=True)
 
        tk.Label(col_num, text="Número", font=FONT_SM, bg=C["bg"],
                 fg=C["muted"]).pack(anchor="w")
        v_num = tk.StringVar()
        self.entry_numero = tk.Entry(col_num, textvariable=v_num, font=FONT_BODY,
                                      relief="flat", bg=C["card"],
                                      highlightbackground=C["border"],
                                      highlightthickness=1, width=10)
        self.entry_numero.pack(ipady=5)
        self.vars["numero"] = v_num
 
        tk.Label(col_bairro, text="Bairro", font=FONT_SM, bg=C["bg"],
                 fg=C["muted"]).pack(anchor="w")
        v_bairro = tk.StringVar()
        tk.Entry(col_bairro, textvariable=v_bairro, font=FONT_BODY, relief="flat",
                 bg=C["card"], highlightbackground=C["border"],
                 highlightthickness=1).pack(fill="x", ipady=5)
        self.vars["bairro"] = v_bairro
 
        row2 = tk.Frame(form, bg=C["bg"])
        row2.pack(fill="x", pady=(8, 0))
        col_cidade = tk.Frame(row2, bg=C["bg"])
        col_cidade.pack(side="left", fill="x", expand=True, padx=(0, 8))
        col_uf = tk.Frame(row2, bg=C["bg"])
        col_uf.pack(side="left")
 
        tk.Label(col_cidade, text="Cidade", font=FONT_SM, bg=C["bg"],
                 fg=C["muted"]).pack(anchor="w")
        v_cidade = tk.StringVar()
        tk.Entry(col_cidade, textvariable=v_cidade, font=FONT_BODY, relief="flat",
                 bg=C["card"], highlightbackground=C["border"],
                 highlightthickness=1).pack(fill="x", ipady=5)
        self.vars["cidade"] = v_cidade
 
        tk.Label(col_uf, text="Estado", font=FONT_SM, bg=C["bg"],
                 fg=C["muted"]).pack(anchor="w")
        v_uf = tk.StringVar()
        ttk.Combobox(col_uf, textvariable=v_uf, font=FONT_BODY, width=6,
                     state="readonly", values=ESTADOS_BR).pack(ipady=2)
        self.vars["estado"] = v_uf
 
        tk.Label(form, text="Convênio", font=FONT_BOLD, bg=C["bg"],
                 fg=C["text"]).pack(anchor="w", pady=(16, 4))
 
        self.v_tem_convenio = tk.StringVar(value="Não")
        conv_radio_frame = tk.Frame(form, bg=C["bg"])
        conv_radio_frame.pack(anchor="w")
        tk.Label(conv_radio_frame, text="Possui convênio?", font=FONT_SM,
                 bg=C["bg"], fg=C["muted"]).pack(side="left", padx=(0, 10))
        tk.Radiobutton(conv_radio_frame, text="Sim", variable=self.v_tem_convenio,
                       value="Sim", font=FONT_BODY, bg=C["bg"], fg=C["text"],
                       selectcolor=C["card"], command=self._toggle_convenio).pack(side="left")
        tk.Radiobutton(conv_radio_frame, text="Não", variable=self.v_tem_convenio,
                       value="Não", font=FONT_BODY, bg=C["bg"], fg=C["text"],
                       selectcolor=C["card"], command=self._toggle_convenio).pack(side="left")
 
        self.lbl_convenio_nome = tk.Label(form, text="Qual convênio?", font=FONT_SM,
                                          bg=C["bg"], fg=C["muted"])
        self.lbl_convenio_nome.pack(anchor="w", pady=(8, 0))
        self.v_convenio = tk.StringVar(value="Particular")
        self.entry_convenio = tk.Entry(form, textvariable=self.v_convenio,
                                       font=FONT_BODY, relief="flat", bg=C["card"],
                                       highlightbackground=C["border"], highlightthickness=1)
        self.entry_convenio.pack(fill="x", ipady=5)
        self.vars["convenio"] = self.v_convenio
        self._toggle_convenio()
 
        tk.Label(form, text="Observações", font=FONT_SM,
                 bg=C["bg"], fg=C["muted"]).pack(anchor="w", pady=(16, 2))
        self.obs_txt = tk.Text(form, height=3, font=FONT_BODY, relief="flat",
                               bg=C["card"], highlightbackground=C["border"],
                               highlightthickness=1)
        self.obs_txt.pack(fill="x", ipady=4)
        tk.Frame(form, bg=C["bg"], height=10).pack()
 
        btn_frame = tk.Frame(self, bg=C["bg"], pady=14)
        btn_frame.pack(fill="x", padx=30)
        label_salvar = "✅  Atualizar Cadastro" if self.pac_id else "💾  Salvar Paciente"
        label_limpar = "↺  Corrigir"          if self.pac_id else "↺  Limpar"
        tk.Button(btn_frame, text=label_salvar, font=FONT_BOLD,
                  bg=C["success"] if self.pac_id else C["accent"],
                  fg=C["white"], bd=0, padx=14, pady=10, cursor="hand2",
                  command=self._salvar).pack(side="left", expand=True, fill="x", padx=4)
        tk.Button(btn_frame, text=label_limpar, font=FONT_BOLD,
                  bg=C["accent"] if self.pac_id else C["card"],
                  fg=C["white"] if self.pac_id else C["text"],
                  bd=0 if self.pac_id else 1, padx=14, pady=10, cursor="hand2",
                  command=self._corrigir).pack(side="left", expand=True, fill="x", padx=4)
        tk.Button(btn_frame, text="✖  Cancelar", font=FONT_BOLD,
                  bg=C["card"], fg=C["danger"], bd=1, padx=14, pady=10,
                  cursor="hand2", command=self.destroy).pack(side="left", expand=True, fill="x", padx=4)
 
    def _toggle_convenio(self):
        if self.v_tem_convenio.get() == "Sim":
            self.lbl_convenio_nome.configure(text="Qual convênio?")
            self.entry_convenio.configure(state="normal")
            if self.v_convenio.get() == "Particular":
                self.v_convenio.set("")
        else:
            self.lbl_convenio_nome.configure(text="Convênio")
            self.v_convenio.set("Particular")
            self.entry_convenio.configure(state="disabled")
 
    def _load(self):
        conn = get_conn()
        r = conn.execute("SELECT * FROM pacientes WHERE id=?", (self.pac_id,)).fetchone()
        conn.close()
        if r:
            keys = ["id","codigo","nome","cpf","nascimento","telefone","email",
                    "cep","endereco","numero","bairro","cidade","estado",
                    "convenio","obs","criado_em","atualizado_em"]
            data = dict(zip(keys, r))
            for k, v in self.vars.items():
                v.set(data.get(k, "") or "")
            self.obs_txt.insert("1.0", data.get("obs", "") or "")
            convenio = data.get("convenio") or "Particular"
            self.v_tem_convenio.set("Não" if convenio.strip().lower() == "particular" else "Sim")
            self._toggle_convenio()
            if convenio.strip().lower() != "particular":
                self.v_convenio.set(convenio)
 
    def _take_snapshot(self):
        self._snapshot = {k: v.get() for k, v in self.vars.items()}
        self._snapshot["obs"] = self.obs_txt.get("1.0", "end").strip()
        self._snapshot["tem_convenio"] = self.v_tem_convenio.get()
 
    def _corrigir(self):
        if self.pac_id:
            for k, v in self.vars.items():
                v.set(self._snapshot.get(k, ""))
            self.obs_txt.delete("1.0", "end")
            self.obs_txt.insert("1.0", self._snapshot.get("obs", ""))
            self.v_tem_convenio.set(self._snapshot.get("tem_convenio", "Não"))
            self._toggle_convenio()
        else:
            for v in self.vars.values():
                v.set("")
            self.obs_txt.delete("1.0", "end")
            self.v_tem_convenio.set("Não")
            self._toggle_convenio()
 
    def _salvar(self):
        nome = self.vars["nome"].get().strip()
        if not nome:
            messagebox.showerror("Campo obrigatório", "Informe o nome do paciente.")
            return
        nasc = self.vars["nascimento"].get().strip()
        if nasc:
            if len(nasc) != 10:
                messagebox.showerror("Data inválida",
                    "Informe a data de nascimento completa (DD/MM/AAAA).")
                return
            try:
                datetime.strptime(nasc, "%d/%m/%Y")
            except ValueError:
                messagebox.showerror("Data inválida",
                    "A data de nascimento informada não é válida.")
                return
        tel = self.vars["telefone"].get().strip()
        if tel and len(tel) < 8:
            messagebox.showerror("Telefone inválido",
                "Informe um telefone válido (somente números).")
            return
        if self.v_tem_convenio.get() == "Sim" and not self.v_convenio.get().strip():
            messagebox.showerror("Convênio", "Informe o nome do convênio ou marque 'Não'.")
            return
        convenio = self.v_convenio.get().strip() or "Particular"
 
        data = {k: v.get().strip() for k, v in self.vars.items()}
        data["convenio"] = convenio
        data["obs"] = self.obs_txt.get("1.0", "end").strip()
 
        conn = get_conn()
        try:
            if self.pac_id:
                conn.execute(
                    "UPDATE pacientes SET nome=?,cpf=?,nascimento=?,telefone=?,"
                    "email=?,cep=?,endereco=?,numero=?,bairro=?,cidade=?,estado=?,"
                    "convenio=?,obs=? WHERE id=?",
                    (data["nome"], data["cpf"], data["nascimento"], data["telefone"],
                     data["email"], data["cep"], data["endereco"], data["numero"],
                     data["bairro"], data["cidade"], data["estado"],
                     data["convenio"], data["obs"], self.pac_id))
                registrar_atualizacao(conn, self.pac_id, "Cadastro",
                    f"Dados cadastrais atualizados para {data['nome']}")
            else:
                codigo = gerar_proximo_codigo(conn)
                conn.execute(
                    "INSERT INTO pacientes(codigo,nome,cpf,nascimento,telefone,email,"
                    "cep,endereco,numero,bairro,cidade,estado,convenio,obs)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (codigo, data["nome"], data["cpf"], data["nascimento"],
                     data["telefone"], data["email"], data["cep"], data["endereco"],
                     data["numero"], data["bairro"], data["cidade"], data["estado"],
                     data["convenio"], data["obs"]))
                new_id = conn.execute(
                    "SELECT id FROM pacientes WHERE rowid=last_insert_rowid()").fetchone()[0]
                registrar_atualizacao(conn, new_id, "Cadastro",
                    f"Paciente {data['nome']} cadastrado ({codigo})")
                pasta_paciente(codigo)

                # Cria a pasta do paciente no Google Drive ao cadastrar
                app = getattr(self.master, "master_app", self.master)
                svc = getattr(app, "gdrive", None)
                if svc:
                    def _create_drive_folder():
                        try:
                            root_id = gdrive_get_or_create_folder(svc, "ClinicaDental")
                            gdrive_get_or_create_folder(svc, codigo, root_id)
                        except Exception:
                            pass
                    threading.Thread(target=_create_drive_folder, daemon=True).start()

            conn.commit()
        except sqlite3.IntegrityError:
            messagebox.showerror("CPF duplicado",
                "Já existe um paciente com este CPF.")
            conn.close()
            return
        conn.close()
        if self.callback:
            self.callback()
        self.destroy()

# ══════════════════════════════════════════════════════════════════════
#  ODONTOGRAMA INTERATIVO (Com formato simétrico de dente)
# ══════════════════════════════════════════════════════════════════════
FDI_SUPERIOR = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
FDI_INFERIOR = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
 
STATUS_CORES = {
    "A fazer":      "#F39C12",
    "Em andamento": "#2471A3",
    "Concluído":    "#27AE60",
    "Ausente":      "#E74C3C",  # Vermelho
}
STATUS_OPCOES = list(STATUS_CORES.keys())
 
class DialogoDente(tk.Toplevel):
    """Popup que abre ao clicar em um dente, para descrever o procedimento."""
    def __init__(self, master, dente, info_atual, callback):
        super().__init__(master)
        self.dente = dente
        self.callback = callback
        self.title(f"Dente {dente}")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.geometry("360x300")
        try:
            self.transient(master.winfo_toplevel())
        except Exception:
            pass
        self.grab_set()
        self._build(info_atual)
 
    def _build(self, info_atual):
        tk.Label(self, text=f"🦷 Dente {self.dente}", font=FONT_H2,
                 bg=C["bg"], fg=C["text"]).pack(pady=(16, 8))
 
        f = tk.Frame(self, bg=C["bg"], padx=20)
        f.pack(fill="both", expand=True)
 
        tk.Label(f, text="O que precisa ser feito neste dente?", font=FONT_SM,
                 bg=C["bg"], fg=C["muted"]).pack(anchor="w")
        self.txt = tk.Text(f, height=4, font=FONT_BODY, relief="flat",
                           bg=C["card"], highlightbackground=C["border"],
                           highlightthickness=1)
        self.txt.pack(fill="x", ipady=4, pady=(2, 10))
        if info_atual:
            self.txt.insert("1.0", info_atual.get("procedimento", ""))
 
        tk.Label(f, text="Status", font=FONT_SM, bg=C["bg"],
                 fg=C["muted"]).pack(anchor="w")
        self.v_status = tk.StringVar(value=(info_atual or {}).get("status", STATUS_OPCOES[0]))
        ttk.Combobox(f, textvariable=self.v_status, font=FONT_BODY,
                     state="readonly", values=STATUS_OPCOES).pack(fill="x", ipady=2)
 
        btns = tk.Frame(self, bg=C["bg"], pady=14)
        btns.pack(fill="x", padx=20)
        
        tk.Button(btns, text="💾 Salvar", font=FONT_BOLD, bg=C["accent"],
                  fg=C["white"], bd=0, padx=10, pady=8, cursor="hand2",
                  command=self._salvar).pack(side="left", expand=True, fill="x", padx=3)
                  
        if info_atual:
            tk.Button(btns, text="🗑 Remover", font=FONT_BOLD, bg=C["card"],
                      fg=C["danger"], bd=1, padx=10, pady=8, cursor="hand2",
                      command=self._remover).pack(side="left", expand=True, fill="x", padx=3)
                      
        tk.Button(btns, text="✖ Cancelar", font=FONT_BOLD, bg=C["card"],
                  fg=C["text"], bd=1, padx=10, pady=8, cursor="hand2",
                  command=self.destroy).pack(side="left", expand=True, fill="x", padx=3)
        self.txt.focus_set()
 
    def _salvar(self):
        proc = self.txt.get("1.0", "end").strip()
        status_selecionado = self.v_status.get()
        
        if not proc:
            if status_selecionado == "Ausente":
                proc = "Dente ausente / extraído"
            else:
                proc = f"Procedimento registrado com status '{status_selecionado}'"
                
        self.callback({"procedimento": proc, "status": status_selecionado})
        self.destroy()
 
    def _remover(self):
        self.callback(None)
        self.destroy()
 
class OdontogramaWidget(tk.Frame):
    """Desenho anatômico clicável da arcada dentária (32 dentes, notação FDI)."""
    TOOTH_W = 32
    TOOTH_H = 46
    GAP = 4
    MID_GAP = 18
 
    def __init__(self, master, dados_iniciais=None, readonly=False, **kwargs):
        kwargs.setdefault("bg", C["bg"])
        super().__init__(master, **kwargs)
        self.dados = dict(dados_iniciais or {})
        self.readonly = readonly
        self._items = {}
        self._build()
 
    def _build(self):
        largura = 16 * (self.TOOTH_W + self.GAP) + self.MID_GAP + 20
        altura = 2 * (self.TOOTH_H + self.GAP) + 70
 
        self.canvas = tk.Canvas(self, width=largura, height=altura,
                                 bg=C["white"], highlightthickness=1,
                                 highlightbackground=C["border"])
        self.canvas.pack(pady=6)
 
        self.canvas.create_text(largura / 2, 10, text="Arcada superior",
                                 font=FONT_SM, fill=C["muted"])
        self._desenhar_arco(FDI_SUPERIOR, y0=20, superior=True)
        y_inf = 20 + self.TOOTH_H + 46
        self._desenhar_arco(FDI_INFERIOR, y0=y_inf, superior=False)
        self.canvas.create_text(largura / 2, y_inf + self.TOOTH_H + 22,
                                 text="Arcada inferior", font=FONT_SM, fill=C["muted"])
 
        legenda_txt = ("Clique em um dente para registrar o que precisa ser feito"
                       if not self.readonly else "Visualização (somente leitura)")
        tk.Label(self, text=legenda_txt, font=FONT_SM,
                 bg=C["bg"], fg=C["muted"]).pack(pady=(4, 4))
 
        chips = tk.Frame(self, bg=C["bg"])
        chips.pack(pady=(0, 6))
        for status, cor in STATUS_CORES.items():
            chip = tk.Frame(chips, bg=C["bg"])
            chip.pack(side="left", padx=6)
            tk.Frame(chip, bg=cor, width=12, height=12).pack(side="left")
            tk.Label(chip, text=status, font=FONT_SM, bg=C["bg"],
                     fg=C["muted"]).pack(side="left", padx=(4, 0))
 
        self.legenda = tk.Text(self, height=7, font=FONT_SM, relief="flat",
                               bg=C["card"], highlightbackground=C["border"],
                               highlightthickness=1, state="disabled", wrap="word")
        self.legenda.pack(fill="both", expand=True, padx=4)
        self._atualizar_legenda()
 
    def _desenhar_arco(self, dentes, y0, superior):
        x = 10
        for i, dente in enumerate(dentes):
            if i == 8:
                x += self.MID_GAP
            x0, y_ = x, y0
            w, h = self.TOOTH_W, self.TOOTH_H
            x1, y1 = x0 + w, y_ + h
            cor = self._cor_dente(dente)
            
            # Desenha formato anatômico do dente (curvado com crown + raiz)
            if superior:
                pts = [
                    x0 + w*0.15, y_,               # Topo da coroa (arredondado)
                    x0 + w*0.85, y_,
                    x1,          y_ + h*0.45,       # Ombro da coroa
                    x0 + w*0.65, y1,               # Ponta da Raiz
                    x0 + w*0.35, y1,
                    x0,          y_ + h*0.45        # Ombro esquerdo
                ]
            else:
                pts = [
                    x0 + w*0.35, y_,               # Ponta da Raiz (virada para cima)
                    x0 + w*0.65, y_,
                    x1,          y_ + h*0.55,       # Ombro da coroa
                    x0 + w*0.85, y1,               # Base da coroa
                    x0 + w*0.15, y1,
                    x0,          y_ + h*0.55
                ]
                
            shape = self.canvas.create_polygon(pts, fill=cor, outline=C["muted"], width=1, smooth=True)
            
            label_y = y1 + 12 if superior else y_ - 12
            self.canvas.create_text((x0 + x1) / 2, label_y, text=str(dente),
                        font=("Helvetica", 8, "bold"), fill=C["text"])
            self._items[dente] = shape
            if not self.readonly:
                self.canvas.tag_bind(shape, "<Button-1>",
                    lambda e, d=dente: self._clicar_dente(d))
                self.canvas.tag_bind(shape, "<Enter>",
                    lambda e: self.canvas.configure(cursor="hand2"))
                self.canvas.tag_bind(shape, "<Leave>",
                    lambda e: self.canvas.configure(cursor=""))
            x += self.TOOTH_W + self.GAP
 
    def _cor_dente(self, dente):
        info = self.dados.get(str(dente))
        if info:
            return STATUS_CORES.get(info.get("status"), C["white"])
        return C["white"]
 
    def _clicar_dente(self, dente):
        DialogoDente(self, dente, self.dados.get(str(dente)),
                     callback=lambda info: self._salvar_dente(dente, info))
 
    def _salvar_dente(self, dente, info):
        if info is None:
            self.dados.pop(str(dente), None)
        else:
            self.dados[str(dente)] = info
        rect = self._items[dente]
        self.canvas.itemconfig(rect, fill=self._cor_dente(dente))
        self._atualizar_legenda()
 
    def _atualizar_legenda(self):
        self.legenda.configure(state="normal")
        self.legenda.delete("1.0", "end")
        if not self.dados:
            self.legenda.insert("1.0", "Nenhum dente marcado ainda.")
        else:
            for dente in sorted(self.dados, key=lambda d: int(d)):
                info = self.dados[dente]
                self.legenda.insert("end",
                    f"🦷 Dente {dente} — {info.get('status', '—')}: "
                    f"{info.get('procedimento', '')}\n")
        self.legenda.configure(state="disabled")
 
    def get_dados(self):
        return dict(self.dados)
 
    def set_dados(self, dados):
        self.dados = dict(dados or {})
        for dente, rect in self._items.items():
            self.canvas.itemconfig(rect, fill=self._cor_dente(dente))
        self._atualizar_legenda()

# ══════════════════════════════════════════════════════════════════════
#  JANELA DO PACIENTE
# ══════════════════════════════════════════════════════════════════════
class PacienteWindow(tk.Toplevel):
    def __init__(self, master, pac_id):
        super().__init__(master)
        self.master_app = master
        self.pac_id = pac_id
        conn = get_conn()
        r = conn.execute("SELECT nome,codigo FROM pacientes WHERE id=?", (pac_id,)).fetchone()
        conn.close()
        self.nome = r[0] if r else "Paciente"
        self.codigo = r[1] if r and r[1] else "—"
        self.title(f"Paciente — {self.nome} ({self.codigo})")
        self.geometry("820x620")
        self.configure(bg=C["bg"])
        self._build()
 
    def _build(self):
        hdr = tk.Frame(self, bg=C["sidebar"], pady=14, padx=20)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"🦷  {self.nome}   ·   {self.codigo}", font=FONT_H2,
                 bg=C["sidebar"], fg=C["white"]).pack(side="left")
 
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=16, pady=10)
 
        self.tab_dados     = tk.Frame(nb, bg=C["bg"])
        self.tab_anamnese  = tk.Frame(nb, bg=C["bg"])
        self.tab_hist      = tk.Frame(nb, bg=C["bg"])
        self.tab_odonto    = tk.Frame(nb, bg=C["bg"])
        self.tab_arq       = tk.Frame(nb, bg=C["bg"])
        self.tab_upd       = tk.Frame(nb, bg=C["bg"])
 
        nb.add(self.tab_dados,    text="  Dados  ")
        nb.add(self.tab_anamnese, text="  Anamnese  ")
        nb.add(self.tab_hist,     text="  Histórico  ")
        nb.add(self.tab_odonto,   text="  Odontograma  ")
        nb.add(self.tab_arq,      text="  Arquivos  ")
        nb.add(self.tab_upd,      text="  Atualizações  ")
 
        self._build_dados()
        self._build_anamnese()
        self._build_historico()
        self._build_odontograma_tab()
        self._build_arquivos()
        self._build_updates()
 
    def _build_dados(self):
        conn = get_conn()
        r = conn.execute("SELECT * FROM pacientes WHERE id=?", (self.pac_id,)).fetchone()
        conn.close()
        if not r:
            return
        keys = ["id","codigo","nome","cpf","nascimento","telefone","email",
                "cep","endereco","numero","bairro","cidade","estado",
                "convenio","obs","criado_em","atualizado_em"]
        data = dict(zip(keys, r))
 
        f = tk.Frame(self.tab_dados, bg=C["bg"], padx=20, pady=16)
        f.pack(fill="both", expand=True)
 
        endereco_completo = ", ".join(filter(None, [
            data.get("endereco"),
            f"nº {data['numero']}" if data.get("numero") else None,
            data.get("bairro"),
            data.get("cidade"),
            f"{data.get('estado')} — CEP {data.get('cep')}" if data.get("estado") else None,
        ])) or "—"
 
        pairs = [("Código", "codigo"), ("Nome", "nome"), ("CPF", "cpf"),
                 ("Nascimento", "nascimento"), ("Telefone", "telefone"),
                 ("E-mail", "email"), ("Convênio", "convenio")]
        for i, (label, key) in enumerate(pairs):
            row = i // 2
            col_base = (i % 2) * 2
            tk.Label(f, text=label+":", font=FONT_BOLD, bg=C["bg"],
                     fg=C["muted"]).grid(row=row, column=col_base, sticky="w",
                                         padx=(0, 6), pady=5)
            tk.Label(f, text=data.get(key) or "—", font=FONT_BODY,
                     bg=C["bg"], fg=C["text"]).grid(row=row, column=col_base+1,
                                                     sticky="w", pady=5)
 
        next_row = (len(pairs) + 1) // 2
        tk.Label(f, text="Endereço:", font=FONT_BOLD, bg=C["bg"],
                 fg=C["muted"]).grid(row=next_row, column=0, sticky="nw", pady=5)
        tk.Label(f, text=endereco_completo, font=FONT_BODY, bg=C["bg"],
                 fg=C["text"], wraplength=440, justify="left").grid(
                     row=next_row, column=1, columnspan=3, sticky="w", pady=5)
 
        obs_row = next_row + 1
        tk.Label(f, text="Observações:", font=FONT_BOLD, bg=C["bg"],
                 fg=C["muted"]).grid(row=obs_row, column=0, sticky="nw", pady=(10, 0))
        tk.Label(f, text=data.get("obs") or "—", font=FONT_BODY, bg=C["bg"],
                 fg=C["text"], wraplength=440, justify="left").grid(
                     row=obs_row, column=1, columnspan=3, sticky="w", pady=(10, 0))
 
        tk.Button(self.tab_dados, text="✏️ Editar dados", font=FONT_SM,
                  bg=C["card"], fg=C["text"], bd=1, padx=12, cursor="hand2",
                  command=lambda: FormPaciente(self, self.pac_id,
                                               callback=self._rebuild_dados)).pack(pady=8)
 
    def _rebuild_dados(self):
        for w in self.tab_dados.winfo_children():
            w.destroy()
        self._build_dados()
 
    def _build_anamnese(self):
        conn = get_conn()
        rows = conn.execute(
            "SELECT id,data,queixa,historico_med,medicamentos,alergias,"
            "doencas,cirurgias,habitos,obs FROM anamnese WHERE paciente_id=? "
            "ORDER BY data DESC", (self.pac_id,)).fetchall()
        conn.close()
 
        top = tk.Frame(self.tab_anamnese, bg=C["bg"], padx=16, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="Anamneses registradas", font=FONT_H2,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
        tk.Button(top, text="+ Nova Anamnese", font=FONT_BOLD,
                  bg=C["teal"], fg=C["white"], bd=0, padx=12, pady=6,
                  cursor="hand2", command=self._nova_anamnese).pack(side="right")
 
        if not rows:
            tk.Label(self.tab_anamnese, text="Nenhuma anamnese registrada.",
                     font=FONT_BODY, bg=C["bg"], fg=C["muted"]).pack(pady=20)
            return
 
        canvas = tk.Canvas(self.tab_anamnese, bg=C["bg"], bd=0, highlightthickness=0)
        sb = ttk.Scrollbar(self.tab_anamnese, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=C["bg"])
        scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(16, 0))
        sb.pack(side="right", fill="y")
 
        labels_map = [("Queixa principal", 2), ("Histórico médico", 3),
                      ("Medicamentos", 4), ("Alergias", 5), ("Doenças", 6),
                      ("Cirurgias", 7), ("Hábitos", 8), ("Observações", 9)]
        for r in rows:
            card = tk.Frame(scroll_frame, bg=C["card"], bd=1, relief="flat",
                            pady=10, padx=14)
            card.pack(fill="x", padx=10, pady=6)
            tk.Label(card, text=f"📋  {r[1][:16] if r[1] else '—'}", font=FONT_BOLD,
                     bg=C["card"], fg=C["accent"]).pack(anchor="w")
            for label, idx in labels_map:
                val = r[idx]
                if val:
                    row_f = tk.Frame(card, bg=C["card"])
                    row_f.pack(fill="x", pady=1)
                    tk.Label(row_f, text=label+":", font=FONT_BOLD, width=18,
                             anchor="w", bg=C["card"], fg=C["muted"]).pack(side="left")
                    tk.Label(row_f, text=val, font=FONT_BODY, bg=C["card"],
                             fg=C["text"], wraplength=420, justify="left").pack(side="left")
 
    def _nova_anamnese(self):
        FormAnamnese(self, self.pac_id, callback=self._refresh_anamnese)
 
    def _refresh_anamnese(self):
        for w in self.tab_anamnese.winfo_children():
            w.destroy()
        self._build_anamnese()
 
    def _build_historico(self):
        top = tk.Frame(self.tab_hist, bg=C["bg"], padx=16, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="Histórico de Visitas", font=FONT_H2,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
        tk.Button(top, text="+ Registrar Visita", font=FONT_BOLD,
                  bg=C["teal"], fg=C["white"], bd=0, padx=12, pady=6,
                  cursor="hand2", command=self._nova_consulta).pack(side="right")
 
        frame = tk.Frame(self.tab_hist, bg=C["bg"], padx=16)
        frame.pack(fill="both", expand=True)
        cols = ("data", "tipo", "procedimento", "valor", "pago", "odonto", "obs")
        tree = ttk.Treeview(frame, columns=cols, show="headings")
        for col, (label, w) in {
            "data": ("Data", 130), "tipo": ("Tipo", 100),
            "procedimento": ("Procedimento", 160),
            "valor": ("Valor R$", 85), "pago": ("Pago?", 60),
            "odonto": ("Odontograma", 90),
            "obs": ("Observações", 160)}.items():
            tree.heading(col, text=label)
            tree.column(col, width=w)
 
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree_hist = tree
        self._load_historico()
 
    def _load_historico(self):
        self.tree_hist.delete(*self.tree_hist.get_children())
        conn = get_conn()
        rows = conn.execute(
            "SELECT data,tipo,procedimento,valor,pago,obs,odontograma FROM consultas "
            "WHERE paciente_id=? ORDER BY data DESC", (self.pac_id,)).fetchall()
        conn.close()
        for r in rows:
            val = f"R$ {r[3]:.2f}" if r[3] else "—"
            n_dentes = len(json.loads(r[6])) if r[6] else 0
            self.tree_hist.insert("", "end",
                values=(r[0][:16] if r[0] else "—", r[1] or "—",
                        r[2] or "—", val, "✅" if r[4] else "❌",
                        f"{n_dentes} dente(s)" if n_dentes else "—", r[5] or ""))
 
    def _nova_consulta(self):
        FormConsulta(self, self.pac_id,
                     callback=lambda: (self._load_historico(),
                                        self._refresh_odontograma_tab()))
 
    def _build_odontograma_tab(self):
        for w in self.tab_odonto.winfo_children():
            w.destroy()
 
        top = tk.Frame(self.tab_odonto, bg=C["bg"], padx=16, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="Odontograma por Visita", font=FONT_H2,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
 
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, data, tipo, odontograma FROM consultas "
            "WHERE paciente_id=? AND odontograma IS NOT NULL AND odontograma != '' "
            "ORDER BY data DESC", (self.pac_id,)).fetchall()
        conn.close()
 
        if not rows:
            tk.Label(self.tab_odonto,
                     text="Nenhuma visita com odontograma registrado ainda.\n"
                          "Marque os dentes ao registrar uma nova visita no Histórico.",
                     font=FONT_BODY, bg=C["bg"], fg=C["muted"],
                     justify="left").pack(pady=30, padx=16, anchor="w")
            return
 
        sel_frame = tk.Frame(self.tab_odonto, bg=C["bg"], padx=16)
        sel_frame.pack(fill="x")
        tk.Label(sel_frame, text="Selecione a visita:", font=FONT_SM,
                 bg=C["bg"], fg=C["muted"]).pack(side="left")
 
        opcoes = {}
        for r in rows:
            chave = f"{(r[1] or '')[:16]} — {r[2] or 'Consulta'}"
            opcoes[chave] = r
        v_sel = tk.StringVar(value=list(opcoes.keys())[0])
        combo = ttk.Combobox(sel_frame, textvariable=v_sel, font=FONT_BODY,
                              state="readonly", values=list(opcoes.keys()), width=42)
        combo.pack(side="left", padx=8)
 
        container = tk.Frame(self.tab_odonto, bg=C["bg"])
        container.pack(fill="both", expand=True)
 
        def _render(*_):
            for w in container.winfo_children():
                w.destroy()
            r = opcoes[v_sel.get()]
            try:
                dados = json.loads(r[3]) if r[3] else {}
            except (json.JSONDecodeError, TypeError):
                dados = {}
            odo = OdontogramaWidget(container, dados_iniciais=dados, readonly=True)
            odo.pack(fill="both", expand=True, padx=16, pady=6)
 
        combo.bind("<<ComboboxSelected>>", _render)
        _render()
 
    def _refresh_odontograma_tab(self):
        self._build_odontograma_tab()
 
    def _build_arquivos(self):
        top = tk.Frame(self.tab_arq, bg=C["bg"], padx=16, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="Arquivos do Paciente", font=FONT_H2,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
        tk.Button(top, text="+ Adicionar Arquivo", font=FONT_BOLD,
                  bg=C["teal"], fg=C["white"], bd=0, padx=12, pady=6,
                  cursor="hand2", command=self._add_arquivo).pack(side="right")
 
        frame = tk.Frame(self.tab_arq, bg=C["bg"], padx=16)
        frame.pack(fill="both", expand=True)
        cols = ("nome", "tipo", "drive", "adicionado")
        self.tree_arq = ttk.Treeview(frame, columns=cols, show="headings")
        for col, (label, w) in {
            "nome": ("Arquivo", 270), "tipo": ("Tipo", 70),
            "drive": ("Drive", 80), "adicionado": ("Adicionado", 130)}.items():
            self.tree_arq.heading(col, text=label)
            self.tree_arq.column(col, width=w)
 
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree_arq.yview)
        self.tree_arq.configure(yscrollcommand=sb.set)
        self.tree_arq.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree_arq.bind("<Double-1>", self._abrir_arquivo)
 
        drive_status = "☁️ Drive ativo" if self.master_app.gdrive else "💾 Apenas local"
        drive_cor = C["success"] if self.master_app.gdrive else C["muted"]
        tk.Label(self.tab_arq,
                 text=f"Duplo clique para abrir o arquivo | {drive_status}",
                 font=FONT_SM, bg=C["bg"], fg=drive_cor).pack(pady=4)
        self._load_arquivos()
 
    def _load_arquivos(self):
        self.tree_arq.delete(*self.tree_arq.get_children())
        conn = get_conn()
        rows = conn.execute(
            "SELECT id,nome,tipo,drive_link,adicionado FROM arquivos "
            "WHERE paciente_id=? ORDER BY adicionado DESC", (self.pac_id,)).fetchall()
        conn.close()
        for r in rows:
            drv = "☁️ Link Drive" if r[3] else "💾 Local"
            self.tree_arq.insert("", "end", iid=r[0],
                values=(r[1], (r[2] or "").upper(), drv, r[4][:16] if r[4] else "—"))
 
    def _add_arquivo(self):
        origem = filedialog.askopenfilename(
            title="Selecionar Documento/Exame",
            filetypes=[("Imagens e PDF", "*.jpg *.jpeg *.png *.pdf"), ("Todos os arquivos", "*.*")])
        if not origem:
            return
        p_origem = Path(origem)
        ext = p_origem.suffix.lower().replace(".", "")
 
        data_pasta = datetime.now().strftime("%Y-%m-%d")
        destino_dir = pasta_paciente(self.codigo) / data_pasta
        destino_dir.mkdir(exist_ok=True)
        nome_final = f"{datetime.now().strftime('%H%M%S')}_{p_origem.name}"
        p_destino = destino_dir / nome_final
 
        shutil.copy(origem, p_destino)
 
        def _upload():
            drive_link = ""
            svc = self.master_app.gdrive
            if svc:
                try:
                    root_id = gdrive_get_or_create_folder(svc, "ClinicaDental")
                    pac_folder = gdrive_get_or_create_folder(svc, self.codigo, root_id)
                    date_folder = gdrive_get_or_create_folder(svc, data_pasta, pac_folder)
                    drive_link = gdrive_upload_file(svc, p_destino, date_folder)
                except Exception:
                    drive_link = ""
 
            conn = get_conn()
            conn.execute(
                "INSERT INTO arquivos(paciente_id,nome,tipo,caminho,drive_link) VALUES(?,?,?,?,?)",
                (self.pac_id, p_destino.name, ext, str(p_destino), drive_link))
            registrar_atualizacao(conn, self.pac_id, "Arquivo", f"Anexou o arquivo '{p_destino.name}'")
            conn.commit()
            conn.close()
            self.after(0, self._load_arquivos)
            msg = f"Arquivo {p_destino.name} adicionado com sucesso."
            if drive_link:
                msg += "\nAnexo enviado para a nuvem no Google Drive!"
            else:
                msg += "\n(Drive não conectado — salvo apenas local)"
            self.after(0, lambda: messagebox.showinfo("Arquivo adicionado", msg))
 
        threading.Thread(target=_upload, daemon=True).start()
 
    def _abrir_arquivo(self, event=None):
        sel = self.tree_arq.focus()
        if not sel:
            return
        conn = get_conn()
        r = conn.execute("SELECT caminho,drive_link FROM arquivos WHERE id=?", (sel,)).fetchone()
        conn.close()
        if r and Path(r[0]).exists():
            try:
                if sys.platform == "win32":
                    os.startfile(r[0])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", r[0]])
                else:
                    subprocess.Popen(["xdg-open", r[0]])
            except Exception as e:
                messagebox.showerror("Erro", str(e))
        elif r and r[1]:
            import webbrowser
            webbrowser.open(r[1])
        else:
            messagebox.showerror("Arquivo não encontrado",
                "O arquivo não foi localizado no disco nem no Drive.")
 
    def _build_updates(self):
        top = tk.Frame(self.tab_upd, bg=C["bg"], padx=16, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="Histórico de Atualizações", font=FONT_H2,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
        tk.Button(top, text="🔄 Atualizar", font=FONT_SM, bg=C["card"],
                  fg=C["text"], bd=1, padx=10, cursor="hand2",
                  command=self._refresh_updates).pack(side="right")
 
        frame = tk.Frame(self.tab_upd, bg=C["bg"], padx=16)
        frame.pack(fill="both", expand=True)
        cols = ("data", "tipo", "descricao")
        self.tree_upd_pac = ttk.Treeview(frame, columns=cols, show="headings")
        for col, (label, w) in {
            "data": ("Data/Hora", 140), "tipo": ("Tipo", 110),
            "descricao": ("Descrição", 480)}.items():
            self.tree_upd_pac.heading(col, text=label)
            self.tree_upd_pac.column(col, width=w)
 
        self.tree_upd_pac.tag_configure("cadastro",  background="#EBF5FB")
        self.tree_upd_pac.tag_configure("anamnese",  background="#E8F8F5")
        self.tree_upd_pac.tag_configure("consulta",  background="#FEF9E7")
        self.tree_upd_pac.tag_configure("arquivo",   background="#FDEDEC")
 
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree_upd_pac.yview)
        self.tree_upd_pac.configure(yscrollcommand=sb.set)
        self.tree_upd_pac.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._load_updates()
 
    def _load_updates(self):
        self.tree_upd_pac.delete(*self.tree_upd_pac.get_children())
        conn = get_conn()
        rows = conn.execute(
            "SELECT data, tipo, descricao FROM atualizacoes "
            "WHERE paciente_id=? ORDER BY data DESC", (self.pac_id,)).fetchall()
        conn.close()
        tag_map = {"Cadastro": "cadastro", "Anamnese": "anamnese",
                   "Consulta": "consulta", "Arquivo": "arquivo"}
        for r in rows:
            tag = tag_map.get(r[1], "")
            self.tree_upd_pac.insert("", "end",
                values=(r[0][:16] if r[0] else "—", r[1], r[2]), tags=(tag,))
 
    def _refresh_updates(self):
        self._load_updates()

# ══════════════════════════════════════════════════════════════════════
#  FORMULÁRIO ANAMNESE
# ══════════════════════════════════════════════════════════════════════
PATOLOGIAS_LISTA = [
    "Anemia", "Asma", "Alteração Rins ou bexiga", "Bronquite", "Cardiopatia",
    "Colesterol", "Diabetes", "Febre Amarela", "Febre Reumática", "Hepatite",
    "HIV", "Pressão alta", "Pressão Baixa", "Quando corta, sangra muito?",
    "Rinite", "Sente-se cansado com frequência?", "Sinusite"
]

DELETERIOS_LISTA = [
    "Dorme com a boca aberta", "Ronca", "Baba no travesseiro", "Morde objetos",
    "Morde os lábios", "Range os dentes", "Roer Unhas"
]

TECIDOS_MOLES = ["Lábios", "Língua", "Palato", "Gengiva", "Mucosa"]

class FormAnamnese(tk.Toplevel):
    def __init__(self, master, pac_id, callback=None):
        super().__init__(master)
        self.pac_id = pac_id
        self.callback = callback
        self.title("Ficha de Anamnese — Drª Vanessa Rente")
        self.geometry("740x820")
        self.configure(bg=C["bg"])
        self._build()

    def _build(self):
        tk.Label(self, text="📋 Questionário de Anamnese Completa", font=FONT_H1, bg=C["bg"], fg=C["text"]).pack(pady=(14, 4))
        
        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True)

        canvas = tk.Canvas(body, bg=C["bg"], bd=0, highlightthickness=0)
        sb = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        f = tk.Frame(canvas, bg=C["bg"], padx=20)

        f.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=f, anchor="nw", width=680)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def section_header(title):
            lbl_f = tk.Frame(f, bg=C["sidebar"], pady=6)
            lbl_f.pack(fill="x", pady=(16, 8))
            tk.Label(lbl_f, text=title, font=FONT_BOLD, bg=C["sidebar"], fg=C["white"]).pack(anchor="w", padx=10)

        # ── 1. QUEIXA PRINCIPAL
        section_header("1. QUEIXA PRINCIPAL")
        self.queixa_txt = tk.Text(f, height=3, font=FONT_BODY, bg=C["card"], highlightbackground=C["border"], highlightthickness=1)
        self.queixa_txt.pack(fill="x")

        # ── 2. HISTÓRICO DO PACIENTE
        section_header("2. HISTÓRICO DO PACIENTE")

        q_items = [
            ("1. Faz tratamento médico?", "trat_medico"),
            ("2. Quando fez seu último tratamento médico?", "ult_trat_medico"),
            ("3. Tem alergia ou sensibilidade a algum medicamento?", "alergia_med"),
            ("4. Atualmente está tomando algum medicamento?", "tomando_med"),
            ("5. Já tomou antibiótico?", "tomou_antibiotico"),
            ("6. Já tomou anti-inflamatório?", "tomou_antiinflamatorio"),
            ("7. Já tomou analgésico?", "tomou_analgesico"),
            ("8. Possui alguma doença ou alguma alteração clínica?", "doenca_clinica"),
            ("9. Foi hospitalizado ou submeteu-se à(s) cirurgia(s)?", "hospitalizado"),
            ("10. Recebeu transfusão de sangue?", "transfusao"),
        ]

        self.hist_vars = {}
        for label, key in q_items:
            q_frame = tk.Frame(f, bg=C["bg"])
            q_frame.pack(fill="x", pady=4)
            tk.Label(q_frame, text=label, font=FONT_SM, bg=C["bg"], fg=C["text"]).pack(anchor="w")
            
            sub_f = tk.Frame(q_frame, bg=C["bg"])
            sub_f.pack(fill="x", pady=2)
            v_opc = tk.StringVar(value="Não")
            tk.Radiobutton(sub_f, text="Sim", variable=v_opc, value="Sim", bg=C["bg"]).pack(side="left")
            tk.Radiobutton(sub_f, text="Não", variable=v_opc, value="Não", bg=C["bg"]).pack(side="left")
            
            v_det = tk.StringVar()
            tk.Entry(sub_f, textvariable=v_det, font=FONT_BODY, bg=C["card"], highlightbackground=C["border"], highlightthickness=1, width=40).pack(side="left", padx=8, ipady=3)
            self.hist_vars[key] = (v_opc, v_det)

        # ── Patologias
        tk.Label(f, text="11. Tem ou teve algumas destas doenças?", font=FONT_BOLD, bg=C["bg"], fg=C["text"]).pack(anchor="w", pady=(10, 4))
        self.patologia_vars = {}
        grid_pat = tk.Frame(f, bg=C["card"], highlightbackground=C["border"], highlightthickness=1, padx=10, pady=8)
        grid_pat.pack(fill="x")
        
        for idx, pat in enumerate(PATOLOGIAS_LISTA):
            r = idx // 2
            c_base = (idx % 2) * 2
            tk.Label(grid_pat, text=pat, font=FONT_SM, bg=C["card"]).grid(row=r, column=c_base, sticky="w", pady=2)
            v = tk.StringVar(value="NÃO")
            cb = ttk.Combobox(grid_pat, textvariable=v, values=["SIM", "NÃO"], width=6, state="readonly")
            cb.grid(row=r, column=c_base+1, sticky="w", padx=(4, 16), pady=2)
            self.patologia_vars[pat] = v

        # Questões odontológicas 12-17
        q_odonto = [
            ("12. É a primeira visita ao dentista?", "primeira_visita"),
            ("13. Já abandonou algum tratamento odontológico?", "abandonou_trat"),
            ("14. Você já recebeu anestesia no tratamento odontológico?", "recebeu_anestesia"),
            ("15. Visita regularmente o cirurgião dentista?", "visita_regular"),
        ]
        for label, key in q_odonto:
            q_frame = tk.Frame(f, bg=C["bg"])
            q_frame.pack(fill="x", pady=4)
            tk.Label(q_frame, text=label, font=FONT_SM, bg=C["bg"], fg=C["text"]).pack(anchor="w")
            v_opc = tk.StringVar(value="Não")
            sub_f = tk.Frame(q_frame, bg=C["bg"])
            sub_f.pack(fill="x")
            tk.Radiobutton(sub_f, text="Sim", variable=v_opc, value="Sim", bg=C["bg"]).pack(side="left")
            tk.Radiobutton(sub_f, text="Não", variable=v_opc, value="Não", bg=C["bg"]).pack(side="left")
            self.hist_vars[key] = (v_opc, None)

        tk.Label(f, text="16. De quanto em quanto tempo?", font=FONT_SM, bg=C["bg"]).pack(anchor="w", pady=(6, 2))
        self.v_frequencia_visita = tk.StringVar(value="Somente quando precisa")
        ttk.Combobox(f, textvariable=self.v_frequencia_visita, values=["De 6 em 6 meses", "A cada ano", "Somente quando precisa"], state="readonly").pack(fill="x", ipady=2)

        tk.Label(f, text="17. Qual foi a última visita (Data):", font=FONT_SM, bg=C["bg"]).pack(anchor="w", pady=(6, 2))
        self.v_ult_visita_data = tk.StringVar()
        tk.Entry(f, textvariable=self.v_ult_visita_data, font=FONT_BODY, bg=C["card"], highlightbackground=C["border"], highlightthickness=1).pack(fill="x", ipady=3)

        # ── 3. HÁBITOS DE HIGIENE ORAL
        section_header("3. HÁBITOS DE HIGIENE ORAL")
        
        tk.Label(f, text="1. Com que frequência escova os dentes?", font=FONT_SM, bg=C["bg"]).pack(anchor="w")
        self.v_escovacao = tk.StringVar(value="3x ao dia")
        ttk.Combobox(f, textvariable=self.v_escovacao, values=["1x ao dia", "2x ao dia", "3x ao dia", "Somente após as refeições"], state="readonly").pack(fill="x", ipady=2, pady=2)

        tk.Label(f, text="2. Qual creme dental utiliza?", font=FONT_SM, bg=C["bg"]).pack(anchor="w", pady=(4, 0))
        self.v_creme_dental = tk.StringVar()
        tk.Entry(f, textvariable=self.v_creme_dental, font=FONT_BODY, bg=C["card"], highlightbackground=C["border"], highlightthickness=1).pack(fill="x", ipady=3)

        self.v_fio_dental = tk.StringVar(value="Sim")
        fio_f = tk.Frame(f, bg=C["bg"])
        fio_f.pack(fill="x", pady=4)
        tk.Label(fio_f, text="3. Faz uso do fio dental?", font=FONT_SM, bg=C["bg"]).pack(side="left")
        tk.Radiobutton(fio_f, text="Sim", variable=self.v_fio_dental, value="Sim", bg=C["bg"]).pack(side="left", padx=6)
        tk.Radiobutton(fio_f, text="Não", variable=self.v_fio_dental, value="Não", bg=C["bg"]).pack(side="left")

        fluor_f = tk.Frame(f, bg=C["bg"])
        fluor_f.pack(fill="x", pady=4)
        tk.Label(fluor_f, text="4. Faz bochecho com flúor?", font=FONT_SM, bg=C["bg"]).pack(side="left")
        self.v_fluor = tk.StringVar(value="Não")
        tk.Radiobutton(fluor_f, text="Sim", variable=self.v_fluor, value="Sim", bg=C["bg"]).pack(side="left", padx=4)
        tk.Radiobutton(fluor_f, text="Não", variable=self.v_fluor, value="Não", bg=C["bg"]).pack(side="left")
        self.v_fluor_qual = tk.StringVar()
        tk.Entry(fluor_f, textvariable=self.v_fluor_qual, font=FONT_BODY, bg=C["card"], width=20).pack(side="left", padx=6)

        lingua_f = tk.Frame(f, bg=C["bg"])
        lingua_f.pack(fill="x", pady=4)
        tk.Label(lingua_f, text="5. Escova regularmente a língua?", font=FONT_SM, bg=C["bg"]).pack(side="left")
        self.v_escova_lingua = tk.StringVar(value="Sim")
        tk.Radiobutton(lingua_f, text="Sim", variable=self.v_escova_lingua, value="Sim", bg=C["bg"]).pack(side="left", padx=4)
        tk.Radiobutton(lingua_f, text="Não", variable=self.v_escova_lingua, value="Não", bg=C["bg"]).pack(side="left")

        # ── 4. HÁBITOS DELETÉRIOS
        section_header("4. HÁBITOS DELETÉRIOS")
        self.deleterios_vars = {}
        del_card = tk.Frame(f, bg=C["card"], highlightbackground=C["border"], highlightthickness=1, padx=10, pady=8)
        del_card.pack(fill="x")
        
        for item in DELETERIOS_LISTA:
            v = tk.BooleanVar()
            tk.Checkbutton(del_card, text=item, variable=v, bg=C["card"], font=FONT_SM).pack(anchor="w")
            self.deleterios_vars[item] = v

        infantis = [("Sucção de Dedos", "suc_dedos"), ("Sucção de Chupeta", "suc_chupeta"), ("Mamadeira", "mamadeira")]
        self.infantis_vars = {}
        for label, key in infantis:
            row_inf = tk.Frame(del_card, bg=C["card"])
            row_inf.pack(fill="x", pady=2)
            v_chk = tk.BooleanVar()
            tk.Checkbutton(row_inf, text=label, variable=v_chk, bg=C["card"], font=FONT_SM).pack(side="left")
            tk.Label(row_inf, text="Abandonou com quantos anos?", font=FONT_SM, bg=C["card"], fg=C["muted"]).pack(side="left", padx=(10, 4))
            v_idade = tk.StringVar()
            tk.Entry(row_inf, textvariable=v_idade, font=FONT_BODY, bg=C["bg"], width=6).pack(side="left")
            self.infantis_vars[key] = (v_chk, v_idade)

        # ── 5. HÁBITOS ALIMENTARES
        section_header("5. HÁBITOS ALIMENTARES")
        opcoes_alim = ["1x ao dia", "2x ao dia", "3 ou + vezes ao dia", "Alguns dias da semana", "Não tomo"]
        
        tk.Label(f, text="Frequência que toma café:", font=FONT_SM, bg=C["bg"]).pack(anchor="w")
        self.v_cafe = tk.StringVar(value="1x ao dia")
        ttk.Combobox(f, textvariable=self.v_cafe, values=opcoes_alim, state="readonly").pack(fill="x", ipady=2, pady=2)

        tk.Label(f, text="Frequência que toma refrigerantes:", font=FONT_SM, bg=C["bg"]).pack(anchor="w", pady=(4, 0))
        self.v_refri = tk.StringVar(value="Não tomo")
        ttk.Combobox(f, textvariable=self.v_refri, values=opcoes_alim, state="readonly").pack(fill="x", ipady=2, pady=2)

        tk.Label(f, text="Frequência que toma chimarrão:", font=FONT_SM, bg=C["bg"]).pack(anchor="w", pady=(4, 0))
        self.v_chima = tk.StringVar(value="Não tomo")
        ttk.Combobox(f, textvariable=self.v_chima, values=opcoes_alim, state="readonly").pack(fill="x", ipady=2, pady=2)

        # ── 6. EXAMES GERAIS
        section_header("6. EXAMES GERAIS & INTRAORAL")
        tk.Label(f, text="Tipo de Dentição:", font=FONT_SM, bg=C["bg"]).pack(anchor="w")
        self.v_denticao = tk.StringVar(value="Dentição permanente")
        ttk.Combobox(f, textvariable=self.v_denticao, values=["Dentição decídua incompleta", "Dentição decídua", "Dentição mista", "Dentição permanente"], state="readonly").pack(fill="x", ipady=2, pady=2)

        tk.Label(f, text="Avaliação de Tecidos Moles:", font=FONT_BOLD, bg=C["bg"]).pack(anchor="w", pady=(8, 4))
        grid_tec = tk.Frame(f, bg=C["card"], highlightbackground=C["border"], highlightthickness=1, padx=10, pady=8)
        grid_tec.pack(fill="x")
        self.tec_vars = {}
        for idx, tec in enumerate(TECIDOS_MOLES):
            tk.Label(grid_tec, text=tec, font=FONT_SM, bg=C["card"]).grid(row=idx, column=0, sticky="w", pady=2)
            v = tk.StringVar(value="Normais")
            ttk.Combobox(grid_tec, textvariable=v, values=["Normais", "Alterados"], state="readonly", width=12).grid(row=idx, column=1, sticky="w", padx=10, pady=2)
            self.tec_vars[tec] = v

        tk.Label(f, text="Observações intraoral:", font=FONT_SM, bg=C["bg"]).pack(anchor="w", pady=(8, 0))
        self.obs_intra_txt = tk.Text(f, height=2, font=FONT_BODY, bg=C["card"], highlightbackground=C["border"], highlightthickness=1)
        self.obs_intra_txt.pack(fill="x", pady=2)

        tk.Label(f, text="Outras informações clínicas odontológicas (ortodontia, cirurgia, etc.):", font=FONT_SM, bg=C["bg"]).pack(anchor="w", pady=(6, 0))
        self.outras_info_txt = tk.Text(f, height=2, font=FONT_BODY, bg=C["card"], highlightbackground=C["border"], highlightthickness=1)
        self.outras_info_txt.pack(fill="x", pady=2)

        tk.Button(self, text="💾 Salvar Anamnese Completa", font=FONT_BOLD, bg=C["teal"], fg=C["white"], bd=0, padx=20, pady=12, cursor="hand2", command=self._salvar).pack(pady=12)

    def _salvar(self):
        queixa = self.queixa_txt.get("1.0", "end").strip()
        
        dados_completos = {
            "queixa": queixa,
            "historico": {k: (v1.get(), v2.get() if v2 else None) for k, (v1, v2) in self.hist_vars.items()},
            "patologias": {k: v.get() for k, v in self.patologia_vars.items()},
            "frequencia_visita": self.v_frequencia_visita.get(),
            "ult_visita_data": self.v_ult_visita_data.get(),
            "higiene": {
                "escovacao": self.v_escovacao.get(),
                "creme_dental": self.v_creme_dental.get(),
                "fio_dental": self.v_fio_dental.get(),
                "fluor": self.v_fluor.get(),
                "fluor_qual": self.v_fluor_qual.get(),
                "escova_lingua": self.v_escova_lingua.get(),
            },
            "deleterios": {k: v.get() for k, v in self.deleterios_vars.items()},
            "infantis": {k: (v1.get(), v2.get()) for k, (v1, v2) in self.infantis_vars.items()},
            "alimentares": {
                "cafe": self.v_cafe.get(),
                "refri": self.v_refri.get(),
                "chima": self.v_chima.get(),
            },
            "exames": {
                "denticao": self.v_denticao.get(),
                "tecidos": {k: v.get() for k, v in self.tec_vars.items()},
                "obs_intra": self.obs_intra_txt.get("1.0", "end").strip(),
                "outras_info": self.outras_info_txt.get("1.0", "end").strip(),
            }
        }

        conn = get_conn()
        conn.execute(
            "INSERT INTO anamnese(paciente_id, queixa, habitos, obs, dados_json) VALUES(?,?,?,?,?)",
            (self.pac_id, queixa, self.v_escovacao.get(), self.obs_intra_txt.get("1.0", "end").strip(), json.dumps(dados_completos, ensure_ascii=False)))
        
        registrar_atualizacao(conn, self.pac_id, "Anamnese", f"Ficha de anamnese completa preenchida.")
        conn.commit()
        conn.close()

        if self.callback: self.callback()
        messagebox.showinfo("Sucesso", "✅ Anamnese salva com sucesso!")
        self.destroy()

# ══════════════════════════════════════════════════════════════════════
#  FORMULÁRIO CONSULTA (Com Histórico do Odontograma Acumulado)
# ══════════════════════════════════════════════════════════════════════
class FormConsulta(tk.Toplevel):
    def __init__(self, master, pac_id, callback=None):
        super().__init__(master)
        self.pac_id = pac_id
        self.callback = callback
        
        # Carrega automaticamente todo o histórico do odontograma acumulado do paciente
        self.odontograma_data = obter_odontograma_acumulado(pac_id)
        
        self.title("Registrar Visita")
        self.geometry("480x520")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self._build()
 
    def _build(self):
        tk.Label(self, text="Registrar Visita/Consulta", font=FONT_H2,
                 bg=C["bg"], fg=C["text"]).pack(pady=(16, 10))
 
        f = tk.Frame(self, bg=C["bg"], padx=30)
        f.pack(fill="both", expand=True)
 
        tk.Label(f, text="Data", font=FONT_SM, bg=C["bg"], fg=C["muted"]).pack(anchor="w")
        self.v_data = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M"))
        tk.Entry(f, textvariable=self.v_data, font=FONT_BODY, relief="flat",
                 bg=C["card"], highlightbackground=C["border"], highlightthickness=1).pack(fill="x", ipady=4, pady=(2, 8))
 
        tk.Label(f, text="Tipo de visita", font=FONT_SM, bg=C["bg"], fg=C["muted"]).pack(anchor="w")
        self.v_tipo = tk.StringVar(value="Consulta")
        ttk.Combobox(f, textvariable=self.v_tipo, font=FONT_BODY, state="readonly",
                     values=["Consulta", "Retorno", "Urgência", "Procedimento"]).pack(fill="x", ipady=2, pady=(2, 8))
 
        tk.Label(f, text="Procedimento executado", font=FONT_SM, bg=C["bg"], fg=C["muted"]).pack(anchor="w")
        self.v_proc = tk.StringVar()
        tk.Entry(f, textvariable=self.v_proc, font=FONT_BODY, relief="flat",
                 bg=C["card"], highlightbackground=C["border"], highlightthickness=1).pack(fill="x", ipady=4, pady=(2, 8))
 
        row = tk.Frame(f, bg=C["bg"])
        row.pack(fill="x", pady=4)
        c1 = tk.Frame(row, bg=C["bg"])
        c1.pack(side="left", fill="x", expand=True, padx=(0, 6))
        c2 = tk.Frame(row, bg=C["bg"])
        c2.pack(side="left")
 
        tk.Label(c1, text="Valor total R$", font=FONT_SM, bg=C["bg"], fg=C["muted"]).pack(anchor="w")
        self.v_valor = tk.StringVar()
        tk.Entry(c1, textvariable=self.v_valor, font=FONT_BODY, relief="flat",
                 bg=C["card"], highlightbackground=C["border"], highlightthickness=1).pack(fill="x", ipady=4, pady=2)
 
        tk.Label(c2, text="Pagamento", font=FONT_SM, bg=C["bg"], fg=C["muted"]).pack(anchor="w")
        self.v_pago = tk.IntVar(value=0)
        tk.Checkbutton(c2, text="Visita Paga", variable=self.v_pago, font=FONT_BODY,
                       bg=C["bg"], fg=C["text"], selectcolor=C["card"]).pack(pady=4)
 
        tk.Label(f, text="Dentes associados", font=FONT_SM, bg=C["bg"], fg=C["muted"]).pack(anchor="w", pady=(8, 0))
        odo_frame = tk.Frame(f, bg=C["bg"])
        odo_frame.pack(fill="x", pady=2)
        tk.Button(odo_frame, text="🦷 Abrir Odontograma da Visita", font=FONT_BOLD,
                  bg=C["accent"], fg=C["white"], bd=0, padx=12, pady=6, cursor="hand2",
                  command=self._abrir_odontograma_window).pack(side="left")
        
        n_ini = len(self.odontograma_data)
        txt_status = f"✅ {n_ini} dente(s) carregado(s) do histórico." if n_ini else "Nenhum dente marcado ainda."
        self.lbl_odonto_status = tk.Label(odo_frame, text=txt_status,
                                           font=FONT_SM, bg=C["bg"], fg=C["success"] if n_ini else C["muted"])
        self.lbl_odonto_status.pack(side="left", padx=10)
 
        tk.Label(f, text="Anotações clínicas", font=FONT_SM, bg=C["bg"], fg=C["muted"]).pack(anchor="w", pady=(10, 2))
        self.obs_txt = tk.Text(f, height=3, font=FONT_BODY, relief="flat",
                               bg=C["card"], highlightbackground=C["border"], highlightthickness=1)
        self.obs_txt.pack(fill="x", ipady=4)
 
        tk.Button(self, text="💾 Registrar Visita", font=FONT_BOLD, bg=C["teal"],
                  fg=C["white"], bd=0, padx=22, pady=10, cursor="hand2",
                  command=self._salvar).pack(pady=16)
 
    def _abrir_odontograma_window(self):
        win = tk.Toplevel(self)
        win.title("Odontograma da Visita")
        win.configure(bg=C["bg"])
        win.resizable(False, False)
        win.grab_set()
        tk.Label(win, text="Marque ou altere os dentes tratados nesta visita", font=FONT_H2,
                 bg=C["bg"], fg=C["text"]).pack(pady=10)
 
        odo = OdontogramaWidget(win, dados_iniciais=self.odontograma_data)
        odo.pack(fill="both", expand=True, padx=16)
 
        def _concluir():
            self.odontograma_data = odo.get_dados()
            n = len(self.odontograma_data)
            self.lbl_odonto_status.configure(
                text=f"✅ {n} dente(s) acumulado(s) no histórico." if n else "Nenhum dente marcado ainda.",
                fg=C["success"] if n else C["muted"])
            win.destroy()
 
        tk.Button(win, text="✅ Concluir Odontograma", font=FONT_BOLD, bg=C["accent"],
                  fg=C["white"], bd=0, padx=16, pady=9, cursor="hand2", command=_concluir).pack(pady=12)
 
    def _salvar(self):
        valor = None
        raw = self.v_valor.get().replace(",", ".").strip()
        if raw:
            try:
                valor = float(raw)
            except ValueError:
                messagebox.showerror("Valor inválido", "Digite um número válido para o valor.")
                return
 
        odontograma_json = (json.dumps(self.odontograma_data, ensure_ascii=False) if self.odontograma_data else None)
 
        conn = get_conn()
        conn.execute(
            "INSERT INTO consultas(paciente_id,data,tipo,procedimento,valor,pago,obs,odontograma)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (self.pac_id, self.v_data.get(), self.v_tipo.get(), self.v_proc.get(),
             valor, int(self.v_pago.get()), self.obs_txt.get("1.0", "end").strip(), odontograma_json))
        consulta_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
 
        desc = f"{self.v_tipo.get()} — {self.v_proc.get() or 'sem procedimento'}"
        if valor:
            desc += f" — R$ {valor:.2f}"
        if self.odontograma_data:
            desc += f" — {len(self.odontograma_data)} dente(s) no odontograma"
        registrar_atualizacao(conn, self.pac_id, "Consulta", desc)
        conn.commit()
        conn.close()
 
        if self.odontograma_data:
            self._exportar_odontograma_drive(consulta_id)
 
        if self.callback:
            self.callback()
        self.destroy()
 
    def _exportar_odontograma_drive(self, consulta_id):
        try:
            pac_win = self.master
            app = getattr(pac_win, "master_app", None)
            codigo = getattr(pac_win, "codigo", None)
            nome = getattr(pac_win, "nome", None)
            if not codigo or codigo == "—":
                return
            
            data_pasta = datetime.now().strftime("%Y-%m-%d")
            destino_dir = pasta_paciente(codigo) / data_pasta
            destino_dir.mkdir(exist_ok=True)
            
            arquivo_txt = destino_dir / f"odontograma_{datetime.now().strftime('%H%M%S')}.txt"
            
            linhas = [
                f"RESUMO DO ODONTOGRAMA — {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                f"Paciente: {nome} ({codigo})",
                f"Visita: {self.v_tipo.get()} — {self.v_proc.get() or 'Não especificado'}",
                "-" * 50,
                "DENTES REGISTRADOS:"
            ]
            for dente in sorted(self.odontograma_data, key=lambda d: int(d)):
                info = self.odontograma_data[dente]
                linhas.append(f"Dente {dente} — {info.get('status')}: {info.get('procedimento')}")
            arquivo_txt.write_text("\n".join(linhas), encoding="utf-8")
 
            drive_link = ""
            svc = getattr(app, "gdrive", None) if app else None
            if svc:
                try:
                    root_id = gdrive_get_or_create_folder(svc, "ClinicaDental")
                    pac_folder = gdrive_get_or_create_folder(svc, codigo, root_id)
                    date_folder = gdrive_get_or_create_folder(svc, data_pasta, pac_folder)
                    drive_link = gdrive_upload_file(svc, arquivo_txt, date_folder)
                except Exception:
                    drive_link = ""
 
            conn = get_conn()
            conn.execute(
                "INSERT INTO arquivos(paciente_id,nome,tipo,caminho,drive_link) VALUES(?,?,?,?,?)",
                (self.pac_id, arquivo_txt.name, "txt", str(arquivo_txt), drive_link))
            conn.commit()
            conn.close()
        except Exception as e:
            messagebox.showwarning(
                "Odontograma",
                f"A visita foi salva normalmente, mas houve um erro ao exportar "
                f"o odontograma para o Drive:\n{e}")

# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()