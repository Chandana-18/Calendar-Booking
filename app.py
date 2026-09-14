import streamlit as st
import sqlite3, uuid, smtplib, threading, os
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Page config ────────────────────────────────────────────
st.set_page_config(
    page_title="Office Hours Booker",
    page_icon="📅",
    layout="centered"
)

# ── Config ─────────────────────────────────────────────────
COURSES        = ["BTM 2000", "BTM 3850"]
INSTRUCTORS    = ["Tracy G", "Kerry G", "Sandip S"]
SLOT_HOURS     = list(range(10, 15))   # 10 AM – 2 PM start (ends 3 PM)
SEATS          = 3
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "labadmin123")
SMTP_USER      = st.secrets.get("SMTP_USER", "")
SMTP_PASS      = st.secrets.get("SMTP_PASS", "")
LAB_EMAIL_1    = st.secrets.get("LAB_EMAIL_1", "")
LAB_EMAIL_2    = st.secrets.get("LAB_EMAIL_2", "")
LAB_EMAILS     = [e for e in [LAB_EMAIL_1, LAB_EMAIL_2] if e]
DB             = "bookings.db"

# ── Database ───────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS bookings(
            id TEXT PRIMARY KEY, name TEXT, email TEXT, course TEXT,
            instructor TEXT, slot_date TEXT, slot_hour INTEGER,
            status TEXT DEFAULT 'confirmed', token TEXT,
            reminder_sent INTEGER DEFAULT 0, created_at TEXT)""")
        c.commit()

init_db()

# ── Helpers ────────────────────────────────────────────────
def slot_label(h):
    s = datetime.strptime(str(h),   "%H").strftime("%I:%M %p").lstrip("0")
    e = datetime.strptime(str(h+1), "%H").strftime("%I:%M %p").lstrip("0")
    return f"{s} – {e}"

def count_booked(d, h, exclude_id=None):
    with get_db() as c:
        if exclude_id:
            return c.execute(
                "SELECT COUNT(*) FROM bookings WHERE slot_date=? AND slot_hour=? AND status='confirmed' AND id!=?",
                (d, h, exclude_id)).fetchone()[0]
        return c.execute(
            "SELECT COUNT(*) FROM bookings WHERE slot_date=? AND slot_hour=? AND status='confirmed'",
            (d, h)).fetchone()[0]

def get_all_bookings():
    with get_db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM bookings ORDER BY slot_date, slot_hour, created_at").fetchall()]

def get_by_token(token):
    with get_db() as c:
        r = c.execute("SELECT * FROM bookings WHERE token=?", (token,)).fetchone()
    return dict(r) if r else None

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
        except Exception as e:
            print(f"Email error: {e}")
    threading.Thread(target=_send, daemon=True).start()

def mail_confirm(b, manage_url):
    lbl  = slot_label(b["slot_hour"])
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
    lbl   = slot_label(b["slot_hour"])
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
    lbl  = slot_label(b["slot_hour"])
    html = (f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto">'
            f'<h2 style="color:#DC2626">❌ Booking Cancelled</h2>'
            f'<p>Hi <b>{b["name"]}</b>, your slot on <b>{b["slot_date"]}</b>'
            f' at <b>{lbl}</b> has been cancelled.</p></div>')
    send_email(b["email"], "Office Hours — Booking Cancelled", html)

# ── CSS ────────────────────────────────────────────────────
st.markdown("""
<style>
.stApp { max-width: 860px; margin: 0 auto; }
div[data-testid="stForm"] { border: none; padding: 0; }
.slot-btn { width: 100%; }
.booking-card {
    background: #fff; border: 1px solid #DDE2EB; border-radius: 12px;
    padding: 16px 20px; margin-bottom: 10px;
}
.booking-card.cancelled { opacity: 0.5; }
.badge-ok  { background:#DCFCE7; color:#15803D; padding:2px 10px;
             border-radius:99px; font-size:12px; font-weight:600; }
.badge-no  { background:#FEE2E2; color:#DC2626; padding:2px 10px;
             border-radius:99px; font-size:12px; font-weight:600; }
.stat-box  { background:#fff; border:1px solid #DDE2EB; border-radius:10px;
             padding:16px; text-align:center; }
.stat-num  { font-size:28px; font-weight:700; color:#2563EB; }
.stat-lbl  { font-size:12px; color:#6B7280; margin-top:2px; }
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

    # ── Admin dashboard ───────────────────────────────────
    st.markdown("## 📋 Lab Bookings Dashboard")

    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 Refresh"):
            st.rerun()

    all_b = get_all_bookings()
    confirmed = [b for b in all_b if b["status"] == "confirmed"]
    cancelled = [b for b in all_b if b["status"] == "cancelled"]

    # Stats
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

    # Filters
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filter_status = st.selectbox("Status", ["All", "Confirmed", "Cancelled"])
    with col_f2:
        filter_course = st.selectbox("Course", ["All"] + COURSES)
    with col_f3:
        filter_date = st.date_input("Date", value=None, label_visibility="visible")

    # Apply filters
    filtered = all_b
    if filter_status != "All":
        filtered = [b for b in filtered if b["status"] == filter_status.lower()]
    if filter_course != "All":
        filtered = [b for b in filtered if b["course"] == filter_course]
    if filter_date:
        filtered = [b for b in filtered if b["slot_date"] == str(filter_date)]

    st.markdown(f"**{len(filtered)} booking{'s' if len(filtered)!=1 else ''}**")
    st.divider()

    if not filtered:
        st.info("No bookings match your filters.")
    else:
        for b in filtered:
            lbl    = slot_label(b["slot_hour"])
            status = "Confirmed" if b["status"]=="confirmed" else "Cancelled"
            badge  = "badge-ok" if b["status"]=="confirmed" else "badge-no"
            cls    = "" if b["status"]=="confirmed" else "cancelled"

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
                    if b["status"] == "confirmed":
                        if st.button("Cancel", key=f"cancel_{b['id']}"):
                            with get_db() as db:
                                db.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (b["id"],))
                                db.commit()
                            mail_cancel(b)
                            mail_lab(b, "cancel")
                            st.success("Cancelled.")
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
    b = get_by_token(token)
    if not b:
        st.error("Booking not found.")
        st.stop()

    lbl    = slot_label(b["slot_hour"])
    status = "Confirmed" if b["status"]=="confirmed" else "Cancelled"

    st.markdown("## 📅 Your Booking")
    if b["status"] == "confirmed":
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

    if b["status"] == "confirmed":
        st.divider()

        # ── Edit booking ──────────────────────────────────
        with st.expander("✏️ Edit / Rebook"):
            new_date = st.date_input("New Date", value=date.fromisoformat(b["slot_date"]),
                                     min_value=date.today(), key="edit_date")
            available = []
            for h in SLOT_HOURS:
                n = count_booked(str(new_date), h, exclude_id=b["id"])
                avail = SEATS - n
                if avail > 0:
                    available.append((h, f"{slot_label(h)}  —  {avail} seat{'s' if avail!=1 else ''} left"))
            if not available:
                st.warning("No slots available on that date.")
            else:
                slot_choice = st.selectbox("Time Slot", available,
                                           format_func=lambda x: x[1], key="edit_slot")
                new_name   = st.text_input("Name",  value=b["name"], key="edit_name")
                new_email  = st.text_input("Email", value=b["email"], key="edit_email")
                new_course = st.selectbox("Course", COURSES,
                                          index=COURSES.index(b["course"]) if b["course"] in COURSES else 0,
                                          key="edit_course")
                new_instr  = st.selectbox("Instructor", INSTRUCTORS,
                                          index=INSTRUCTORS.index(b["instructor"]) if b["instructor"] in INSTRUCTORS else 0,
                                          key="edit_instr")
                if st.button("💾 Save Changes"):
                    with get_db() as db:
                        db.execute("""UPDATE bookings SET name=?,email=?,course=?,instructor=?,
                                      slot_date=?,slot_hour=?,reminder_sent=0 WHERE id=?""",
                            (new_name, new_email, new_course, new_instr,
                             str(new_date), slot_choice[0], b["id"]))
                        db.commit()
                    updated = get_by_token(token)
                    base_url = st.secrets.get("APP_URL", "https://your-app.streamlit.app")
                    manage_url = f"{base_url}?page=manage&token={token}"
                    mail_confirm(updated, manage_url)
                    st.success("✅ Booking updated! Confirmation email sent.")
                    st.rerun()

        # ── Cancel ────────────────────────────────────────
        st.divider()
        if st.button("❌ Cancel My Booking", type="secondary"):
            with get_db() as db:
                db.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (b["id"],))
                db.commit()
            mail_cancel(b)
            mail_lab(b, "cancel")
            st.error("Your booking has been cancelled.")
            st.rerun()
    else:
        st.info("This booking has been cancelled. [Book a new slot](/?page=book)")

    st.stop()

# ════════════════════════════════════════════════════════════
#  BOOK A SLOT (student - main page)
# ════════════════════════════════════════════════════════════
else:
    st.markdown("## 📅 Book an Office Hours Slot")
    st.markdown("Pick a date, choose an open time slot, and fill in your details.")
    st.divider()

    # Date picker
    selected_date = st.date_input("Select a date",
                                  min_value=date.today(),
                                  value=date.today())
    date_str = str(selected_date)

    # Slot grid
    st.markdown(f"**Available slots for {selected_date.strftime('%A, %B %d')}**")
    cols = st.columns(len(SLOT_HOURS))
    selected_hour = st.session_state.get("selected_hour", None)

    for i, h in enumerate(SLOT_HOURS):
        n     = count_booked(date_str, h)
        avail = SEATS - n
        label = slot_label(h)
        with cols[i]:
            if avail <= 0:
                st.button(f"**{label}**\n\nFull", disabled=True, key=f"slot_{h}", use_container_width=True)
            else:
                is_sel = selected_hour == h
                btn_label = f"**{label}**\n\n{'✅ Selected' if is_sel else f'{avail} seat{chr(115) if avail!=1 else chr(32)} left'}"
                if st.button(btn_label, key=f"slot_{h}", use_container_width=True,
                             type="primary" if is_sel else "secondary"):
                    st.session_state.selected_hour = h
                    st.rerun()

    selected_hour = st.session_state.get("selected_hour", None)

    st.divider()

    # Booking form
    with st.form("booking_form"):
        st.markdown("**Your Details**")
        c1, c2 = st.columns(2)
        with c1:
            name   = st.text_input("Full Name", placeholder="e.g. Maria Chen")
            course = st.selectbox("Course", ["Select..."] + COURSES)
        with c2:
            email  = st.text_input("Email Address", placeholder="you@university.edu")
            instr  = st.selectbox("Instructor", ["Select..."] + INSTRUCTORS)

        submit = st.form_submit_button("Confirm Booking", type="primary", use_container_width=True)

        if submit:
            errs = []
            if not name.strip():           errs.append("Name is required.")
            if "@" not in email:           errs.append("Valid email is required.")
            if course == "Select...":      errs.append("Select a course.")
            if instr  == "Select...":      errs.append("Select an instructor.")
            if not selected_hour:          errs.append("Select a time slot above.")
            if not errs and count_booked(date_str, selected_hour) >= SEATS:
                errs.append("That slot just filled up — please pick another.")

            if errs:
                for e in errs:
                    st.error(e)
            else:
                bid = str(uuid.uuid4())
                tok = str(uuid.uuid4())
                with get_db() as db:
                    db.execute("""INSERT INTO bookings
                        (id,name,email,course,instructor,slot_date,slot_hour,token,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        (bid, name.strip(), email.strip(), course, instr,
                         date_str, selected_hour, tok, datetime.now().isoformat()))
                    db.commit()

                b = get_by_token(tok)
                base_url   = st.secrets.get("APP_URL", "https://your-app.streamlit.app")
                manage_url = f"{base_url}?page=manage&token={tok}"

                mail_confirm(b, manage_url)
                mail_lab(b, "new")

                st.session_state.selected_hour = None
                st.success(f"✅ Booking confirmed for {slot_label(selected_hour)} on {date_str}!")
                st.info(f"📧 Confirmation sent to **{email}**. Check your inbox (and spam).")
                st.markdown(f"🔗 **Your manage link:** [Click here to manage your booking]({manage_url})")
                st.markdown(f"*(Save this link to edit or cancel your booking later)*")
