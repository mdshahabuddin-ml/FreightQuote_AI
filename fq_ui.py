"""
FreightQuote AI - enterprise UI layer.

Theme (CSS), login layout pieces, signed-in shell (sidebar + top bar),
the AI Copilot page and the generic module pages.

This module never writes to any database. Every query it runs opens SQLite
in read-only mode, skips credential tables/columns, and limits Customers to
their own rows.
"""

import html
import re
import sqlite3
import time
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------- copy ----
BRAND = "FreightQuote AI"
HERO_LEAD = ("Agents watch your data, raise tickets, and wait for a human to "
             "approve anything that matters.")
HERO_POINTS = [
    "Freight quote requests and live shipment status",
    "AI Copilot that answers from your live data, with sources",
    "Secure sign-in with lockout, OTP and security questions",
    "Role-based access for every workspace",
]

ROLE_BUTTONS = [
    ("Admin", "login_role_admin"),
    ("Operations Manager", "login_role_ops"),
    ("Freight Broker", "login_role_broker"),
    ("Auditor", "login_role_auditor"),
    ("Customer", "login_role_customer"),
]

# ------------------------------------------------------------- navigation ----
# (section, page id, label, material icon)
NAV = [
    ("Assistant", "copilot", "AI Copilot", "auto_awesome"),
    ("Agents", "route", "Route AI", "alt_route"),
    ("Agents", "quotes", "Spot Quotes", "attach_money"),
    ("Agents", "carriers", "Carriers", "local_shipping"),
    ("Agents", "weather", "Weather Risk", "thunderstorm"),
    ("Agents", "margin", "Margin", "trending_up"),
    ("Agents", "customs", "Customs", "description"),
    ("Insights", "reports", "Reports", "summarize"),
    ("Insights", "notifications", "Notifications", "notifications"),
    ("Insights", "graph", "Knowledge Graph", "hub"),
    ("Insights", "twin", "Digital Twin", "deployed_code"),
    ("Platform", "feeds", "Data Feed Center", "upload"),
    ("Platform", "admin", "Admin", "shield"),
    ("Platform", "profile", "My Profile", "person"),
]
PAGE_TITLES = {pid: label for _, pid, label, _ in NAV}
PAGE_TITLES["command"] = "Command Center"

PAGE_SUBTITLES = {
    "copilot": "Agents run first, then the Copilot answers from their fresh evidence in your live data.",
    "command": "Your workspace: quotes, shipments and account actions.",
    "route": "Ports, routes and shipment movement from your live data.",
    "quotes": "Spot quote requests, pricing and approval status.",
    "carriers": "Carrier records and performance from your live data.",
    "weather": "Weather and storm exposure across ports and vessels.",
    "margin": "Quote margins and pricing outliers.",
    "customs": "Customs holds and clearance status.",
    "reports": "Every data table the platform can read, at a glance.",
    "notifications": "Alerts, tickets and items waiting for a human.",
    "graph": "How your records connect across tables.",
    "twin": "A live mirror of shipments and network state.",
    "feeds": "Data sources feeding the platform.",
    "admin": "Users, roles and account lockouts. Read-only view.",
    "profile": "Your account details.",
}

# Keywords that decide which tables a module page shows.
PAGE_KEYWORDS = {
    "route": ["route", "port", "shipment", "vessel", "voyage", "lane"],
    "quotes": ["quote", "rate", "pricing", "request"],
    "carriers": ["carrier", "vendor", "fleet"],
    "weather": ["weather", "storm", "forecast", "wind", "wave"],
    "margin": ["margin", "quote", "price", "cost"],
    "customs": ["custom", "clearance", "hold", "declaration"],
    "notifications": ["notification", "alert", "ticket", "event", "audit", "log"],
    "graph": ["relation", "edge", "node", "graph", "entity"],
    "twin": ["twin", "simulation", "snapshot", "shipment", "vessel"],
    "feeds": ["feed", "source", "import", "upload", "ingest"],
}

ALL_ROLES = {"admin", "operations manager", "freight broker", "auditor", "customer"}
PAGE_ROLES = {
    "admin": {"admin"},
    "route": ALL_ROLES - {"customer"},
    "carriers": ALL_ROLES - {"customer"},
    "weather": ALL_ROLES - {"customer"},
    "margin": ALL_ROLES - {"customer"},
    "customs": ALL_ROLES - {"customer"},
    "graph": ALL_ROLES - {"customer"},
    "twin": ALL_ROLES - {"customer"},
    "feeds": ALL_ROLES - {"customer"},
    "reports": ALL_ROLES - {"customer"},
}

# -------------------------------------------------------------- data safety ----
SENSITIVE_TABLES = {
    "password_resets", "login_attempts", "answer_attempts", "auth_users",
    "sqlite_sequence", "sqlite_stat1", "sqlite_stat4",
}
SENSITIVE_COL_RE = re.compile(r"(hash|password|passwd|otp|secret|token|salt|api_?key)", re.I)
OWNER_ID_COLS = ("user_id", "customer_id", "owner_id", "created_by", "requested_by")
OWNER_EMAIL_COLS = ("email", "customer_email", "user_email", "requester_email")
STATUS_COLS = ("status", "state", "current_status", "quote_status", "shipment_status",
               "approval_status", "severity", "current_severity", "risk_level")
ATTENTION_RE = re.compile(
    r"(pending|hold|delay|reject|fail|error|overdue|open|review|await|block|"
    r"cancel|high|critical|risk|exception)", re.I)
DATE_COL_RE = re.compile(r"(_at$|date|time|created|updated)", re.I)

# ======================================================================= CSS ====

_TOKENS = """
:root{
  --fq-primary:#5b5bd6; --fq-primary-600:#4f46e5; --fq-primary-50:#eef0ff;
  --fq-primary-100:#e0e3ff; --fq-text:#1f2937; --fq-text-2:#374151;
  --fq-muted:#6b7280; --fq-subtle:#9ca3af; --fq-border:#e7e9ef;
  --fq-border-2:#dfe2e8; --fq-bg:#f7f8fb; --fq-card:#ffffff;
  --fq-green:#22c55e; --fq-red:#dc2626; --fq-amber:#d97706; --fq-teal:#0f766e;
}
"""

BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
%(tokens)s
html, body, .stApp{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;}
.stApp :is(p,span,div,label,input,textarea,button,h1,h2,h3,h4,h5,h6,li,td,th,a,small,strong,summary)
  :not([data-testid="stIconMaterial"]):not(code *):not(pre *){font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;}
.stApp{background:var(--fq-bg); color:var(--fq-text);}
#MainMenu, footer, [data-testid="stDeployButton"], [data-testid="stAppDeployButton"],
[data-testid="stStatusWidget"], [data-testid="stDecoration"], [data-testid="stMainMenu"]{display:none !important;}
header[data-testid="stHeader"]{background:transparent; pointer-events:none;}
header[data-testid="stHeader"] *{pointer-events:auto;}
[data-testid="stSidebarNav"], [data-testid="stSidebarNavSeparator"]{display:none !important;}
[data-testid="stMarkdownContainer"]:has(.fq-nav-label, .fq-brand, .fq-topbar, .fq-hero, .fq-answer, .fq-msg-user,
  .fq-demo-label, .fq-welcome, .fq-section-title, .fq-kpis, .fq-card, .fq-empty, .fq-auth-title, .fq-table-wrap){margin-bottom:0 !important;}

/* headings */
.stApp h1, .stApp h2, .stApp h3{color:var(--fq-text); letter-spacing:-.015em; font-weight:700;}
.stApp h2{font-size:1.25rem;} .stApp h3{font-size:1.05rem;}
[data-testid="stCaptionContainer"], .stCaption{color:var(--fq-muted) !important;}

/* labels + inputs */
[data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label{font-size:12px !important; font-weight:500 !important; color:var(--fq-text-2) !important;}
[data-testid="stTextInputRootElement"], .stSelectbox [data-rac][role="group"], .stMultiSelect [data-rac][role="group"],
.stTextInput [data-baseweb="input"], .stNumberInput [data-baseweb="input"], .stDateInput [data-baseweb="input"],
.stTextArea [data-baseweb="textarea"], .stSelectbox [data-baseweb="select"] > div, .stMultiSelect [data-baseweb="select"] > div{
  background:#fff !important; border:1px solid var(--fq-border-2) !important; border-radius:8px !important; box-shadow:none !important;}
.stTextInput [data-baseweb="base-input"], .stTextArea [data-baseweb="base-input"], .stNumberInput [data-baseweb="base-input"]{background:#fff !important;}
[data-testid="stTextInputRootElement"]:focus-within, .stSelectbox [data-rac][role="group"]:focus-within,
.stTextInput [data-baseweb="input"]:focus-within, .stTextArea [data-baseweb="textarea"]:focus-within,
.stNumberInput [data-baseweb="input"]:focus-within, .stSelectbox [data-baseweb="select"] > div:focus-within{
  border-color:#a5b4fc !important; box-shadow:0 0 0 3px rgba(99,102,241,.13) !important;}
.stTextInput input, .stNumberInput input, .stTextArea textarea{font-size:13px !important; color:var(--fq-text) !important;}
.stTextInput input{padding:8px 11px !important; background:transparent !important;}
[data-testid="stTextInputRootElement"]{min-height:36px; overflow:hidden;}
.stSelectbox [data-rac][role="group"]{min-height:34px;}
.stSelectbox input{font-size:13px !important; color:var(--fq-text) !important;}
.stTextArea textarea{border:1px solid var(--fq-border-2) !important; border-radius:8px !important; background:#fff !important;}
.stSelectbox [data-baseweb="select"] div{font-size:13px;}

/* buttons */
.stButton button, .stFormSubmitButton button, .stDownloadButton button, .stLinkButton a{
  border-radius:8px !important; font-size:13px !important; font-weight:500 !important;
  min-height:34px; padding:6px 14px; box-shadow:none; transition:background .15s, border-color .15s, color .15s;}
.stButton button p, .stFormSubmitButton button p{font-size:13px !important; font-weight:inherit;}
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"]{
  background:var(--fq-primary) !important; border:1px solid var(--fq-primary) !important; color:#fff !important;}
button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover{
  background:var(--fq-primary-600) !important; border-color:var(--fq-primary-600) !important;}
button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-secondaryFormSubmit"]{
  background:#fff !important; border:1px solid var(--fq-border-2) !important; color:var(--fq-text-2) !important;}
button[data-testid="stBaseButton-secondary"]:hover, button[data-testid="stBaseButton-secondaryFormSubmit"]:hover{
  border-color:#c7d2fe !important; color:var(--fq-primary) !important; background:#fafaff !important;}
button[data-testid="stBaseButton-tertiary"], button[data-testid="stBaseButton-tertiaryFormSubmit"]{
  color:var(--fq-primary) !important; padding:0 2px !important; min-height:0 !important;}
button[data-testid="stBaseButton-tertiary"]:hover, button[data-testid="stBaseButton-tertiaryFormSubmit"]:hover{
  color:var(--fq-primary-600) !important; text-decoration:underline;}
button:focus-visible{outline:2px solid #a5b4fc !important; outline-offset:2px;}

/* radio as segmented control */
.stRadio [role="radiogroup"]{gap:6px; flex-wrap:wrap;}
.stRadio [role="radiogroup"] > label{background:#fff; border:1px solid var(--fq-border-2); border-radius:8px; padding:5px 12px 5px 8px; margin:0;}
.stRadio [role="radiogroup"] > label:has(input:checked){border-color:#a5b4fc; background:var(--fq-primary-50);}
.stRadio [role="radiogroup"] > label p{font-size:12.5px !important;}

/* alerts, expanders, containers, tabs */
[data-testid="stAlert"]{border-radius:10px;}
[data-testid="stAlert"] p{font-size:13px;}
[data-testid="stExpander"] details{border:1px solid var(--fq-border) !important; border-radius:10px !important; background:#fff;}
[data-testid="stExpander"] summary p{font-size:13px; font-weight:600;}
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]){border-radius:12px;}
.stTabs [data-baseweb="tab"] p{font-size:13px; font-weight:500;}
.stTabs [aria-selected="true"] p{color:var(--fq-primary);}
.stTabs [data-baseweb="tab-highlight"]{background:var(--fq-primary);}
hr{border-color:var(--fq-border) !important;}
[data-testid="stMetric"]{background:#fff; border:1px solid var(--fq-border); border-radius:12px; padding:12px 14px;}
[data-testid="stMetricLabel"] p{font-size:12px; color:var(--fq-muted);}
[data-testid="stDataFrame"]{border:1px solid var(--fq-border); border-radius:10px; overflow:hidden;}

/* shared components */
.fq-badge{display:inline-flex; align-items:center; justify-content:center; min-width:46px; padding:2px 10px;
  border-radius:999px; font-size:11px; font-weight:600; line-height:16px; border:1px solid; white-space:nowrap;}
.fq-badge.high{color:#dc2626; background:#fef2f2; border-color:#fecaca;}
.fq-badge.medium{color:#b45309; background:#fffbeb; border-color:#fde68a;}
.fq-badge.low{color:#0f766e; background:#f0fdfa; border-color:#99f6e4;}
.fq-badge.info{color:#4f46e5; background:#eef2ff; border-color:#c7d2fe;}
.fq-badge.none{color:#6b7280; background:#f9fafb; border-color:#e5e7eb;}
.fq-table-wrap{border:1px solid var(--fq-border); border-radius:10px; overflow:auto; background:#fff; max-width:100%;}
table.fq-table{width:100%; border-collapse:collapse; font-size:12px; color:var(--fq-text-2); margin:0;}
table.fq-table th, table.fq-table td{font-size:12px !important; line-height:1.4 !important;}
table.fq-table th{background:#fafbfc; color:var(--fq-text-2); font-weight:600; text-align:left; padding:8px 12px !important;
  border:0 !important; border-bottom:1px solid var(--fq-border) !important; white-space:nowrap;}
table.fq-table td{padding:6px 12px !important; border:0 !important; border-bottom:1px solid #f0f1f5 !important; white-space:nowrap; max-width:320px;
  overflow:hidden; text-overflow:ellipsis;}
table.fq-table tr:last-child td{border-bottom:0 !important;}
table.fq-table tr:hover td{background:#fafaff;}
.fq-card{background:#fff; border:1px solid var(--fq-border); border-radius:12px; padding:16px 18px; margin-bottom:12px;}
.fq-card .h{margin:0 0 4px; font-size:14px !important; font-weight:600; color:var(--fq-text);}
.fq-card p{margin:0; font-size:12.5px; color:var(--fq-muted);}
.fq-empty{background:#fff; border:1px dashed #d6d9e2; border-radius:12px; padding:28px 22px; text-align:center;}
.fq-empty .h{margin:0 0 6px; font-size:14px !important; font-weight:600; color:var(--fq-text);}
.fq-empty p{margin:0 auto; font-size:12.5px; color:var(--fq-muted); max-width:520px;}
""".replace("%(tokens)s", _TOKENS)

LOGIN_CSS = """
.block-container{padding:0 !important; max-width:100% !important;}
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"]{display:none !important;}
header[data-testid="stHeader"]{display:none !important;}
.stApp{background:#fff;}
[data-testid="stMain"], .main{padding:0 !important;}
[data-testid="stMainBlockContainer"]{padding:0 !important;}
.st-key-fq_login{gap:0 !important;}
.st-key-fq_login > div > [data-testid="stHorizontalBlock"], .st-key-fq_login [data-testid="stHorizontalBlock"]:has(.fq-hero){
  gap:0 !important; min-height:100vh; align-items:stretch !important; flex-wrap:nowrap;}
[data-testid="stColumn"]:has(.fq-hero){
  background:linear-gradient(162deg,#7d86f6 0%,#6168e0 30%,#5459d4 52%,#3f7fc0 76%,#14a39b 100%);
  padding:0 !important; display:flex; flex-direction:column; justify-content:center; position:relative; overflow:hidden;}
[data-testid="stColumn"]:has(.fq-hero) > div{width:100%;}
[data-testid="stColumn"]:has(.st-key-fq_auth_panel){background:#fff; padding:0 !important;}
.fq-hero{padding:48px clamp(28px,4vw,44px); color:#fff; position:sticky; top:0; z-index:1; min-height:100vh;
  display:flex; flex-direction:column; justify-content:center; box-sizing:border-box;}
.fq-hero h1{color:#fff !important; font-size:clamp(26px,2.4vw,31px) !important; font-weight:700 !important; margin:0 0 16px !important;
  padding:0 !important; letter-spacing:-.02em; line-height:1.15;}
.fq-hero .lead{font-size:13px; line-height:1.6; color:rgba(255,255,255,.88); margin:0 0 20px; max-width:330px;}
.fq-hero ul{list-style:none; margin:0; padding:0;}
.fq-hero li{display:flex; align-items:center; gap:10px; font-size:12.5px; color:rgba(255,255,255,.92); margin:0 0 9px; padding:0;}
.fq-hero li::before{content:""; width:6px; height:6px; border-radius:50%; background:#7ee8e0; flex:0 0 6px; box-shadow:0 0 0 3px rgba(126,232,224,.18);}
.st-key-fq_auth_panel{max-width:400px; margin:0 auto; padding:%(pad_top)s 28px 40px !important; gap:12px !important;}
.fq-auth-title{font-size:28px; font-weight:700; color:#1f2937; letter-spacing:-.025em; line-height:1.1; margin:0 0 6px;}
.fq-auth-sub{font-size:11.5px !important; color:#6b7280; margin:0; line-height:1.4;}
.fq-auth-heading{font-size:15px; font-weight:600; color:#1f2937; margin:6px 0 0;}
.fq-status{display:flex; align-items:center; gap:9px; background:#eef1ff; border:1px solid #d3d9fe; color:#3c3f8f;
  border-radius:7px; padding:8px 12px; font-size:12px; margin:14px 0 6px;}
.fq-status .ring{width:11px; height:11px; border-radius:50%; border:2px solid #c7cdfb; border-top-color:#5b5bd6; flex:0 0 11px;
  animation:fqspin 1.1s linear infinite;}
.fq-status .ok{width:8px; height:8px; border-radius:50%; background:#22c55e; box-shadow:0 0 0 3px rgba(34,197,94,.18); flex:0 0 8px;}
@keyframes fqspin{to{transform:rotate(360deg)}}
.st-key-fq_auth_panel [data-testid="stForm"]{padding:0; border:0;}
.st-key-fq_auth_panel [data-testid="stForm"] [data-testid="stVerticalBlock"]{gap:10px;}
.st-key-fq_auth_panel .stTextInput [data-baseweb="input"]{min-height:38px;}
.st-key-fq_auth_links{justify-content:flex-end; align-items:center; gap:8px !important;}
.st-key-fq_auth_links > div:not(:first-child)::before{content:"\\00B7"; color:#9ca3af; margin-right:8px; font-size:13px;}
.st-key-fq_auth_links > div{display:flex; align-items:center; width:auto !important;}
.st-key-fq_auth_links button p{font-size:12.5px !important; font-weight:500 !important;}
.fq-demo-label{font-size:11.5px; color:#6b7280; margin:8px 0 0;}
.st-key-fq_role_chips{gap:7px !important; flex-wrap:wrap;}
.st-key-fq_role_chips > div{width:auto !important;}
.st-key-fq_role_chips button{min-height:26px !important; padding:3px 11px !important; border-radius:999px !important;}
.st-key-fq_role_chips button p{font-size:11.5px !important;}
.st-key-fq_role_chips button[data-testid="stBaseButton-secondary"]{border-color:#e3e5ea !important; color:#374151 !important;}
@media (max-width: 860px){
  .fq-hero{padding:36px 26px;}
  .fq-hero h1{font-size:26px !important;}
  .st-key-fq_auth_panel{padding:48px 22px 36px !important;}
}
@media (max-width: 640px){
  .st-key-fq_login [data-testid="stHorizontalBlock"]:has(.fq-hero){flex-wrap:wrap; min-height:0;}
  [data-testid="stColumn"]:has(.fq-hero), [data-testid="stColumn"]:has(.st-key-fq_auth_panel){width:100% !important; flex:1 1 100% !important; min-width:100% !important;}
  .fq-hero{padding:30px 20px 26px; min-height:0;}
  .fq-hero ul{display:none;}
  .fq-hero .lead{margin:0;}
  .st-key-fq_auth_panel{padding:28px 18px 36px !important;}
}
"""

APP_CSS = """
.block-container, [data-testid="stMainBlockContainer"]{padding:0 28px 40px !important; max-width:100% !important;}
section[data-testid="stSidebar"]{background:#fff !important; border-right:1px solid var(--fq-border);}
[data-testid="stSidebar"][data-collapsed="false"], section[data-testid="stSidebar"][aria-expanded="true"]{width:244px !important; min-width:244px !important; max-width:244px !important;}
[data-testid="stSidebarHeader"]{height:auto !important; min-height:0 !important; padding:8px 10px 0 !important; margin:0 !important;}
[data-testid="stSidebarContent"]{padding:0 !important;}
[data-testid="stSidebarUserContent"]{padding:0 10px 18px !important;}
[data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"]{gap:2px !important;}
.fq-brand{display:flex; align-items:center; gap:10px; padding:2px 4px 12px;}
.fq-logo{width:34px; height:34px; border-radius:10px; flex:0 0 34px; display:flex; align-items:center; justify-content:center;
  background:linear-gradient(140deg,#7178f2,#5b5bd6 60%,#4f46e5); box-shadow:0 3px 10px rgba(91,91,214,.28);}
.fq-brand .name{font-size:13.5px; font-weight:700; color:#111827; line-height:1.2; letter-spacing:-.01em;}
.fq-brand .who{font-size:10.5px; color:#6b7280; line-height:1.3; margin-top:1px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:172px;}
.st-key-fq_search{position:relative; margin-bottom:6px;}
.st-key-fq_search [data-baseweb="input"]{background:#f9fafb !important; border-color:#eceef2 !important; min-height:32px;}
.st-key-fq_search [data-baseweb="base-input"]{background:#f9fafb !important;}
.st-key-fq_search input{font-size:12px !important; padding:6px 52px 6px 10px !important;}
.st-key-fq_search::after{content:"Ctrl K"; position:absolute; right:8px; top:50%; transform:translateY(-50%); font-size:10px; color:#6b7280;
  border:1px solid #e5e7eb; background:#fff; border-radius:5px; padding:1px 6px; pointer-events:none; font-weight:500;}
.fq-nav-label{display:block; font-size:10.5px; font-weight:600; letter-spacing:.07em; color:#9ca3af; text-transform:uppercase;
  line-height:16px; margin:0; padding:14px 8px 4px;}
.st-key-fq_nav .stButton button{justify-content:flex-start !important; background:transparent !important; border:0 !important;
  color:#374151 !important; min-height:32px !important; padding:6px 10px !important; border-radius:8px !important; box-shadow:none !important;}
.st-key-fq_nav .stButton button > div, .st-key-fq_nav .stButton button > span{justify-content:flex-start !important;}
.st-key-fq_nav .stButton button:hover{background:#f4f5f8 !important; color:#111827 !important;}
.st-key-fq_nav .stButton button p{font-size:13px !important; font-weight:500 !important;}
.st-key-fq_nav .stButton button [data-testid="stIconMaterial"]{font-size:17px !important; color:#6b7280; margin-right:4px;}
.st-key-fq_nav .st-key-nav_%(active)s button, .st-key-fq_nav .st-key-nav_%(active)s button:hover{background:var(--fq-primary-50) !important; color:#4338ca !important;}
.st-key-fq_nav .st-key-nav_%(active)s button p{font-weight:600 !important;}
.st-key-fq_nav .st-key-nav_%(active)s button [data-testid="stIconMaterial"]{color:#4f46e5 !important;}
.st-key-fq_nav .st-key-nav_command{margin-top:12px;}
.st-key-fq_nav .st-key-nav_command button, .st-key-fq_nav .st-key-nav_command button:hover{background:linear-gradient(135deg,#6366f1,#7f80f3) !important; color:#fff !important;
  box-shadow:0 4px 12px rgba(99,102,241,.28) !important; min-height:36px !important;}
.st-key-fq_nav .st-key-nav_command button p, .st-key-fq_nav .st-key-nav_command button:hover p{font-weight:600 !important; color:#fff !important;}
.st-key-fq_nav .st-key-nav_command button [data-testid="stIconMaterial"], .st-key-fq_nav .st-key-nav_command button:hover [data-testid="stIconMaterial"]{color:#fff !important;}
.st-key-fq_nav .st-key-nav_command button:hover{filter:brightness(1.05);}
%(command_active)s
.st-key-fq_signout{margin-top:22px;}
.st-key-fq_signout button{min-height:28px !important; padding:3px 12px !important; font-size:12px !important;}
.st-key-fq_signout button p{font-size:12px !important;}
.fq-topbar{display:flex; align-items:flex-start; justify-content:space-between; gap:16px; flex-wrap:wrap;
  background:#fff; margin:0 -28px 0; padding:14px 28px 8px;}
.fq-topbar .title{font-size:19px; font-weight:700; color:#111827; letter-spacing:-.015em; line-height:1.25;}
.fq-topbar .subtitle{font-size:12px; color:#6b7280; margin-top:3px; max-width:420px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.fq-pills{display:flex; gap:8px; flex-wrap:wrap; align-items:center; padding-top:2px;}
.fq-pill{display:inline-flex; align-items:center; gap:7px; font-size:11px; color:#4b5563; background:#fff; border:1px solid var(--fq-border);
  border-radius:999px; padding:4px 11px; white-space:nowrap;}
.fq-pill .dot{width:7px; height:7px; border-radius:50%; background:#22c55e;}
.fq-pill .dot.grey{background:#9ca3af;} .fq-pill .dot.amber{background:#f59e0b;}
.st-key-fq_toolbar{background:#fff; margin:-16px -28px 18px !important; padding:4px 28px 12px; border-bottom:1px solid var(--fq-border);
  width:calc(100% + 56px) !important; max-width:none !important; box-sizing:border-box;}
.st-key-fq_toolbar .stSelectbox{max-width:176px;}
.st-key-fq_toolbar [data-baseweb="select"] > div{min-height:32px !important;}
.st-key-fq_page_gap{height:18px;}
/* copilot */
.st-key-fq_chat{background:#fff; border:1px solid var(--fq-border); border-radius:14px; padding:18px 20px 20px !important; gap:14px !important;}
.fq-msg-user{display:flex; justify-content:flex-end;}
.fq-msg-user span{background:var(--fq-primary); color:#fff; padding:10px 14px; border-radius:12px 12px 4px 12px; font-size:13px;
  max-width:min(560px,85%); line-height:1.45; box-shadow:0 2px 8px rgba(91,91,214,.22); white-space:pre-wrap; word-break:break-word;}
.fq-answer{background:#fff; border:1px solid var(--fq-border); border-radius:12px; padding:12px 14px 14px; max-width:780px; box-shadow:0 1px 2px rgba(16,24,40,.04);}
.fq-trace{font-size:11px; color:#6b7280; line-height:1.75;}
.fq-trace div::before, .fq-trace summary::before{content:"\\203A\\00a0"; color:#9ca3af;}
.fq-trace details{margin:0;}
.fq-trace summary{list-style:none; cursor:pointer; color:#4f46e5; font-weight:600;}
.fq-trace summary::-webkit-details-marker{display:none;}
.fq-trace details[open] summary::before{content:"\\25BE\\00a0";}
.fq-trace summary::before{content:"\\25B8\\00a0"; color:#4f46e5;}
.fq-trace .src{padding-left:10px;}
.fq-trace pre{background:#f8fafc; border:1px solid var(--fq-border); border-radius:8px; padding:8px 10px; font-size:11px; color:#334155;
  white-space:pre-wrap; margin:4px 0 2px; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}
.fq-watch{border:1px solid var(--fq-border); border-radius:10px; margin:10px 0 12px; overflow:hidden;}
.fq-watch .row{display:grid; grid-template-columns:minmax(110px,150px) 80px 1fr; align-items:center; gap:12px; padding:9px 12px;
  border-bottom:1px solid #f0f1f5; font-size:12px; color:#374151;}
.fq-watch .row:last-child{border-bottom:0;}
.fq-watch .name{font-weight:500; color:#1f2937; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.fq-headline{font-size:12.5px !important; color:#374151; margin:0 0 8px; line-height:1.5;}
.fq-headline b{color:#111827;}
.fq-answer .note{font-size:12.5px; color:#374151; margin:2px 0 8px;}
.fq-welcome{padding:6px 2px 2px;}
.fq-welcome .h{margin:0 0 4px; font-size:15px !important; font-weight:600; color:#111827;}
.fq-welcome p{margin:0; font-size:12.5px; color:#6b7280;}
.st-key-fq_suggest{gap:8px !important; flex-wrap:wrap;}
.st-key-fq_suggest > div{width:auto !important;}
.st-key-fq_suggest button{border-radius:999px !important; min-height:28px !important; padding:4px 12px !important;}
.st-key-fq_suggest button p{font-size:12px !important;}
[data-testid="stChatInput"]{border-radius:12px !important; border:1px solid var(--fq-border-2) !important; background:#fff !important; box-shadow:0 2px 6px rgba(16,24,40,.05);}
[data-testid="stChatInput"]:focus-within{border-color:#a5b4fc !important;}
[data-testid="stChatInput"] textarea{font-size:13px !important;}
[data-testid="stBottomBlockContainer"]{padding:12px 28px 18px !important; background:var(--fq-bg);}
[data-testid="stBottom"] > div{background:var(--fq-bg);}
.fq-kpis{display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin:0 0 16px;}
.fq-kpi{background:#fff; border:1px solid var(--fq-border); border-radius:12px; padding:12px 14px;}
.fq-kpi .k{font-size:11.5px; color:#6b7280;} .fq-kpi .v{font-size:20px; font-weight:700; color:#111827; margin-top:2px;}
.fq-section-title{display:flex; align-items:center; justify-content:space-between; gap:10px; margin:4px 0 8px;}
.fq-section-title .h{margin:0; font-size:13.5px !important; font-weight:600; color:#111827;}
.fq-section-title span{font-size:11.5px; color:#6b7280;}
@media (max-width: 760px){
  .block-container, [data-testid="stMainBlockContainer"]{padding:0 16px 32px !important;}
  .fq-topbar{margin:0 -16px; padding:12px 16px 10px;}
  .st-key-fq_toolbar{margin:-16px -16px 14px !important; padding:4px 16px 10px; width:calc(100% + 32px) !important;}
  .fq-topbar .subtitle{white-space:normal;}
  .fq-watch .row{grid-template-columns:1fr auto; }
  .fq-watch .row .txt{grid-column:1 / -1;}
  .st-key-fq_chat{padding:14px 12px 16px !important;}
  [data-testid="stBottomBlockContainer"]{padding:10px 16px 14px !important;}
}
"""

LOGO_SVG = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a9 9 0 1 0 9 9"/>'
            '<path d="M12 7a5 5 0 1 0 5 5"/><circle cx="12" cy="12" r="1.4" fill="#fff"/></svg>')


def _style(css):
    # st.html with only a <style> tag takes no vertical space
    st.html(f"<style>{css}</style>")


def inject_base_css():
    _style(BASE_CSS)


def inject_login_css(mode="Sign In"):
    pad = {"Sign In": "clamp(48px, 21vh, 210px)",
           "Register": "clamp(36px, 7vh, 72px)",
           "Forgot Password": "clamp(40px, 11vh, 120px)"}.get(mode, "clamp(48px, 18vh, 180px)")
    _style(LOGIN_CSS.replace("%(pad_top)s", pad))


def inject_app_css(active):
    cmd = ""
    if active == "command":
        cmd = (".st-key-fq_nav .st-key-nav_command button{box-shadow:0 0 0 3px rgba(99,102,241,.25),"
               "0 4px 12px rgba(99,102,241,.3) !important;}")
    key = "none" if active == "command" else re.sub(r"[^a-z0-9_]", "", active)
    _style(APP_CSS.replace("%(active)s", key).replace("%(command_active)s", cmd))


def esc(value):
    return html.escape("" if value is None else str(value))


def badge(level, text=None):
    level = (level or "none").lower()
    return f'<span class="fq-badge {esc(level)}">{esc(text or level.title())}</span>'


def html_table(columns, rows, numeric_cols=()):
    head = "".join(f"<th>{esc(_pretty(c))}</th>" for c in columns)
    body = []
    for r in rows:
        cells = []
        for c, v in zip(columns, r):
            if isinstance(v, float):
                v = f"{v:,.2f}"
            cells.append(f'<td title="{esc(v)}">{esc(v)}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    if not body:
        body = [f'<tr><td colspan="{max(1, len(columns))}" style="color:#9ca3af">No rows</td></tr>']
    return (f'<div class="fq-table-wrap"><table class="fq-table"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def _pretty(name):
    name = str(name)
    return name[:1].upper() + name[1:]


# ================================================================ LOGIN ====

def render_login_hero():
    points = "".join(f"<li>{esc(p)}</li>" for p in HERO_POINTS)
    st.markdown(
        f'<div class="fq-hero"><h1>{esc(BRAND)}</h1>'
        f'<p class="lead">{esc(HERO_LEAD)}</p><ul>{points}</ul></div>',
        unsafe_allow_html=True,
    )


def render_auth_header(mode, status_ok=True, status_text=None):
    sub = "Freight operations platform · every sign-in is protected"
    heading = {"Register": "Create an account",
               "Forgot Password": "Reset your password"}.get(mode)
    if status_text is None:
        status_text = ("Ready: secure sign-in online (you can sign in)" if status_ok
                       else "Starting up: database (you can sign in shortly)")
    icon = '<span class="ok"></span>' if status_ok else '<span class="ring"></span>'
    head = f'<div class="fq-auth-heading">{esc(heading)}</div>' if heading else ""
    st.markdown(
        f'<div><div class="fq-auth-title">{esc(BRAND)}</div>'
        f'<div class="fq-auth-sub">{esc(sub)}</div>'
        f'<div class="fq-status">{icon}<span>{esc(status_text)}</span></div>{head}</div>',
        unsafe_allow_html=True,
    )


def render_role_chips(selected=None):
    """Workspace chips (same keys as before: login_role_*)."""
    def pick(label):
        st.session_state["selected_login_role"] = label

    st.markdown('<div class="fq-demo-label">Workspace (click to select)</div>', unsafe_allow_html=True)
    with st.container(horizontal=True, gap="small", key="fq_role_chips"):
        for label, key in ROLE_BUTTONS:
            st.button(label, key=key, on_click=pick, args=(label,),
                      type="primary" if selected == label else "secondary")


# ============================================================ DATA LAYER ====

def _qi(name):
    return '"' + str(name).replace('"', '""') + '"'


def _ro_connect(path):
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.execute("PRAGMA query_only = ON")
    return conn


def discover_databases(primary=None):
    # Use an explicitly supplied database when provided.
    if primary:
        p = Path(primary)
        return [p] if p.is_file() and p.name != "security_auth.db" else []

    # Use only the main project database by default.
    main_db = BASE_DIR / "freightquote.db"

    if main_db.is_file():
        return [main_db]

    # Do not automatically load backups if the main DB is missing.
    return []


def _norm_role(role):
    return str(role or "").strip().casefold()


@st.cache_data(ttl=20, show_spinner=False)
def _catalog(db_paths):
    """[{db, table, columns:[(name,type)], rows}] for every readable table."""
    out = []
    for db in db_paths:
        try:
            with _ro_connect(db) as conn:
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
                for t in tables:
                    if t.lower() in SENSITIVE_TABLES:
                        continue
                    cols = [(r[1], (r[2] or "").upper()) for r in conn.execute(f"PRAGMA table_info({_qi(t)})")]
                    try:
                        n = conn.execute(f"SELECT COUNT(*) FROM {_qi(t)}").fetchone()[0]
                    except sqlite3.Error:
                        n = None
                    out.append({"db": str(db), "table": t, "columns": cols, "rows": n})
        except sqlite3.Error:
            continue
    return out


def accessible_tables(user, db_paths):
    """Tables this user may read, with safe columns and an owner filter for Customers."""
    role = _norm_role(user.get("role"))
    result = []
    for entry in _catalog(tuple(str(p) for p in db_paths)):
        t = entry["table"].lower()
        if t == "users" and role not in ("admin", "auditor"):
            continue
        cols = [c for c, _ in entry["columns"] if not SENSITIVE_COL_RE.search(c)]
        if not cols:
            continue
        where, params = "", []
        if role == "customer":
            lower = {c.lower(): c for c, _ in entry["columns"]}
            idc = next((lower[c] for c in OWNER_ID_COLS if c in lower), None)
            emc = next((lower[c] for c in OWNER_EMAIL_COLS if c in lower), None)
            if t == "users":
                continue
            if idc and user.get("id") is not None:
                where, params = f"{_qi(idc)} = ?", [user["id"]]
            elif emc and user.get("email"):
                where, params = f"lower({_qi(emc)}) = lower(?)", [user["email"]]
            elif lower.get("username") and user.get("username"):
                where, params = f"lower({_qi(lower['username'])}) = lower(?)", [user["username"]]
            else:
                continue  # no way to scope rows to this customer
        types = {c: ty for c, ty in entry["columns"]}
        item = {**entry, "safe_cols": cols, "types": types, "where": where, "params": params}
        if where:  # report only this user's row count
            try:
                with _ro_connect(entry["db"]) as conn:
                    item["rows"] = conn.execute(
                        f"SELECT COUNT(*) FROM {_qi(entry['table'])} WHERE {where}", params).fetchone()[0]
            except sqlite3.Error:
                item["rows"] = None
        result.append(item)
    return result


def _status_col(tbl):
    lower = {c.lower(): c for c in tbl["safe_cols"]}
    return next((lower[c] for c in STATUS_COLS if c in lower), None)


def _date_col(tbl):
    for c in tbl["safe_cols"]:
        if DATE_COL_RE.search(c):
            return c
    return None


def _numeric_cols(tbl):
    return [c for c in tbl["safe_cols"]
            if any(k in tbl["types"].get(c, "") for k in ("INT", "REAL", "NUM", "FLOA", "DOUB", "DEC"))
            and not c.lower().endswith("id")]


def _where(tbl, extra=None, extra_params=()):
    parts, params = [], list(tbl["params"])
    if tbl["where"]:
        parts.append(tbl["where"])
    if extra:
        parts.append(extra)
        params.extend(extra_params)
    return (" WHERE " + " AND ".join(parts)) if parts else "", params


def watch(tbl):
    """Status summary for one table -> dict(name, level, text)."""
    name = re.sub(r"s$", "", tbl["table"].lower()) + "_watch"
    sc = _status_col(tbl)
    w, params = _where(tbl)
    try:
        with _ro_connect(tbl["db"]) as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM {_qi(tbl['table'])}{w}", params).fetchone()[0]
            if not sc:
                return {"name": name, "level": "info" if total else "none",
                        "badge": "Live" if total else "Empty",
                        "text": f"{total:,} {tbl['table'].replace('_', ' ')} rows available"}
            groups = conn.execute(
                f"SELECT {_qi(sc)}, COUNT(*) FROM {_qi(tbl['table'])}{w} GROUP BY 1 ORDER BY 2 DESC", params
            ).fetchall()
    except sqlite3.Error:
        return {"name": name, "level": "none", "badge": "n/a", "text": "Could not read this table"}
    flagged = [(str(s), n) for s, n in groups if s is not None and ATTENTION_RE.search(str(s))]
    attention = sum(n for _, n in flagged)
    if total == 0:
        level, txt = "none", "No rows yet"
    elif attention == 0:
        level, txt = "low", f"0 of {total:,} need attention"
    else:
        share = attention / total
        level = "high" if share >= 0.3 else "medium"
        detail = ", ".join(f"{s} {n}" for s, n in flagged[:3])
        txt = f"{attention:,} of {total:,} need attention ({detail})"
    return {"name": name, "level": level, "badge": None, "text": txt}


def table_rows(tbl, limit=25, order_col=None, extra=None, extra_params=()):
    cols = tbl["safe_cols"]
    w, params = _where(tbl, extra, extra_params)
    order = f" ORDER BY {_qi(order_col)} DESC" if order_col else " ORDER BY rowid DESC"
    sql = f"SELECT {', '.join(_qi(c) for c in cols)} FROM {_qi(tbl['table'])}{w}{order} LIMIT {int(limit)}"
    with _ro_connect(tbl["db"]) as conn:
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            sql = sql.replace(" ORDER BY rowid DESC", "")
            rows = conn.execute(sql, params).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM {_qi(tbl['table'])}{w}", params).fetchone()[0]
    return cols, rows, total, sql, params


# =============================================================== COPILOT ====

def _tokens(text):
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    out = set(words)
    out |= {w[:-1] for w in words if w.endswith("s") and len(w) > 3}
    out |= {w[:-2] for w in words if w.endswith("es") and len(w) > 4}
    return out


def _parts(name):
    p = set(re.findall(r"[a-z0-9]+", name.lower().replace("_", " ")))
    return p | {w[:-1] for w in p if w.endswith("s") and len(w) > 3}


def plan(question, tables):
    toks = _tokens(question)
    scored = []
    for t in tables:
        s = 3 * len(_parts(t["table"]) & toks)
        s += sum(1 for c in t["safe_cols"] if _parts(c) & toks)
        scored.append((s, t["rows"] or 0, t))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [t for s, _, t in scored if s > 0], toks


def answer(question, user, db_paths):
    t0 = time.perf_counter()
    tables = accessible_tables(user, db_paths)
    trace, sources = [], []
    if not tables:
        return {"q": question, "trace": ["No readable data tables for your workspace yet."],
                "sources": [], "sql": None, "watch": [], "headline": None, "columns": [], "rows": [],
                "note": "Nothing to answer from yet. Data will appear here as soon as quotes or other "
                        "records are saved.", "elapsed": time.perf_counter() - t0}

    picked, toks = plan(question, tables)
    watch_set = (picked or tables)[:5]
    trace.append("Planner selected: " + ", ".join(
        re.sub(r"s$", "", t["table"].lower()) + "_watch" for t in watch_set))
    trace.append("Running the selected agents and the read-only query engine...")
    watches = [watch(t) for t in watch_set]
    trace.append(f"Agents ready in {time.perf_counter() - t0:.1f}s")

    if not picked:
        rows = [(t["table"], t["rows"] if t["rows"] is not None else "?", len(t["safe_cols"]),
                 Path(t["db"]).name) for t in tables]
        rows.sort(key=lambda r: (r[1] if isinstance(r[1], int) else -1), reverse=True)
        trace.append("No table matched the question; showing what the Copilot can read")
        return {"q": question, "trace": trace, "watch": watches,
                "sources": [f"{t['table']} · {Path(t['db']).name}" for t in tables[:6]],
                "sql": "SELECT name FROM sqlite_master WHERE type = 'table'",
                "headline": f"<b>{len(tables)}</b> readable tables; mention one of them (or a column) to query it.",
                "columns": ["table", "rows", "columns", "database"], "rows": rows[:10],
                "note": None, "elapsed": time.perf_counter() - t0}

    main = picked[0]
    trace.append("Exact answer from your live data (read-only query)")
    lower = {c.lower(): c for c in main["safe_cols"]}
    sc = _status_col(main)
    extra, extra_params, filter_txt = None, [], ""

    # status filter, e.g. "pending quotes"
    if sc:
        try:
            w, params = _where(main)
            with _ro_connect(main["db"]) as conn:
                values = [r[0] for r in conn.execute(
                    f"SELECT DISTINCT {_qi(sc)} FROM {_qi(main['table'])}{w} LIMIT 200", params) if r[0] is not None]
            for v in values:
                vt = _tokens(str(v))
                if vt and vt <= toks or str(v).lower() in question.lower():
                    extra, extra_params, filter_txt = f"lower({_qi(sc)}) = lower(?)", [v], f" with {sc} = {v}"
                    break
        except sqlite3.Error:
            pass

    # group-by: "how many ... by/per <column>"
    group_col = None
    m = re.search(r"\b(?:by|per)\s+([a-z0-9_ ]+)", question.lower())
    counting = re.search(r"\b(how many|count|number of|per|breakdown|split|group)\b", question.lower())
    if m and counting:
        cand = _tokens(m.group(1))
        group_col = next((c for c in main["safe_cols"] if _parts(c) & cand), None)

    order_col, order_txt = None, ""
    nums = _numeric_cols(main)
    hit = next((c for c in nums if _parts(c) & toks), None)
    if hit:
        order_col, order_txt = hit, f", sorted by {hit.replace('_', ' ')}"
    elif toks & {"latest", "recent", "newest", "last", "new"} and _date_col(main):
        order_col = _date_col(main)
        order_txt = f", newest first by {order_col.replace('_', ' ')}"

    try:
        if group_col:
            w, params = _where(main, extra, extra_params)
            sql = (f"SELECT {_qi(group_col)}, COUNT(*) AS count FROM {_qi(main['table'])}{w} "
                   f"GROUP BY 1 ORDER BY 2 DESC LIMIT 50")
            with _ro_connect(main["db"]) as conn:
                rows = conn.execute(sql, params).fetchall()
            cols, total = [group_col, "count"], sum(r[1] for r in rows)
            headline = (f"<b>{total:,}</b> {esc(main['table'].replace('_', ' '))} rows{esc(filter_txt)}, "
                        f"grouped by {esc(group_col.replace('_', ' '))}.")
        else:
            cols, rows, total, sql, params = table_rows(main, limit=10, order_col=order_col,
                                                        extra=extra, extra_params=extra_params)
            headline = (f"<b>{total:,}</b> {esc(main['table'].replace('_', ' '))} entries{esc(filter_txt)}; "
                        f"showing {len(rows)}{esc(order_txt)}.")
    except sqlite3.Error as exc:
        return {"q": question, "trace": trace + [f"Query failed: {type(exc).__name__}"], "watch": watches,
                "sources": [], "sql": None, "headline": None, "columns": [], "rows": [],
                "note": "The query could not run against this table.", "elapsed": time.perf_counter() - t0}

    shown_sql = sql
    for p in params:
        shown_sql = shown_sql.replace("?", repr(p) if isinstance(p, str) else str(p), 1)
    for i, t in enumerate(picked[:3], 1):
        sources.append(f"[{i}] {t['table']} · {Path(t['db']).name} · {t['rows'] or 0:,} rows "
                       f"· match #{i}")
    elapsed = time.perf_counter() - t0
    return {"q": question, "trace": trace, "watch": watches, "sources": sources, "sql": shown_sql,
            "headline": headline, "columns": cols, "rows": rows, "note": None, "elapsed": elapsed}


def render_answer(res):
    tr = "".join(f"<div>{esc(line)}</div>" for line in res["trace"])
    if res.get("sources"):
        src = "".join(f'<div class="src">{esc(s)}</div>' for s in res["sources"])
        tr += f'<details open><summary>Sources ({len(res["sources"])})</summary>{src}</details>'
    if res.get("sql"):
        tr += f'<details><summary>Show the exact query</summary><pre>{esc(res["sql"])}</pre></details>'
    tr += f'<div>done in {res["elapsed"]:.1f}s</div>'
    parts = [f'<div class="fq-answer"><div class="fq-trace">{tr}</div>']
    if res.get("watch"):
        rows = "".join(
            f'<div class="row"><span class="name">{esc(w["name"])}</span>'
            f'<span>{badge(w["level"], w.get("badge"))}</span><span class="txt">{esc(w["text"])}</span></div>'
            for w in res["watch"])
        parts.append(f'<div class="fq-watch">{rows}</div>')
    if res.get("note"):
        parts.append(f'<div class="note">{esc(res["note"])}</div>')
    if res.get("headline"):
        parts.append(f'<div class="fq-headline">{res["headline"]}</div>')
    if res.get("columns"):
        parts.append(html_table(res["columns"], res["rows"]))
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def suggestions(user, db_paths):
    tables = accessible_tables(user, db_paths)
    out = []
    for t in sorted(tables, key=lambda t: t["rows"] or 0, reverse=True)[:4]:
        label = t["table"].replace("_", " ")
        sc = _status_col(t)
        out.append(f"How many {label} by {sc.replace('_', ' ')}?" if sc else f"Show the latest {label}")
    return out or ["What data can you read?"]


def page_copilot(user, db_paths):
    ss = st.session_state
    hist = ss.setdefault("fq_copilot_history", [])
    pending = ss.pop("fq_pending_q", None)
    typed = st.chat_input("Ask about your quotes, shipments, carriers or anything in your data...")
    question = (typed or pending or "").strip()
    if question:
        with st.spinner("Agents are running..."):
            res = answer(question[:500], user, db_paths)
        hist.append({"role": "user", "text": question[:500]})
        hist.append({"role": "assistant", "result": res})
        del hist[:-30]

    with st.container(key="fq_chat"):
        if not hist:
            st.markdown(
                '<div class="fq-welcome"><div class="h">Ask the Copilot</div>'
                '<p>Questions run read-only queries over your live FreightQuote data. '
                'Every answer shows its sources and the exact query.</p></div>',
                unsafe_allow_html=True)

            def ask(q):
                st.session_state["fq_pending_q"] = q

            with st.container(horizontal=True, gap="small", key="fq_suggest"):
                for i, q in enumerate(suggestions(user, db_paths)):
                    st.button(q, key=f"fq_sugg_{i}", on_click=ask, args=(q,))
        for item in hist:
            if item["role"] == "user":
                st.markdown(f'<div class="fq-msg-user"><span>{esc(item["text"])}</span></div>',
                            unsafe_allow_html=True)
            else:
                render_answer(item["result"])
        if hist:
            if st.button("Clear conversation", key="fq_clear_chat", type="tertiary", icon=":material/delete_sweep:"):
                ss["fq_copilot_history"] = []
                st.rerun()


# ============================================================ OTHER PAGES ====

def page_tables(pid, user, db_paths):
    tables = accessible_tables(user, db_paths)


    if pid == "reports":
        matches = tables
    else:
        keys = PAGE_KEYWORDS.get(pid, [])

        matches = [
            t for t in tables
            if any(k in t["table"].lower() for k in keys)
        ]

        # Route AI: also match tables with route-related columns.
        if pid == "route":
            for t in tables:
                if t in matches:
                    continue

                column_names = [
                    str(col[0]).lower()
                    for col in t.get("columns", [])
                ]

                if any(
                    key in column_name
                    for column_name in column_names
                    for key in keys
                ):
                    matches.append(t)



    if not matches:
        st.markdown(
            f'<div class="fq-empty"><div class="h">No {esc(PAGE_TITLES.get(pid, pid))} data yet</div>'
            f'<p>This module fills in automatically once its agent or a data feed writes '
            f'{esc(", ".join(PAGE_KEYWORDS.get(pid, ["records"])[:3]))} records to the database. '
            f'Nothing is simulated here.</p></div>',
            unsafe_allow_html=True
        )
        return
    if pid == "reports":
        total_rows = sum(t["rows"] or 0 for t in matches)
        st.markdown(
            f'<div class="fq-kpis"><div class="fq-kpi"><div class="k">Readable tables</div><div class="v">{len(matches)}</div></div>'
            f'<div class="fq-kpi"><div class="k">Total rows</div><div class="v">{total_rows:,}</div></div>'
            f'<div class="fq-kpi"><div class="k">Databases</div><div class="v">{len({t["db"] for t in matches})}</div></div></div>',
            unsafe_allow_html=True)
    for t in matches[:8]:
        w = watch(t)
        try:
            cols, rows, total, _, _ = table_rows(t, limit=25, order_col=_date_col(t))
        except sqlite3.Error:
            st.warning(f"Could not read {t['table']}.")
            continue
        st.markdown(
            f'<div class="fq-section-title"><div class="h">{esc(t["table"].replace("_", " ").title())}</div>'
            f'<span>{badge(w["level"], w.get("badge"))}&nbsp; {esc(w["text"])} · showing {len(rows)} of {total:,}</span></div>'
            + html_table(cols, rows) + '<div style="height:18px"></div>', unsafe_allow_html=True)


def page_admin(user, db_path):
    try:
        with _ro_connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
            safe = [c for c in cols if not SENSITIVE_COL_RE.search(c)]
            users = conn.execute(f"SELECT {', '.join(_qi(c) for c in safe)} FROM users ORDER BY id").fetchall()
            roles = conn.execute("SELECT role, COUNT(*) FROM users GROUP BY role ORDER BY 2 DESC").fetchall()
            try:
                locked = conn.execute("SELECT COUNT(*) FROM login_attempts WHERE locked_until > ?",
                                      (time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),)).fetchone()[0]
            except sqlite3.Error:
                locked = 0
    except sqlite3.Error as exc:
        st.error(f"Could not read users: {type(exc).__name__}")
        return
    kpis = "".join(f'<div class="fq-kpi"><div class="k">{esc(r[0])}</div><div class="v">{r[1]}</div></div>' for r in roles)
    st.markdown(
        f'<div class="fq-kpis"><div class="fq-kpi"><div class="k">Users</div><div class="v">{len(users)}</div></div>'
        f'<div class="fq-kpi"><div class="k">Locked accounts</div><div class="v">{locked}</div></div>{kpis}</div>',
        unsafe_allow_html=True)
    st.markdown('<div class="fq-section-title"><div class="h">Users</div><span>Read-only · password and '
                'security-answer hashes are never shown</span></div>'
                + html_table(safe, [tuple(u) for u in users]), unsafe_allow_html=True)


def page_profile(user, db_path):
    created = None
    try:
        with _ro_connect(db_path) as conn:
            row = conn.execute("SELECT created_at FROM users WHERE id = ?", (user.get("id"),)).fetchone()
            created = row[0][:10] if row and row[0] else None
    except sqlite3.Error:
        pass
    initials = "".join(w[:1] for w in str(user.get("username", "U")).split()[:2]).upper() or "U"
    st.markdown(
        f'<div class="fq-card" style="display:flex;gap:16px;align-items:center;max-width:620px">'
        f'<div class="fq-logo" style="width:52px;height:52px;flex-basis:52px;border-radius:14px;color:#fff;'
        f'font-weight:700;font-size:18px">{esc(initials)}</div><div>'
        f'<div class="h">{esc(user.get("username"))}</div><p>{esc(user.get("email"))}</p>'
        f'<p style="margin-top:6px">{badge("info", user.get("role"))}'
        f'{"&nbsp; <span style=font-size:12px;color:#6b7280>Member since " + esc(created) + "</span>" if created else ""}'
        f'</p></div></div>', unsafe_allow_html=True)
    st.caption("To change your password, sign out and use Forgot password on the sign-in page.")


def page_command(user):
    try:
        from dashboard_views import render_dashboard
    except Exception as exc:  # keep the shell usable even if the module breaks
        st.error(f"Dashboard module could not be loaded: {type(exc).__name__}: {exc}")
        return
    render_dashboard(user)


def page_customer_quotes(user):
    try:
        from quote_ui import render_customer_quotes
    except Exception as exc:
        st.error(f"Quote module could not be loaded: {type(exc).__name__}: {exc}")
        return
    view = st.session_state.get("customer_view", "request")
    c1, c2, _ = st.columns([1, 1, 2])
    with c1:
        if st.button("Request a Freight Quote", key="fq_cq_request", width="stretch",
                     type="primary" if view == "request" else "secondary"):
            st.session_state["customer_view"] = "request"
            st.rerun()
    with c2:
        if st.button("My Quotes / Shipment Status", key="fq_cq_list", width="stretch",
                     type="primary" if view == "quotes" else "secondary"):
            st.session_state["customer_view"] = "quotes"
            st.rerun()
    try:
        render_customer_quotes(user, view_mode=view)
    except TypeError:
        render_customer_quotes(user)


# ================================================================= SHELL ====

def allowed(pid, role):
    return role in PAGE_ROLES.get(pid, ALL_ROLES)


def _extra_pages():
    folder = BASE_DIR / "pages"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.py") if not p.name.startswith("_"))


def _on_search():
    q = (st.session_state.get("fq_search") or "").strip()
    if q:
        st.session_state["fq_pending_q"] = q
        st.session_state["fq_page"] = "copilot"
    st.session_state["fq_search"] = ""


def _go(pid):
    st.session_state["fq_page"] = pid


def render_sidebar(user, on_sign_out):
    role = _norm_role(user.get("role"))
    active = st.session_state.get("fq_page", "copilot")
    with st.sidebar:
        st.markdown(
            f'<div class="fq-brand"><div class="fq-logo">{LOGO_SVG}</div><div style="min-width:0">'
            f'<div class="name">{esc(BRAND)}</div>'
            f'<div class="who">{esc(user.get("role"))} · {esc(user.get("email"))}</div></div></div>',
            unsafe_allow_html=True)
        st.text_input("Search or ask", key="fq_search", placeholder="Search or ask...",
                      label_visibility="collapsed", on_change=_on_search)
        st.html("""<script>
          (function(){const d=window.parent.document; if(d.__fqCtrlK) return; d.__fqCtrlK=true;
            d.addEventListener('keydown',function(e){ if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){
              const i=d.querySelector('.st-key-fq_search input'); if(i){e.preventDefault(); i.focus();}}});})();
          </script>""", unsafe_allow_javascript=True)
        with st.container(key="fq_nav"):
            section = None
            for sec, pid, label, icon in NAV:
                if not allowed(pid, role):
                    continue
                if sec != section:
                    section = sec
                    st.markdown(f'<div class="fq-nav-label">{esc(sec)}</div>', unsafe_allow_html=True)
                st.button(label, key=f"nav_{pid}", icon=f":material/{icon}:", width="stretch",
                          on_click=_go, args=(pid,))
            for page in _extra_pages():
                try:
                    st.page_link(f"pages/{page.name}", label=page.stem.split("_", 1)[-1].replace("_", " ").title(),
                                 icon=":material/description:")
                except Exception:
                    pass
            st.button("Command Center", key="nav_command", icon=":material/space_dashboard:",
                      width="stretch", on_click=_go, args=("command",))
        st.button("Sign out", key="fq_signout", on_click=on_sign_out)


def _status_pills(user, db_paths):
    tables = accessible_tables(user, db_paths)
    rows = sum(t["rows"] or 0 for t in tables)
    flagged = 0
    for t in tables[:6]:
        if _status_col(t):
            w = watch(t)
            flagged += 1 if w["level"] in ("high", "medium") else 0
    turns = len(st.session_state.get("fq_copilot_history", [])) // 2
    dot = "amber" if flagged else ""
    return (f'<span class="fq-pill"><span class="dot {dot}"></span>live · tables {len(tables)} · rows {rows:,}'
            f' · flagged {flagged} · cycle {turns}</span>'
            f'<span class="fq-pill"><span class="dot"></span>SQLite read-only · Copilot ready</span>')


def render_topbar(pid, user, db_paths):
    st.markdown(
        f'<div class="fq-topbar"><div style="min-width:0"><div class="title">{esc(PAGE_TITLES.get(pid, pid))}</div>'
        f'<div class="subtitle">{esc(PAGE_SUBTITLES.get(pid, ""))}</div></div>'
        f'<div class="fq-pills">{_status_pills(user, db_paths)}</div></div>',
        unsafe_allow_html=True)


def render_app(user, db_path, on_sign_out):
    ss = st.session_state
    role = _norm_role(user.get("role"))
    ss.setdefault("fq_page", "copilot")
    if ss["fq_page"] != "command" and (ss["fq_page"] not in PAGE_TITLES or not allowed(ss["fq_page"], role)):
        ss["fq_page"] = "copilot"
    # sidebar callbacks have already run, so this is the page to draw
    pid = ss["fq_page"]
    inject_app_css(pid)
    db_paths = discover_databases(db_path)

    render_sidebar(user, on_sign_out)
    render_topbar(pid, user, db_paths)

    with st.container(key="fq_toolbar"):
        if pid == "copilot":
            st.selectbox("Answer language", ["English"], key="fq_lang", label_visibility="collapsed",
                         help="Answers are generated in English.")
        else:
            st.markdown('<div style="height:2px"></div>', unsafe_allow_html=True)

    if pid == "copilot":
        page_copilot(user, db_paths)
    elif pid == "command":
        page_command(user)
    elif pid == "quotes" and role == "customer":
        page_customer_quotes(user)
    elif pid == "admin":
        page_admin(user, db_path)
    elif pid == "profile":
        page_profile(user, db_path)
    else:
        page_tables(pid, user, db_paths)
