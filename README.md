# AttendAI: Smart Attendance System

Face-recognition attendance for a classroom, with liveness checks against photos and
videos, a React dashboard, a parent email inbox, and WhatsApp and email alerts.

```
smart-attendance/
├── backend/            Flask REST API + MySQL (XAMPP) + face recognition   (python app.py)
├── frontend/           React (Vite) dashboard                            (npm run dev)
├── whatsapp-bridge/    Sends WhatsApp messages through Baileys          (npm start)
└── legacy/             The original command-line scripts, with bug fixes
```

Three programs run side by side: the **API** on port 5000, the **dashboard** on 5173 and the
**WhatsApp bridge** on 5100. All three only listen on this computer.

---

## 1. Install the tools (once)

| Tool | Version | Download |
|---|---|---|
| Python | 3.10 – 3.13 | python.org (tick "Add Python to PATH") |
| Node.js | 20 or newer | nodejs.org (LTS) |
| XAMPP (MySQL / MariaDB) | 8.x | apachefriends.org (only MySQL is needed) |

## 2. The database (once)

Open the **XAMPP Control Panel** and press **Start** next to **MySQL** (tick the **Svc** box,
as administrator, to start it with Windows). That's all: the databases `attendai` and
`attendai_ithub` are created automatically on the first start, with XAMPP's default login
(user `root`, no password). If you set a MySQL password, copy `.env.example` to `.env` and
change `DATABASE_URL`. You can look at the tables in phpMyAdmin (http://localhost/phpmyadmin).

Moving from PostgreSQL? Start MySQL, then in `backend` run once:
`python manage.py copy-from-postgres postgresql://attendai:PASSWORD@localhost:5432/attendai`

## 3. Start the API

```bash
cd backend
pip install -r requirements.txt
pip install face_recognition --no-deps
python app.py
```

`--no-deps` matters: without it pip tries to compile dlib, which needs CMake and Visual Studio.
`dlib-bin` in requirements.txt is a ready-made dlib. The 68-point landmark model also comes
with pip now (`face_recognition_models`), so you don't have to download the `.dat` file.

## 4. Start the dashboard

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. On the first visit you create the **admin account**; after that
the dashboard asks for this login. If you forget the password: `python manage.py reset-password admin`.

## 5. Link WhatsApp

```bash
cd whatsapp-bridge
npm install
npm start
```

In the dashboard go to **Notify → WhatsApp** and scan the QR code with the school phone
(WhatsApp → Settings → Linked devices → Link a device). The link is saved in `whatsapp-bridge/auth/`.

> **About Baileys.** It talks to WhatsApp Web over a WebSocket. It's free, but it isn't an official
> API, and WhatsApp can block numbers that look like spam. Use a separate school number, ask
> parents to save it, and keep the gap between messages (Notify → Settings, default 6 seconds).
> If the number does get blocked, Twilio or the Meta WhatsApp Cloud API are the official, paid options.

## 6. Set up Gmail (sending and the parent inbox)

1. Turn on 2-Step Verification in the Google account.
2. Create an App Password at https://myaccount.google.com/apppasswords
3. Paste it in **Notify → Settings**. The same password lets the app read parents' emails over IMAP.
   It is stored encrypted.

## 7. Bring over data from the old version (optional)

If you already have `known_faces/` and `attendance_records/` from the old `app.py`:

```bash
cd backend
python manage.py import-old "C:\path\to\old\project"
```

This copies the students, photos, attendance CSVs, events and Gmail settings.

---

## 8. Put it online (teachers and parents from anywhere)

See **[deploy/README-DEPLOY.md](deploy/README-DEPLOY.md)**: the college PC keeps running AttendAI
(`python serve.py`, the app and API together on http://localhost:5000), Tailscale Funnel gives it a
free fixed `https://` address, and GitHub tests every change and updates the PC by itself.

## What each part does

| Feature | Where | Notes |
|---|---|---|
| Admin login | every page | JWT token, 12 hours. 5 wrong tries lock login for 60 s. |
| Register a student | Register | Only name + photo + consent are required. Roll no, branch, semester, parent name/relation/WhatsApp/email, address, qualifications and achievements are optional. Branch and semester stay filled in for the next student. |
| Live attendance | Live camera | Random challenge (blink, turn left/right, open mouth) + identity check twice. **Laptop camera is the default.** |
| Records | Attendance | Stored in MySQL; a copy is also written to `backend/attendance_records/YYYY-MM-DD.csv`. Branch filter. |
| Parent inbox | Dashboard panel + Inbox | Mails from parents' saved addresses, matched to their child. Reply from the app (same Gmail thread). Checked every 5 minutes. |
| 3-day absence alert | Notify → Absence alerts | WhatsApp + email to the parent. Weekends, days with no register and **holidays** are skipped. Goes out by itself when you stop the camera. One alert per absence streak. |
| Holiday notice | Notify → Holidays | Broadcast to all parents. |
| Exam results | Notify → Exam results | Create exam → download Excel template → fill marks (`AB` = absent) → upload `.xlsx`/`.csv` → each parent gets only their child's marks. |
| Events | Notify → Events | To students and/or parents, WhatsApp and/or email. |
| Message log | Notify → Sent | Every message, with the reason if it failed, and "Retry failed". |

## API endpoints (for the report, section 4.3)

All routes start with `/api` and need `Authorization: Bearer <token>`, except `/health` and `/auth/*`.

| Endpoint | Method | Purpose |
|---|---|---|
| `/auth/status`, `/auth/setup`, `/auth/login`, `/auth/me`, `/auth/password` | GET/POST | First-run setup, login, change password |
| `/students` | GET | All students with full details |
| `/register` | POST | New student: base64 photo + details (one face required) |
| `/students/<id>` | PUT / DELETE | Edit details / remove student |
| `/students/<id>/photo` | GET | Student photo |
| `/attendance/today`, `/attendance/<date>`, `/attendance/<date>/export`, `/attendance-dates`, `/history` | GET | Records, CSV export, last 7 days |
| `/start-attendance`, `/stop-attendance` | POST | Camera on / off (off = save day + absence alerts) |
| `/camera-status`, `/video-feed`, `/cameras`, `/camera-source` | GET/POST | Live state, MJPEG feed, camera choice |
| `/alerts`, `/alerts/send` | GET/POST | Absence streaks, send alerts |
| `/holidays`, `/holidays/<id>/notify` | GET/POST/DELETE | Holidays and notices |
| `/exams`, `/exams/<id>`, `/exams/<id>/template`, `/exams/<id>/upload`, `/exams/<id>/publish` | GET/POST/DELETE | Exams, marks upload, send results |
| `/events`, `/events/<id>/notify` | GET/POST/DELETE | Events |
| `/inbox`, `/inbox/<id>`, `/inbox/<id>/reply`, `/inbox/sync` | GET/POST | Parent emails |
| `/whatsapp/status`, `/whatsapp/test`, `/whatsapp/logout` | GET/POST | WhatsApp link |
| `/messages`, `/messages/status`, `/messages/retry` | GET/POST | Sent log, progress, retry |
| `/settings`, `/settings/test-email` | GET/POST | Gmail, alert days, channels, country code |

---

## Camera guide

**Default: the laptop's built-in camera.** It is enough for one student at a time, 50–80 cm from
the screen, with light on their face. You can pick another camera on the Live camera page.

**What matters (in this order):**

1. **Light on the face.** This matters more than the camera. A window *behind* the student causes
   most misses (your report measured 60–75% accuracy with backlight). Light from the front, or a
   small LED ring light in dim rooms.
2. **Autofocus and good low-light.** Fixed-focus budget webcams blur at 60–80 cm.
3. **1080p at 30 fps.** The software shrinks frames to 960 px wide anyway, so **4K gives no benefit**
   and only costs speed.
4. **Normal field of view (about 70–90°).** Wide 120° conference cameras make faces small and
   bent at the edges.

**Recommended upgrade:** a 1080p USB webcam with autofocus, in the class of the **Logitech C920 / C922**
or similar from other brands. Plug it straight into the laptop, not through a hub. Mount it at the
students' eye level by the classroom door, so each student stops in front of it for a few seconds.

**Avoid:**
- **Infrared "Windows Hello" cameras.** They show up as a second camera and give a grey picture.
  The app skips them automatically.
- **CCTV / IP cameras.** The liveness check needs one person close to the camera, and this version
  only reads USB/built-in cameras (not RTSP streams).
- **Fisheye or 120°+ wide-angle cameras.**
- **Phones used as webcams** (DroidCam etc.). They work, but add lag and disconnect.

The face must be at least about **100 px wide** in the frame. If students hear "Move closer",
the camera is too far or too wide.

---

## Tests

```bash
cd backend && pytest          # 12 tests, uses the attendai_test database
cd frontend && npm test
```

## Notes for the project report

The code and the report (SMART_ATTENDANCE_SYSTEM_ReUpdated.pdf) differ in a few places. Update the report:

- Frontend is **React 19 + Vite** (now matches "Vite"; it was Create React App before).
- Storage is **MySQL / MariaDB** (XAMPP) (the "Limitations" and "Future work" sections still say file storage).
- **Anti-spoofing is done**: random challenge-response liveness. Move it from Limitations/Future work to Contributions.
- WhatsApp is through **Baileys**, not Twilio; email through Gmail SMTP/IMAP.
- Face match threshold is **0.5** (stricter than the 0.6 in sections 3.2 and 3.3.2).
- The endpoint table in 4.3 should use the table above (`/api/register`, not `/api/register-camera`, etc.).
- Section 3.3.1: registration uses the **browser's** camera, and the 128-d encoding is stored in the database.
- Acknowledgements still say "[Guide Name]"; the cover says "ENGINERING".
