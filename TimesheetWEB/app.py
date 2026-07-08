"""
Danfoss Time Reporting System — Flask Web Application
======================================================
Exact feature-for-feature rewrite of logo_page_updated.py in Flask.

Run:
    pip install flask requests openpyxl
    python app.py

Then open: http://localhost:5000
"""

import os
import re
import sys
import json
import base64
import hashlib
import secrets
import zipfile
import calendar
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from functools import wraps

import requests
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, flash
)

# ── App setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)   # session encryption key


# ── File paths ────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
TIME_NAME_LIST = BASE_DIR / "File" / "time name list.xlsx"
USER_STORE     = BASE_DIR / "File" / "registered_users.json"
USER_STORE.parent.mkdir(parents=True, exist_ok=True)

import shutil, base64 as _b64

# Search for Logo.png in several possible locations
_logo_candidates = [
    BASE_DIR / "Pictures" / "Logo.png",
    BASE_DIR / "static" / "images" / "Logo.png",
    BASE_DIR / "Logo.png",
    BASE_DIR / "static" / "Logo.png",
]
LOGO_SOURCE = next((p for p in _logo_candidates if p.exists()), None)

# Always copy logo into static/images/ so Flask can serve it via HTTP
STATIC_IMG_DIR = BASE_DIR / "static" / "images"
STATIC_IMG_DIR.mkdir(parents=True, exist_ok=True)
STATIC_LOGO = STATIC_IMG_DIR / "Logo.png"

if LOGO_SOURCE and LOGO_SOURCE != STATIC_LOGO:
    shutil.copy2(LOGO_SOURCE, STATIC_LOGO)

# Build the logo URL — use web path if file exists, else base64 inline data URI
if STATIC_LOGO.exists():
    LOGO_URL = "/static/images/Logo.png"
else:
    # Encode as base64 inline so it always works regardless of static serving
    LOGO_URL = None
    for candidate in _logo_candidates:
        if candidate.exists():
            try:
                _img_b64 = _b64.b64encode(candidate.read_bytes()).decode()
                LOGO_URL  = f"data:image/png;base64,{_img_b64}"
                break
            except Exception:
                pass


# ── Azure AD / SharePoint credentials ────────────────────────────────────────
TENANT_ID     = "097464b8-069c-453e-9254-c17ec707310d"
CLIENT_ID     = "ecdd19bb-3ef4-4099-98b9-78c76b29f01d"
CLIENT_SECRET = "DgF8Q~Y1Cy2QFbqcLof19eDB8B7qpay3.I.UydeL"

SP_SITE_HOST  = "danfoss.sharepoint.com"
SP_SITE_PATH  = "/sites/DataManagementandIntegrationTimecardEntries"
SP_LIST_NAME  = "Time Sheet"
SP_SITE_ID    = ""   # leave blank to auto-resolve at runtime

_TOKEN_URL    = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

# SSO — redirect must be registered in Azure App reg → Authentication
SSO_REDIRECT_URI = "http://localhost:5000/auth/callback"
SSO_SCOPES       = "openid profile email User.Read"

# Dummy consultants (shown in dropdown when no Excel file present)
DUMMY_CONSULTANTS = [
    "Pradeep Kumar",
    "Integration Second Level Support",
]


# ╔══════════════════════════════════════════════════════════════╗
# ║  SharePoint / Graph helpers                                  ║
# ╚══════════════════════════════════════════════════════════════╝

def get_graph_token() -> str:
    resp = requests.post(_TOKEN_URL, data={
        "grant_type":    "client_credentials",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope":         "https://graph.microsoft.com/.default",
    }, timeout=30)
    resp.raise_for_status()
    token = resp.json().get("access_token", "")
    if not token:
        raise RuntimeError(f"No access_token: {resp.json()}")
    return token


def _graph_hdrs(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def get_site_id(token: str) -> str:
    if SP_SITE_ID.strip():
        return SP_SITE_ID.strip()
    url  = f"https://graph.microsoft.com/v1.0/sites/{SP_SITE_HOST}:{SP_SITE_PATH}?$select=id"
    resp = requests.get(url, headers=_graph_hdrs(token), timeout=30)
    resp.raise_for_status()
    site_id = resp.json().get("id", "")
    if not site_id:
        raise RuntimeError(f"Could not resolve site id: {resp.json()}")
    return site_id


def get_list_id(token: str, site_id: str) -> str:
    url  = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists"
    resp = requests.get(url, headers=_graph_hdrs(token), timeout=30)
    resp.raise_for_status()
    for lst in resp.json().get("value", []):
        if lst.get("displayName", "").strip().lower() == SP_LIST_NAME.strip().lower():
            return lst["id"]
    raise RuntimeError(f"List '{SP_LIST_NAME}' not found.")


def _graph_post_item(token: str, site_id: str, list_id: str, fields: dict):
    url  = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/items"
    resp = requests.post(url, headers=_graph_hdrs(token),
                         json={"fields": fields}, timeout=30)
    if not resp.ok:
        try:
            err = resp.json()
        except Exception:
            err = resp.text
        raise RuntimeError(f"HTTP {resp.status_code} — {err}")
    return resp


def submit_timesheet_to_sp_list(consultant, consultant_type, month, year,
                                 owner, projects_data):
    """
    projects_data: list of {"name": str, "hours": {date_str: hours_float}, "total": float}
    """
    month_label  = f"{month} {year}"
    token        = get_graph_token()
    site_id      = get_site_id(token)
    list_id      = get_list_id(token, site_id)

    for proj in projects_data:
        fields = {
            "Title":                 consultant,
            "Login_x0020_User":      consultant,
            "Project_x0020_Type":    consultant_type,
            "Month":                 month_label,
            "Project_x0020_Hours":   proj["total"],
            "Project_Name":          proj["name"],
            "Project_x0020_Manager": owner,
        }
        _graph_post_item(token, site_id, list_id, fields)


# ╔══════════════════════════════════════════════════════════════╗
# ║  SSO — Microsoft / Azure AD                                  ║
# ╚══════════════════════════════════════════════════════════════╝

def _pkce_pair():
    verifier  = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


@app.route("/auth/login")
def auth_login():
    """Redirect user to Microsoft login page."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(12)

    session["pkce_verifier"] = verifier
    session["oauth_state"]   = state

    auth_url = (
        f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/authorize?"
        + urllib.parse.urlencode({
            "client_id":             CLIENT_ID,
            "response_type":         "code",
            "redirect_uri":          SSO_REDIRECT_URI,
            "response_mode":         "query",
            "scope":                 SSO_SCOPES,
            "state":                 state,
            "code_challenge":        challenge,
            "code_challenge_method": "S256",
            "prompt":                "select_account",
        })
    )
    return redirect(auth_url)


@app.route("/auth/callback")
def auth_callback():
    """Handle OAuth2 callback, exchange code for token, fetch user profile."""
    error = request.args.get("error")
    if error:
        flash(f"Sign-in failed: {request.args.get('error_description', error)}", "danger")
        return redirect(url_for("login"))

    code  = request.args.get("code")
    state = request.args.get("state")

    if state != session.get("oauth_state"):
        flash("Invalid state parameter — possible CSRF. Please try again.", "danger")
        return redirect(url_for("login"))

    # Exchange code for tokens
    token_resp = requests.post(_TOKEN_URL, data={
        "client_id":     CLIENT_ID,
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  SSO_REDIRECT_URI,
        "code_verifier": session.pop("pkce_verifier", ""),
        "scope":         SSO_SCOPES,
    }, timeout=30)

    token_data = token_resp.json()
    if "access_token" not in token_data:
        flash(f"Token exchange failed: {token_data}", "danger")
        return redirect(url_for("login"))

    access_token = token_data["access_token"]

    # Fetch user profile
    me_resp = requests.get(
        "https://graph.microsoft.com/v1.0/me?$select=displayName,mail,userPrincipalName",
        headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    me_resp.raise_for_status()
    me = me_resp.json()

    session["sso_signed_in"]    = True
    session["sso_display_name"] = me.get("displayName", "")
    session["sso_email"]        = me.get("mail") or me.get("userPrincipalName", "")
    session["sso_token"]        = access_token
    session["logged_in"]        = True
    session["username"]         = session["sso_display_name"]

    return redirect(url_for("dashboard"))


# ╔══════════════════════════════════════════════════════════════╗
# ║  User store (local accounts)                                 ║
# ╚══════════════════════════════════════════════════════════════╝

def load_users() -> dict:
    if not USER_STORE.exists():
        return {}
    try:
        return json.loads(USER_STORE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_users(users: dict):
    USER_STORE.write_text(json.dumps(users, indent=4), encoding="utf-8")


def hash_password(password: str, salt: str = None):
    if salt is None:
        salt = secrets.token_hex(16)
    pw_hash = hashlib.sha256((salt + password).encode()).hexdigest()
    return salt, pw_hash


# ╔══════════════════════════════════════════════════════════════╗
# ║  Excel autofill data                                         ║
# ╚══════════════════════════════════════════════════════════════╝

def load_excel_autofill_data():
    project_values, owner_values, owner_map = [], [], {}
    if not TIME_NAME_LIST.exists():
        return project_values, owner_values, owner_map
    try:
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(TIME_NAME_LIST) as wb:
            shared = []
            try:
                root_el = ET.fromstring(wb.read("xl/sharedStrings.xml"))
                for si in root_el.findall("a:si", ns):
                    shared.append("".join(t.text or "" for t in si.findall(".//a:t", ns)))
            except KeyError:
                pass
            sheet = ET.fromstring(wb.read("xl/worksheets/sheet1.xml"))
            rows  = {}
            for cell in sheet.findall(".//a:c", ns):
                ref = cell.get("r", "")
                m   = re.match(r"([A-Z]+)([0-9]+)", ref)
                if not m:
                    continue
                col, row = m.group(1), int(m.group(2))
                if col not in ("A", "C"):
                    continue
                vn = cell.find("a:v", ns)
                if vn is None:
                    continue
                val = vn.text or ""
                if cell.get("t") == "s":
                    val = shared[int(val)]
                val = val.strip()
                if val:
                    rows.setdefault(row, {})[col] = val
            for rn in sorted(rows):
                proj  = rows[rn].get("A", "")
                owner = rows[rn].get("C", "")
                if proj and proj not in project_values:
                    project_values.append(proj)
                if owner and owner not in owner_values:
                    owner_values.append(owner)
                if proj and owner:
                    owner_map[proj] = owner
    except Exception:
        pass
    return project_values, owner_values, owner_map


project_dropdown_values, owner_dropdown_values, consultant_owner_map = load_excel_autofill_data()


# ╔══════════════════════════════════════════════════════════════╗
# ║  Auth guard                                                  ║
# ╚══════════════════════════════════════════════════════════════╝

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ╔══════════════════════════════════════════════════════════════╗
# ║  Routes                                                      ║
# ╚══════════════════════════════════════════════════════════════╝

@app.route("/")
def index():
    return redirect(url_for("register"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username         = request.form.get("username", "").strip()
        password         = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        users            = load_users()

        if not username:
            flash("Please enter a username.", "warning")
        elif not password:
            flash("Please enter a password.", "warning")
        elif len(password) < 4:
            flash("Password must be at least 4 characters.", "warning")
        elif password != confirm_password:
            flash("Passwords do not match.", "danger")
        elif username in users:
            flash("Username already registered.", "info")
        else:
            salt, pw_hash = hash_password(password)
            users[username] = {"salt": salt, "password_hash": pw_hash}
            save_users(users)
            flash("Account created successfully. Please log in.", "success")
            return redirect(url_for("login"))

    return render_template("register.html", logo_url=LOGO_URL)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        users    = load_users()

        valid = False
        if username == "admin" and password == "1234":
            valid = True
        elif username in users:
            salt, stored_hash = users[username]["salt"], users[username]["password_hash"]
            _, entered_hash   = hash_password(password, salt)
            valid = entered_hash == stored_hash

        if valid:
            session["logged_in"] = True
            session["username"]  = username
            session["sso_signed_in"] = False
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.", "danger")

    return render_template("login.html", logo_url=LOGO_URL)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    now = datetime.now()
    return render_template(
        "dashboard.html",
        username          = session.get("username", ""),
        sso_signed_in     = session.get("sso_signed_in", False),
        sso_email         = session.get("sso_email", ""),
        current_month     = now.strftime("%B"),
        current_year      = str(now.year),
        today             = now.strftime("%d %B %Y"),
        months            = ["January","February","March","April","May","June",
                             "July","August","September","October","November","December"],
        years             = [str(y) for y in range(2024, 2031)],
        project_suggestions = project_dropdown_values,
        owner_suggestions   = owner_dropdown_values,
        dummy_consultants   = DUMMY_CONSULTANTS,
        consultant_owner_map = consultant_owner_map,
        logo_url          = LOGO_URL,
    )


@app.route("/api/month-dates")
@login_required
def api_month_dates():
    """Return list of dates for a given month/year with weekend flags."""
    month_name = request.args.get("month", datetime.now().strftime("%B"))
    year       = int(request.args.get("year", datetime.now().year))
    months     = ["January","February","March","April","May","June",
                  "July","August","September","October","November","December"]
    month_idx  = months.index(month_name) + 1
    _, days    = calendar.monthrange(year, month_idx)
    today      = datetime.now().date()

    dates = []
    for day in range(1, days + 1):
        d          = datetime(year, month_idx, day).date()
        is_weekend = d.weekday() >= 5
        is_today   = d == today
        dates.append({
            "date":       d.isoformat(),
            "day_name":   d.strftime("%a"),
            "day_num":    d.strftime("%d"),
            "is_weekend": is_weekend,
            "is_today":   is_today,
        })
    return jsonify(dates)


@app.route("/api/autofill-owner")
@login_required
def api_autofill_owner():
    """Return the project owner for a given project name."""
    project = request.args.get("project", "").strip()
    owner   = consultant_owner_map.get(project, "")
    return jsonify({"owner": owner})


@app.route("/api/submit", methods=["POST"])
@login_required
def api_submit():
    """Receive timesheet data and submit to SharePoint."""
    data = request.get_json()

    consultant      = data.get("consultant", "").strip()
    consultant_type = data.get("type", "Internal")
    month           = data.get("month", "")
    year            = data.get("year", "")
    owner           = data.get("owner", "").strip()
    projects_data   = data.get("projects", [])   # [{name, hours:{date:h}, total}]

    if not consultant:
        return jsonify({"ok": False, "error": "Consultant name is required."}), 400
    if not owner:
        return jsonify({"ok": False, "error": "Project owner is required."}), 400
    if not projects_data:
        return jsonify({"ok": False, "error": "Please add at least one project."}), 400

    # Validate hours
    grand_total = 0.0
    for proj in projects_data:
        try:
            t = float(proj.get("total", 0))
            if t < 0:
                return jsonify({"ok": False, "error": "Hours cannot be negative."}), 400
            grand_total += t
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": f"Invalid hours for project '{proj.get('name')}'."}), 400

    try:
        submit_timesheet_to_sp_list(
            consultant, consultant_type, month, year, owner, projects_data
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    # Save to in-memory history (stored in session for this user)
    history = session.get("history", [])
    history.append({
        "date":        datetime.now().strftime("%d-%m-%Y %H:%M"),
        "consultant":  consultant,
        "type":        consultant_type,
        "month":       month,
        "year":        year,
        "owner":       owner,
        "total_hours": f"{grand_total:g}",
    })
    session["history"] = history

    return jsonify({
        "ok":          True,
        "grand_total": f"{grand_total:g}",
        "message":     f"Timesheet submitted to SharePoint! Total: {grand_total:g} hours",
    })


@app.route("/history")
@login_required
def history():
    records = session.get("history", [])
    return render_template("history.html", records=records)


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)