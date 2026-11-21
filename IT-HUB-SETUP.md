# Aakansha IT Hub: what's new and how to switch it on

AttendAI now holds two organisations:

- **The college**, at `/`, which works exactly as before.
- **Aakansha IT Hub**, at **`/it-hub`**, which has its own login page, its own teal colour and its own data.

## What the IT Hub gets
| | College | Aakansha IT Hub |
|---|---|---|
| Login page | `/` (Admin, Teacher, Parent) | `/it-hub` (Admin, Teacher; **no Parent**) |
| Student grouping | one **branch** | one or more **courses** (e.g. Python + Tally) |
| Attendance | one register per day | **one register per course per day** |
| Dashboard, Register, Students, Take attendance (camera or class photo), Leave, Reports, Fees | ✅ | ✅ (all follow the course picked on the left) |
| Team, Inbox, WhatsApp/email alerts, Exam/test results | ✅ | ✅ (tests and fees per course) |
| Gmail and WhatsApp number | set up here | **uses the college's** (only the college admin changes them) |

The two organisations can't see each other's students, staff, attendance, holidays, tests, fees,
class photos or messages. The same student name, and even the same person, can be registered in both.
Each organisation logs in on its own page: an IT Hub account is refused on the college page, and
the other way round.

## Where the files go
Copy everything into your AttendAI folder, keeping the folder layout, and replace the old files.
- `backend/...` goes into `backend` (new files: `orgs.py`, `tests/test_ithub.py`).
- `frontend/src/...` goes into `frontend/src` (new files: `org.js`, `ithub.css`, `ithub.test.jsx`).
- `README-NEW-EMPLOYEE.md` goes into the main folder.

## How to switch it on (Windows, about 5 minutes)
1. **Stop AttendAI:** double-click `deploy\windows\stop-attendai.bat`. Also close any `python app.py`
   or `npm run dev` windows.
2. **Copy the files in** as described above.
3. **Rebuild the screens.** In Command Prompt:
   ```
   cd "C:\Users\KK SING\Desktop\reassigned\smart-attendance\frontend"
   npm run build
   ```
4. **Create the IT Hub admin.** This also upgrades the database. All existing data stays with the college.
   ```
   cd ..\backend
   venv\Scripts\python.exe manage.py add-ithub-admin
   ```
   It prints `admin@ithub.local` and a **first password**. Write the password down: it's shown only once.
5. **Start AttendAI again:** double-click `deploy\windows\start-attendai.bat`.
6. Open **http://localhost:5000/it-hub**, or your online address with `/it-hub` on the end,
   e.g. `https://laptop-tf66rgp8.tail5b50a8.ts.net/it-hub`. Log in with that account and choose your own password.
7. **First steps in the IT Hub:**
   1. **Students > Course list:** add the courses (Python, Tally Prime, Web design…), then click **Save courses**.
   2. **Team:** add trainers and tick the courses each one teaches.
   3. **Register:** add students and tick the courses each student joined.
   4. Pick a course on the left, then go to **Take attendance**.

If you use the GitHub automatic updates, pushing these files does steps 3 and 5 for you.
Step 4 is still needed once.

## Good to know
- **Only one live camera session at a time.** While the IT Hub is using it, the college sees
  "The camera is being used by Aakansha IT Hub", and the other way round. Class photo attendance
  has no such limit.
- **Absent marks are per course.** Students are marked absent only for courses that held a class that day.
- Both pages can be open in the same browser, in two tabs: each keeps its own login.
- Tests: `python -m pytest -q` in `backend` should say **65 passed**, and `npx vitest run` in `frontend` should say **5 passed**.
