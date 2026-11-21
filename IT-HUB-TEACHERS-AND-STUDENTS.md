# Aakansha IT Hub: teachers by course, and a student login

Nothing changes on the college side.

## What changed (IT Hub only)
1. **Teachers see only the courses the admin assigned them.** This covers students, the course
   picker, attendance (camera and class photo), the register, reports and tests. A teacher with **no**
   course ticked sees nothing and gets the message *"No course has been assigned to you yet"*. The admin
   assigns courses on **Team** (edit the teacher, tick their courses, save).
2. **The Courses page is for admins only.** Teachers no longer see it in the menu.
3. **New "Student" tab on the IT Hub login page** (`/it-hub`). Students log in with their
   **registration number + full name + their own mobile number**, as saved in "Student's mobile"
   when they were registered. They can see:
   - **Attendance for each course they joined:** percentage, whether they're above the minimum, and recent classes
   - **Test results**
   - **Fees:** paid, balance and due date
   - **Leave:** apply, and see if it was approved

   A student's leave application appears on the **Leave** page for the IT Hub admin and for the
   teachers of that student's courses, and either of them can approve it.

> **Students need a mobile number on their record to log in.** For students registered before
> this update, open **Students > the student > Edit** and fill in **Student's mobile**.

## Where the files go
Copy everything into your AttendAI folder (the one with `backend` and `frontend`) and choose
**Replace the files in the destination**. New file: `backend/tests/test_student_portal.py`.

## How to switch it on (in the VS Code terminal)
1. Stop AttendAI: double-click `deploy\windows\stop-attendai.bat`, or press **Ctrl+C** in the window running `python serve.py`.
2. Copy the files in.
3. Rebuild the screens:
   ```
   cd "C:\Users\KK SING\Desktop\reassigned\smart-attendance\frontend"
   npm run build
   ```
4. Start AttendAI again: `..\deploy\windows\start-attendai.bat`, or `cd ..\backend` then `python serve.py`.

No database changes and no new commands are needed.

## Check
- `python -m pytest -q` in `backend` should say **75 passed**.
- `npx vitest run` in `frontend` should say **6 passed**.
