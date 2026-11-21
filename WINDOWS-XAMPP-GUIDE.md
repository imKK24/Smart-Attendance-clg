# AttendAI on Windows with XAMPP: faster camera, MySQL, MAC binding, proxy protection

## What's new
1. **Faster camera start.** The face models (~120 MB) now load once when the server starts, not at every **Start attendance**. The camera opens while student faces load, opens faster on Windows (MJPG), and the camera you used last is tried first. The server window prints `Camera ready (x s)` when it's warm.
2. **Smoother picture for remote users.** On the server PC the picture streams as before. Over the internet it now sends one small, always-newest picture at a time, so it may look a little choppy but no longer falls seconds behind.
3. **MySQL / MariaDB (XAMPP) instead of PostgreSQL.** The college and IT Hub databases are still kept separate (`attendai`, `attendai_ithub`).
4. **IP cameras bound to their MAC address.** If the camera's IP changes, it's found again automatically. If another device takes its IP, it's refused.
5. **Proxy protection** (Take attendance → **Proxy protection**, admin only). Each rule is switched on separately and applies to teachers:
   - **Only approved devices:** each teacher's phone or laptop must be approved once.
   - **Only from the college network.**
   - **Only at the college:** uses the phone's GPS location, with a distance you choose.

---

## Step 1: Install XAMPP (once)
1. Download XAMPP for Windows from **apachefriends.org** and install it. Only **MySQL** is needed.
2. Open the **XAMPP Control Panel** and press **Start** next to **MySQL**. It turns green.
3. To start MySQL automatically with Windows: right-click the XAMPP Control Panel → **Run as administrator** → tick the **Svc** box next to MySQL → **Yes**.

## Step 2: Copy the files
Stop AttendAI first: run `deploy\windows\stop-attendai.bat` or close its window.

Copy everything in this zip into the project folder **with the same paths**, and choose **Replace** when Windows asks.

| From the zip | Goes to |
|---|---|
| `backend\*.py`, `backend\requirements.txt` | `smart-attendance\backend\` |
| `backend\tests\*.py` | `smart-attendance\backend\tests\` |
| `frontend\src\...` | `smart-attendance\frontend\src\` (same sub-folders) |
| `deploy\windows\*.ps1` | `smart-attendance\deploy\windows\` |
| `.env.example`, `README.md`, `README-NEW-EMPLOYEE.md` | `smart-attendance\` |

`guard.py`, `ProxyProtection.jsx` and the three test files are new files.

## Step 3: Install the MySQL driver
Open a terminal in `smart-attendance\backend`:
```
venv\Scripts\activate
pip install -r requirements.txt
```

## Step 4: Point AttendAI at MySQL
Open `smart-attendance\.env` in Notepad and change the `DATABASE_URL` line to:
```
DATABASE_URL=mysql+pymysql://root:@localhost:3306/attendai
```
This is XAMPP's default login: user `root`, no password. If you set a MySQL password, put it after `root:`.

## Step 5: Move your existing data (only if you used PostgreSQL before)
PostgreSQL must still be running for this step. Keep `venv` active in `backend` and run (use your real PostgreSQL password):
```
python manage.py copy-from-postgres postgresql://attendai:YOUR_PG_PASSWORD@localhost:5432/attendai
```
It creates both MySQL databases, copies every table for the college and the IT Hub, and prints how many rows it copied. PostgreSQL is not changed, so you can go back if needed. If MySQL already has data, it refuses to copy, so nothing gets mixed up.

Starting fresh instead? Skip this step. The databases are created on the first start; then run `python manage.py create-accounts`.

## Step 6: Rebuild and start
```
cd ..\frontend
npm run build
```
Then start with `deploy\windows\start-attendai.bat`, and press **Ctrl + F5** in the browser.

Check: log in and look at Students, Attendance and the IT Hub courses. You can also look at the tables in **phpMyAdmin** (http://localhost/phpmyadmin).

---

## Using the new features

### Bind an IP camera to its MAC address
Take attendance → **+ Add or test an IP camera** → fill in the form → **Test connection**. The result shows the camera's **MAC address**. Keep **"Bind to this camera's MAC address"** ticked → **Save camera**. The camera list then shows *Bound to MAC xx:xx:…*.

- If the router gives the camera a new IP, AttendAI finds it by its MAC and updates the link by itself.
- If another device takes the camera's address, AttendAI refuses to use it and explains why.
- This only works for cameras on the **same network as the server PC**. MAC addresses don't travel across the internet. Cameras you already added aren't bound: remove them and add them again to bind them.

### Proxy protection (Take attendance → Proxy protection)
- **Only approved devices:** turn it on. The first time a teacher presses Start attendance (or sends a class photo), they're told to ask the admin, and their device appears in the list as **Waiting**, e.g. "Chrome on Android · teacher's email". Press **Approve**. Use the bin icon to take a device away.
  Phones and laptops can't be bound by MAC (browsers never reveal it, and phones change it on every Wi-Fi), so each browser keeps its own secret device key instead. Clearing the browser's data or using another browser means approving again.
- **Only from the college network:** teachers reach AttendAI through the public link, so the server sees the college's internet address. Once, from the **college Wi-Fi**, open the public link as admin → Proxy protection → **"Add the network I'm on now"**. If the college has more than one internet line, add each one.
- **Only at the college (location):** stand at the college with your phone → **Use my location** → set the distance (200 m is a good start) → **Save location** → tick the box. Teachers outside the college network are then asked for their location, and anyone further away is refused with the distance shown. On the college network, no location is asked.

Admins are never blocked, so you can't lock yourself out. A fake-GPS app can still cheat the location rule, which is why it works best together with approved devices.

---

## Troubleshooting
| Message | Fix |
|---|---|
| "Can't reach MySQL. Open the XAMPP Control Panel…" | Start MySQL in XAMPP (Step 1). |
| MySQL won't start in XAMPP (port 3306 busy) | Another MySQL is installed. Stop it in *Services*, or change XAMPP's port and put the same port in `DATABASE_URL`. |
| `No module named pymysql` | Step 3 was skipped. |
| Camera still slow the first time after a restart | Wait until the server window shows `Camera ready`. That's the one-time load. |
| "A different device is now at 192.168.x.x" | The camera was replaced or its IP was taken. Remove the camera and add it again. |
| Teacher: "Location is blocked" | In the phone browser: site settings → Location → Allow. Location only works through the https public link. |

Optional check: in `backend`, run `python -m pytest -q`. It should report **86 passed** (MySQL must be running).

Nightly backups now save `attendai-college-db-….sql` and `attendai-ithub-db-….sql`, made with XAMPP's `mysqldump`.
