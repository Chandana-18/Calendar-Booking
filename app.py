import streamlit as st
import gspread, uuid, smtplib, threading, os
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2.service_account import Credentials
from apscheduler.schedulers.background import BackgroundScheduler

# ── Page config ────────────────────────────────────────────
st.set_page_config(
    page_title="Book your one hour research slot at DS 106",
    page_icon="📅",
    layout="centered"
)

# ── Config ─────────────────────────────────────────────────
COURSES        = ["BTM 2000", "BTM 3850"]
INSTRUCTORS    = ["Tracy G", "Kerry G", "Sandip S"]
SLOT_HOURS     = list(range(10, 16))   # 10 AM – 3 PM start (ends 4 PM)
SEATS          = 3
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "labadmin123")
SMTP_USER      = st.secrets.get("SMTP_USER", "")
SMTP_PASS      = st.secrets.get("SMTP_PASS", "")
LAB_EMAIL_1    = st.secrets.get("LAB_EMAIL_1", "")
LAB_EMAIL_2    = st.secrets.get("LAB_EMAIL_2", "")
LAB_EMAILS     = [e for e in [LAB_EMAIL_1, LAB_EMAIL_2] if e]
APP_URL        = st.secrets.get("APP_URL", "https://your-app.streamlit.app")
SHEET_NAME     = "OfficeHoursBookings"

# ── Google Sheets connection ───────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SHEET_ID = "1PDJ0mTy6SsZC70S25FaNjcWPOAGxveAormAVN7QLcyM"

@st.cache_resource
def get_sheet():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)
    ws = sh.sheet1
    # Add headers if sheet is empty
    if not ws.get_all_values() or ws.cell(1, 1).value != "id":
        ws.clear()
        ws.append_row([
            "id", "name", "email", "course", "instructor",
            "slot_date", "slot_hour", "status", "token",
            "reminder_sent", "created_at"
        ])
    return ws

def get_all_rows():
    ws = get_sheet()
    records = ws.get_all_records()
    return records

def find_row_by_token(token):
    ws = get_sheet()
    records = ws.get_all_records()
    for i, r in enumerate(records, start=2):  # row 1 is header
        if r.get("token") == token:
            return i, r
    return None, None

def find_row_by_id(bid):
    ws = get_sheet()
    records = ws.get_all_records()
    for i, r in enumerate(records, start=2):
        if r.get("id") == bid:
            return i, r
    return None, None

def add_booking(row_data):
    ws = get_sheet()
    ws.append_row(row_data)

def update_cell_by_row(row_num, col_name, value):
    ws = get_sheet()
    headers = ws.row_values(1)
    col_idx = headers.index(col_name) + 1
    ws.update_cell(row_num, col_idx, value)

def update_booking_row(row_num, data: dict):
    ws = get_sheet()
    headers = ws.row_values(1)
    for col_name, value in data.items():
        col_idx = headers.index(col_name) + 1
        ws.update_cell(row_num, col_idx, value)

def count_booked(d, h, exclude_id=None):
    records = get_all_rows()
    return sum(
        1 for r in records
        if str(r.get("slot_date")) == str(d)
        and str(r.get("slot_hour")) == str(h)
        and r.get("status") == "confirmed"
        and (exclude_id is None or r.get("id") != exclude_id)
    )

# ── Helpers ────────────────────────────────────────────────
def slot_label(h):
    s = datetime.strptime(str(h),   "%H").strftime("%I:%M %p").lstrip("0")
    e = datetime.strptime(str(h+1), "%H").strftime("%I:%M %p").lstrip("0")
    return f"{s} – {e}"

# ── Email ──────────────────────────────────────────────────
def tr(k, v):
    return (f'<tr><td style="padding:8px;border:1px solid #E5E7EB;background:#F9FAFB;'
            f'width:120px"><b>{k}</b></td>'
            f'<td style="padding:8px;border:1px solid #E5E7EB">{v}</td></tr>')

def send_email(to, subject, html):
    if not SMTP_USER or not SMTP_PASS:
        return
    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = SMTP_USER
            msg["To"]      = to
            msg.attach(MIMEText(html, "html"))
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(SMTP_USER, [to], msg.as_string())
            print(f"✉️ Sent: {subject} → {to}")
        except Exception as e:
            print(f"❌ Email error: {e}")
    threading.Thread(target=_send, daemon=True).start()

def mail_confirm(b, manage_url):
    lbl  = slot_label(int(b["slot_hour"]))
    html = (f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto">'
            f'<h2 style="color:#2563EB">✅ Booking Confirmed</h2>'
            f'<p>Hi <b>{b["name"]}</b>, your office-hours slot is confirmed.</p>'
            f'<table style="border-collapse:collapse;width:100%;margin:16px 0">'
            f'{tr("Date",b["slot_date"])}{tr("Time",lbl)}'
            f'{tr("Course",b["course"])}{tr("Instructor",b["instructor"])}'
            f'</table>'
            f'<a href="{manage_url}" style="display:inline-block;padding:10px 20px;'
            f'background:#2563EB;color:#fff;border-radius:6px;text-decoration:none">'
            f'Manage / Cancel Booking</a>'
            f'<p style="color:#6B7280;font-size:13px;margin-top:14px">'
            f'You will receive a reminder 1 hour before your slot.</p></div>')
    send_email(b["email"], "Office Hours — Booking Confirmed", html)

def mail_lab(b, action="new"):
    lbl   = slot_label(int(b["slot_hour"]))
    icon  = "🔔 New Booking" if action == "new" else "❌ Cancelled"
    color = "#2563EB" if action == "new" else "#DC2626"
    subj  = (f"New Booking – {b['name']} ({b['course']})" if action == "new"
             else f"Cancelled – {b['name']} ({b['course']})")
    html  = (f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto">'
             f'<h2 style="color:{color}">{icon}</h2>'
             f'<table style="border-collapse:collapse;width:100%;margin:16px 0">'
             f'{tr("Student",b["name"])}{tr("Email",b["email"])}'
             f'{tr("Course",b["course"])}{tr("Instructor",b["instructor"])}'
             f'{tr("Date",b["slot_date"])}{tr("Time",lbl)}'
             f'</table></div>')
    for addr in LAB_EMAILS:
        send_email(addr, subj, html)

def mail_cancel(b):
    lbl  = slot_label(int(b["slot_hour"]))
    html = (f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto">'
            f'<h2 style="color:#DC2626">❌ Booking Cancelled</h2>'
            f'<p>Hi <b>{b["name"]}</b>, your slot on <b>{b["slot_date"]}</b>'
            f' at <b>{lbl}</b> has been cancelled.</p></div>')
    send_email(b["email"], "Office Hours — Booking Cancelled", html)

def mail_reminder(b):
    lbl  = slot_label(int(b["slot_hour"]))
    html = (f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto">'
            f'<h2 style="color:#D97706">⏰ Reminder: Your Slot is in 1 Hour</h2>'
            f'<p>Hi <b>{b["name"]}</b>, your office-hours session starts in <b>1 hour</b>.</p>'
            f'<p>📅 <b>{b["slot_date"]}</b> at <b>{lbl}</b>'
            f' with <b>{b["instructor"]}</b></p></div>')
    send_email(b["email"], "Reminder — Office Hours in 1 Hour", html)

# ── Reminder scheduler ─────────────────────────────────────
def check_reminders():
    now = datetime.now()
    try:
        records = get_all_rows()
        for b in records:
            if b.get("status") != "confirmed":
                continue
            if str(b.get("reminder_sent", "0")) == "1":
                continue
            try:
                slot_dt = datetime.strptime(
                    f"{b['slot_date']} {b['slot_hour']}:00", "%Y-%m-%d %H:%M")
                diff = (slot_dt - now).total_seconds()
                if 0 < diff <= 3600:
                    mail_reminder(b)
                    row_num, _ = find_row_by_id(b["id"])
                    if row_num:
                        update_cell_by_row(row_num, "reminder_sent", "1")
                    print(f"[REMINDER] Sent to {b['name']}")
            except Exception as e:
                print(f"[REMINDER ROW ERROR] {e}")
    except Exception as e:
        print(f"[REMINDER ERROR] {e}")

if "scheduler_started" not in st.session_state:
    _sched = BackgroundScheduler()
    _sched.add_job(check_reminders, "interval", minutes=5)
    _sched.start()
    st.session_state.scheduler_started = True

# ── CSS ────────────────────────────────────────────────────
st.markdown("""
<style>
.stApp { max-width: 860px; margin: 0 auto; }
div[data-testid="stForm"] { border: none; padding: 0; }
.booking-card {
    background: #fff; border: 1px solid #DDE2EB; border-radius: 12px;
    padding: 16px 20px; margin-bottom: 10px;
}
.booking-card.cancelled { opacity: 0.5; }
.badge-ok { background:#DCFCE7; color:#15803D; padding:2px 10px;
            border-radius:99px; font-size:12px; font-weight:600; }
.badge-no { background:#FEE2E2; color:#DC2626; padding:2px 10px;
            border-radius:99px; font-size:12px; font-weight:600; }
.stat-box { background:#fff; border:1px solid #DDE2EB; border-radius:10px;
            padding:16px; text-align:center; }
.stat-num { font-size:28px; font-weight:700; color:#2563EB; }
.stat-lbl { font-size:12px; color:#6B7280; margin-top:2px; }
</style>
""", unsafe_allow_html=True)

# ── URL params ─────────────────────────────────────────────
params = st.query_params
page   = params.get("page", "book")
token  = params.get("token", "")

# ════════════════════════════════════════════════════════════
#  ADMIN VIEW
# ════════════════════════════════════════════════════════════
if page == "admin":
    if "admin_ok" not in st.session_state:
        st.session_state.admin_ok = False

    if not st.session_state.admin_ok:
        st.markdown("## 🔒 Lab Admin Login")
        pwd = st.text_input("Password", type="password")
        if st.button("Login"):
            if pwd == ADMIN_PASSWORD:
                st.session_state.admin_ok = True
                st.rerun()
            else:
                st.error("Wrong password.")
        st.stop()

    st.markdown("## 📋 Lab Bookings Dashboard")
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 Refresh"):
            st.cache_resource.clear()
            st.rerun()

    all_b     = get_all_rows()
    confirmed = [b for b in all_b if b.get("status") == "confirmed"]
    cancelled = [b for b in all_b if b.get("status") == "cancelled"]

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f'<div class="stat-box"><div class="stat-num">{len(all_b)}</div>'
                    f'<div class="stat-lbl">Total Bookings</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="stat-box"><div class="stat-num" style="color:#15803D">{len(confirmed)}</div>'
                    f'<div class="stat-lbl">Confirmed</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="stat-box"><div class="stat-num" style="color:#DC2626">{len(cancelled)}</div>'
                    f'<div class="stat-lbl">Cancelled</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filter_status = st.selectbox("Status", ["All", "Confirmed", "Cancelled"])
    with col_f2:
        filter_course = st.selectbox("Course", ["All"] + COURSES)
    with col_f3:
        filter_date = st.date_input("Date", value=None, label_visibility="visible")

    filtered = all_b
    if filter_status != "All":
        filtered = [b for b in filtered if b.get("status") == filter_status.lower()]
    if filter_course != "All":
        filtered = [b for b in filtered if b.get("course") == filter_course]
    if filter_date:
        filtered = [b for b in filtered if str(b.get("slot_date")) == str(filter_date)]

    st.markdown(f"**{len(filtered)} booking{'s' if len(filtered)!=1 else ''}**")
    st.divider()

    if not filtered:
        st.info("No bookings match your filters.")
    else:
        for b in filtered:
            lbl    = slot_label(int(b["slot_hour"]))
            status = "Confirmed" if b.get("status")=="confirmed" else "Cancelled"
            badge  = "badge-ok" if b.get("status")=="confirmed" else "badge-no"
            cls    = "" if b.get("status")=="confirmed" else "cancelled"
            with st.container():
                bc1, bc2 = st.columns([4, 1])
                with bc1:
                    st.markdown(
                        f'<div class="booking-card {cls}">'
                        f'<b>{b["name"]}</b> &nbsp; <span class="{badge}">{status}</span><br>'
                        f'<span style="color:#6B7280;font-size:13px">'
                        f'{b["email"]} · {b["course"]} · {b["instructor"]}</span><br>'
                        f'<span style="font-size:13px">📅 {b["slot_date"]} &nbsp; ⏰ {lbl}</span>'
                        f'</div>', unsafe_allow_html=True)
                with bc2:
                    if b.get("status") == "confirmed":
                        if st.button("Cancel", key=f"cancel_{b['id']}"):
                            row_num, _ = find_row_by_id(b["id"])
                            if row_num:
                                update_cell_by_row(row_num, "status", "cancelled")
                            mail_cancel(b)
                            mail_lab(b, "cancel")
                            st.success("Cancelled.")
                            st.cache_resource.clear()
                            st.rerun()

    st.divider()
    if st.button("🚪 Logout"):
        st.session_state.admin_ok = False
        st.rerun()
    st.stop()

# ════════════════════════════════════════════════════════════
#  MANAGE BOOKING (student)
# ════════════════════════════════════════════════════════════
elif page == "manage" and token:
    row_num, b = find_row_by_token(token)
    if not b:
        st.error("Booking not found.")
        st.stop()

    lbl    = slot_label(int(b["slot_hour"]))
    status = "Confirmed" if b.get("status")=="confirmed" else "Cancelled"

    st.markdown("## 📅 Your Booking")
    if b.get("status") == "confirmed":
        st.success(f"Status: **{status}**")
    else:
        st.error(f"Status: **{status}**")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Name:** {b['name']}")
        st.markdown(f"**Email:** {b['email']}")
        st.markdown(f"**Course:** {b['course']}")
    with col2:
        st.markdown(f"**Instructor:** {b['instructor']}")
        st.markdown(f"**Date:** {b['slot_date']}")
        st.markdown(f"**Time:** {lbl}")

    if b.get("status") == "confirmed":
        st.divider()

        with st.expander("✏️ Edit / Rebook"):
            new_date = st.date_input("New Date",
                                     value=date.fromisoformat(str(b["slot_date"])),
                                     min_value=date.today(), key="edit_date")
            available = []
            for h in SLOT_HOURS:
                n     = count_booked(str(new_date), h, exclude_id=b["id"])
                avail = SEATS - n
                if avail > 0:
                    available.append((h, f"{slot_label(h)}  —  {avail} seat{'s' if avail!=1 else ''} left"))
            if not available:
                st.warning("No slots available on that date.")
            else:
                slot_choice = st.selectbox("Time Slot", available,
                                           format_func=lambda x: x[1], key="edit_slot")
                new_name   = st.text_input("Name",  value=b["name"],  key="edit_name")
                new_email  = st.text_input("Email", value=b["email"], key="edit_email")
                new_course = st.selectbox("Course", COURSES,
                                          index=COURSES.index(b["course"]) if b["course"] in COURSES else 0,
                                          key="edit_course")
                new_instr  = st.selectbox("Instructor", INSTRUCTORS,
                                          index=INSTRUCTORS.index(b["instructor"]) if b["instructor"] in INSTRUCTORS else 0,
                                          key="edit_instr")
                if st.button("💾 Save Changes"):
                    update_booking_row(row_num, {
                        "name":       new_name,
                        "email":      new_email,
                        "course":     new_course,
                        "instructor": new_instr,
                        "slot_date":  str(new_date),
                        "slot_hour":  slot_choice[0],
                        "reminder_sent": "0"
                    })
                    updated_row, updated = find_row_by_token(token)
                    manage_url = f"{APP_URL}?page=manage&token={token}"
                    mail_confirm(updated, manage_url)
                    st.cache_resource.clear()
                    st.success("✅ Booking updated! Confirmation email sent.")
                    st.rerun()

        st.divider()
        if st.button("❌ Cancel My Booking", type="secondary"):
            update_cell_by_row(row_num, "status", "cancelled")
            mail_cancel(b)
            mail_lab(b, "cancel")
            st.cache_resource.clear()
            st.error("Your booking has been cancelled.")
            st.rerun()
    else:
        st.info(f"This booking is cancelled. [Book a new slot]({APP_URL})")

    st.stop()

# ════════════════════════════════════════════════════════════
#  BOOK A SLOT (main page)
# ════════════════════════════════════════════════════════════
else:
    st.markdown("## 📅 Book your one hour research slot at DS 106")
    st.markdown("Pick a date, choose an open time slot, and fill in your details.")
    st.divider()

    selected_date = st.date_input("Select a date",
                                  min_value=date.today(),
                                  value=date.today())
    date_str = str(selected_date)

    st.markdown(f"**Available slots for {selected_date.strftime('%A, %B %d')}**")
    cols = st.columns(len(SLOT_HOURS))
    selected_hour = st.session_state.get("selected_hour", None)

    for i, h in enumerate(SLOT_HOURS):
        n     = count_booked(date_str, h)
        avail = SEATS - n
        label = slot_label(h)
        with cols[i]:
            if avail <= 0:
                st.button(f"**{label}**\n\nFull", disabled=True,
                          key=f"slot_{h}", use_container_width=True)
            else:
                is_sel    = selected_hour == h
                btn_label = f"**{label}**\n\n{'✅ Selected' if is_sel else f'{avail} seat{chr(115) if avail!=1 else chr(32)} left'}"
                if st.button(btn_label, key=f"slot_{h}",
                             use_container_width=True,
                             type="primary" if is_sel else "secondary"):
                    st.session_state.selected_hour = h
                    st.rerun()

    selected_hour = st.session_state.get("selected_hour", None)
    st.divider()

    with st.form("booking_form"):
        st.markdown("**Your Details**")
        c1, c2 = st.columns(2)
        with c1:
            name   = st.text_input("Full Name", placeholder="e.g. Maria Chen")
            course = st.selectbox("Course", ["Select..."] + COURSES)
        with c2:
            email  = st.text_input("Email Address", placeholder="you@university.edu")
            instr  = st.selectbox("Instructor", ["Select..."] + INSTRUCTORS)

        submit = st.form_submit_button("Confirm Booking", type="primary",
                                       use_container_width=True)
        if submit:
            errs = []
            if not name.strip():        errs.append("Name is required.")
            if "@" not in email:        errs.append("Valid email is required.")
            if course == "Select...":   errs.append("Select a course.")
            if instr  == "Select...":   errs.append("Select an instructor.")
            if not selected_hour:       errs.append("Select a time slot above.")
            if not errs and count_booked(date_str, selected_hour) >= SEATS:
                errs.append("That slot just filled up — please pick another.")

            if errs:
                for e in errs:
                    st.error(e)
            else:
                bid = str(uuid.uuid4())
                tok = str(uuid.uuid4())
                add_booking([
                    bid, name.strip(), email.strip(), course, instr,
                    date_str, selected_hour, "confirmed", tok, "0",
                    datetime.now().isoformat()
                ])
                b = {"id": bid, "name": name.strip(), "email": email.strip(),
                     "course": course, "instructor": instr,
                     "slot_date": date_str, "slot_hour": selected_hour,
                     "status": "confirmed", "token": tok}
                manage_url = f"{APP_URL}?page=manage&token={tok}"
                mail_confirm(b, manage_url)
                mail_lab(b, "new")
                st.session_state.selected_hour = None
                st.cache_resource.clear()
                st.success(f"✅ Booking confirmed for {slot_label(selected_hour)} on {date_str}!")
                st.info(f"📧 Confirmation sent to **{email}**. Check your inbox (and spam).")
                st.markdown(f"🔗 **Your manage link:** [Click here to manage your booking]({manage_url})")
                st.markdown("*(Save this link to edit or cancel your booking later)*")
