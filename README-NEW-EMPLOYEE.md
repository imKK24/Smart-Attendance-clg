# AttendAI: guide for new staff

AttendAI is the college's face-recognition attendance register. It marks attendance
from a camera or a class photo, keeps student records, and tells parents about
absences, holidays and exam results by WhatsApp and email.

**Where to open it**

| From | Address |
|---|---|
| Anywhere (phone, home, college) | **https://laptop-tf66rgp8.tail5b50a8.ts.net** |
| On the AttendAI computer itself | http://localhost:5000 |

Use Chrome or Edge. On a phone, you can add it to the home screen (browser menu > *Add to Home screen*).

---

### Aakansha IT Hub staff

Aakansha IT Hub has its own login page and its own students, at the same address with **`/it-hub`** on the end:
**https://laptop-tf66rgp8.tail5b50a8.ts.net/it-hub** (on the AttendAI laptop: http://localhost:5000/it-hub).
The screens are the same as the college's, in teal instead of blue, with these differences:

- Students join one or more **courses** (Python, Tally…) instead of a branch. The admin keeps the
  course list on **Students > Course list**.
- Pick the **course** in the menu on the left (on a phone, at the top). Attendance, the dashboard,
  class photos, reports and fees all follow that course. **Attendance is kept per course.**
- Tests (Notify > Test results) and fees can be set per course.
- There is **no parent login** for the IT Hub.
- The IT Hub sends messages through the college's WhatsApp and Gmail, which only the college admin can change.
- The college and the IT Hub can't see each other's students, staff, registers, holidays or messages.

## 1. Your first login (everyone)

1. Ask the **admin** to make your account. You'll get a login email and a first password.
2. Open the address and pick the **Admin** or **Teacher** tab (whichever the admin made you), then log in.
3. AttendAI asks you to **choose your own password**:
   - at least 8 characters
   - not a common password like `12345678`
   - must not contain your login name

   After that, only you know it.
4. If you forget it, or want to change it later, ask the admin to reset it. You'll then choose
   a new one at your next login. Admins can also change their own under **Notify > Settings**.

> After 5 wrong passwords the account is locked for 1 minute. Each further lock doubles, up to 15 minutes.

## 2. What each role can do

| | Teacher | Admin |
|---|---|---|
| Take attendance, see the register | ✅ (own branches only) | ✅ all branches |
| Register students, add photos | ✅ (own branches) | ✅ |
| Leave, Reports, Inbox, Notify (send alerts, results) | ✅ (own branches) | ✅ |
| Delete students or exams; holidays and events | ❌ | ✅ |
| Fees, Team (staff accounts), settings, WhatsApp link | ❌ | ✅ |
| Choose attendance methods and cameras | ❌ | ✅ |

**Parents** have their own read-only **Parent** tab on the login page (see section 6).

## 3. Everyday work (teachers)

### Taking attendance: menu > **Take attendance**
The admin decides which methods are switched on.

- **Live camera.** Choose the camera and press **Start**. Each student looks at the camera
  and **blinks twice**. When a student is recognised and passes the blink check, they're
  marked present and their name appears under *Marked this session*. Press **Stop** when done.
  *Use this in the room with the AttendAI computer, or with a classroom IP camera.*
- **Class photo.** On your phone, take **1–3 photos** of the class from the front.
  AttendAI finds every face and shows the list. **Check it**: tick anyone it missed, untick
  any mistakes. Then **Save**. The photos are kept as evidence.
  *Best from a phone: good light, faces towards the camera, no one hidden behind others.*

### Other pages
- **Dashboard:** today's attendance %, the last 7 sessions, and *Needs attention*: students
  below the minimum or absent several days in a row. Use **WhatsApp parent** there.
- **Attendance:** the register for any day; **Export for Excel**.
- **Students:** search, open a student, edit details, add extra face photos.
- **Leave:** applications from parents (from the portal or email). Approve or reject.
- **Reports:** *Exam eligibility* (who is below the minimum %), *Monthly register*
  (Excel download), *Insights* (charts).
- **Inbox:** emails from parents; reply from here.
- **Notify:** *Absence alerts* (students absent 3 days in a row, to message parents),
  *Exam results* (download the Excel template, fill in the marks, upload, then **Send results**),
  and the *Sent* log of every message.

## 4. Registering a new student: menu > **Register**

1. **Collect the signed consent form first.** It's needed before any face photo is saved.
2. Fill in:
   - **Student:** name, **registration number**, branch, class
   - **Parent:** name, relation, **mobile** (used for WhatsApp alerts and the parent login), email
   - address, qualifications and achievements (optional)
3. **Take or upload a photo:** face straight on, good light, no cap or mask.
4. Tick the **consent** box and click **Save**.
5. For better recognition, open the student on the **Students** page and add 1–2 more photos
   (e.g. with and without glasses).

Registration numbers may contain only letters, numbers, `/`, `-`, `.` and spaces.

## 5. Admin tasks

| Task | Where |
|---|---|
| Add a teacher, set their branches, reset a password, switch an account off | **Team** |
| Choose attendance methods (Live camera / Class photo), add IP cameras, choose the blink check (quick or secure) | **Take attendance** |
| Link the college WhatsApp (scan the QR with the college phone) | **Notify > WhatsApp** |
| Set up Gmail for sending and the parent inbox | **Notify > Settings** |
| Holidays and events (parents are told) | **Notify > Holidays / Events** |
| Fees and fee reminders | **Fees** |
| Change your own password | **Notify > Settings** |

When someone leaves the college, **switch their account off** in Team the same day.

## 6. Parents

Tell parents:
1. Open the address and choose the **Parent** tab.
2. Enter the student's **registration number**, the student's **full name**, and **the mobile
   number given to the college**.
3. They can see attendance, exam results and leave records, and **apply for leave**.
   They can't change anything else.
4. The parent login ends after 2 hours.

## 7. Looking after the AttendAI computer (person in charge)

AttendAI runs on one college laptop: **LAPTOP-TF66RGP8**.

- **The laptop must stay on, plugged in and logged in.** When it's off or asleep, the website is off too.
- **After a restart or Windows update:** log in to Windows once, then lock the screen with **Win + L**.
  AttendAI starts by itself and keeps running while the screen is locked.
- **Start / stop by hand:** `deploy\windows\start-attendai.bat` / `stop-attendai.bat`.
- **If something is wrong:** look in the `logs` folder (`backend.err.log`, `whatsapp.err.log`).
  Restarting with stop and then start fixes most problems.
- **Backups** run every night at 9 PM into the `backups` folder (last 14 nights).
  **Copy that folder to a pen drive every week.**
- **MySQL** (the database, from XAMPP) must be running: open the *XAMPP Control Panel*, MySQL must show green / *Running*.
- Full details on going online, Tailscale and GitHub are in `deploy\README-DEPLOY.md`.

**Never** delete or share these folders. They hold student faces, passwords and keys:
`backend\data`, `backend\known_faces`, `backend\class_photos`, `whatsapp-bridge\auth`, `backups`, and the `.env` file.

## 8. For developers (changing the code)

1. Get access to the **private** GitHub repository from the admin, then clone it.
   ```
   git clone https://github.com/<college-account>/attendai.git
   ```
2. Install Python 3.12, Node.js (LTS) and XAMPP (only MySQL is needed). Start MySQL in the
   XAMPP Control Panel. The databases (`attendai`, `attendai_ithub` and the test ones) are
   created automatically the first time the backend or the tests run.
3. Backend:
   ```
   cd backend
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   pip install face_recognition --no-deps
   python app.py          (development server, http://localhost:5000)
   ```
4. Frontend, in a second window:
   ```
   cd frontend
   npm install
   npm run dev            (http://localhost:5173)
   ```
5. Before pushing, run the tests:
   - backend: `python -m pytest -q`
   - frontend: `npx vitest run`
6. Push to a branch and open a pull request. When it's merged into **main**, GitHub runs all
   tests again and, if they pass, **updates the AttendAI computer by itself**. Check the
   **Actions** tab.

Rules:
- Never commit `.env`, keys, student photos or backups. `.gitignore` blocks them, but check `git status` anyway.
- Never use real student data for testing. The tests use their own `attendai_test` database.
- Don't run `npm run dev` on the AttendAI computer while it's serving users.

## 9. Privacy rules (everyone)

- Face photos are **biometric data**. Take them only with a signed consent form, and never
  copy them off the AttendAI system.
- Don't share your password or let others use your login. Log out on shared computers.
- Only message parents through AttendAI (it records every message in *Sent*).
- Report a lost phone or a suspected break-in to the admin straight away. They can reset
  your password, which logs you out everywhere.

## 10. Quick help

| Problem | What to do |
|---|---|
| Site doesn't open | Is the AttendAI laptop on and logged in? Tell the person in charge. |
| "Too many wrong tries" | Wait the time shown, or ask the admin to reset your password. |
| A student isn't recognised | Add 1–2 more photos on **Students**; check the light; or mark from a class photo. |
| WhatsApp messages stuck in *Waiting* | Admin: **Notify > WhatsApp**. If it shows a QR code, scan it again with the college phone. |
| Parent can't log in | Check the student's registration number, full name and parent mobile on **Students**. They must match exactly. |
| Anything else | Ask the admin. Technical details are in `README.md` and `deploy\README-DEPLOY.md`. |
