# Putting AttendAI online (Windows college PC)

**How it works:** AttendAI keeps running on the college PC, so the webcam, IP
cameras, WhatsApp and all student data stay there. **Tailscale Funnel**
gives the PC a free, fixed `https://` address that teachers and parents can
open from anywhere. You don't need a domain, and you don't change any router
settings. **GitHub** keeps the code, tests every change, and updates the PC
by itself.

```
 Phone / home PC ──https──► Tailscale ──► college PC: AttendAI (localhost:5000)
                                              ├─ PostgreSQL
 GitHub (private repo) ──tests pass──►        ├─ WhatsApp bridge
                         runner on the PC ─►  └─ webcam / IP cameras
```

| Part | What | Time |
|---|---|---|
| A | Prepare the PC | 10 min |
| B | Run setup.bat | 15 min |
| C | Tailscale: the public address | 10 min |
| D | Check it and share the address | 5 min |
| E | GitHub: tests + automatic updates | 30 min |
| F | Later: your own domain with Cloudflare | 30 min |
| G | Everyday running, backups, problems | - |

---

## A. Prepare the PC (once)

1. **Already installed** (from the earlier setup): Python, Node.js, PostgreSQL, and the AttendAI folder.
   Use a short path without spaces, such as `C:\AttendAI`.
2. **First admin:** create your admin account on this PC *before* going online.
   (For safety, the "create first admin" screen only works on the PC itself.)
3. **Power:** keep the PC plugged in. `setup.bat` turns off sleep. Windows updates
   can restart the PC at night. In *Settings > Windows Update > Active hours*, set
   the college hours.
4. **Logging in:** AttendAI starts when you **log in to Windows** (it needs your login to
   use the camera). After a restart, log in once and then lock the screen with
   **Win + L**. AttendAI keeps running while the screen is locked.

## B. Run the setup (once; safe to run again)

1. Open the `deploy\windows` folder and **double-click `setup.bat`**.
2. It will:
   - install the Python and Node packages
   - build the app screens
   - save the online settings in `.env` (`HOST=127.0.0.1`, `BEHIND_TUNNEL=1`)
   - check the database
   - add two tasks to Windows Task Scheduler:
     - **AttendAI**: starts at login, and restarts anything that stops
     - **AttendAI backup**: runs every night at 9 PM
   - start AttendAI
3. When it says **"AttendAI is running: http://localhost:5000"**, open that address
   on the PC. From now on the app **and** the API are both at port 5000.
   (`npm run dev` on port 5173 is only for changing the code.)

## C. Tailscale: the free public address

1. Download Tailscale from https://tailscale.com/download/windows, install it, and **log in**
   (Google, Microsoft or GitHub account). Use an account the college controls, not a
   personal one.
2. Double-click **`deploy\windows\tunnel-tailscale.bat`**.
   - **The first time**, it opens a Tailscale page asking you to *enable HTTPS and Funnel* for
     this PC. Approve it, then run `tunnel-tailscale.bat` again.
   - It prints your address, e.g. **`https://attendai-pc.tail1234.ts.net`**.
     This address stays the same after restarts.
3. The address is saved in `.env` as `PUBLIC_URL`, and AttendAI restarts.

> Note: Tailscale's free plan is meant for non-commercial use. It's fine for the project
> and a trial. For official, long-term college use, move to your own domain (part F).

## D. Check it, then share it

Use a **phone on mobile data**. College Wi-Fi doesn't count, because it's the same network as the PC.

1. Open `https://…ts.net`. You should see the AttendAI login page with a padlock.
2. Open `https://…ts.net/api/health`. It shows `"you": "…"`. That must be **your phone's
   internet IP**, *not* `127.0.0.1`. If it shows 127.0.0.1, see the problems table in part G.
3. Share the address:
   - **Teachers / admins:** log in as usual. Everyone must choose their own password the first time.
   - **Parents:** the **Parent** tab, with the registration number, the student's name and the
     parent's mobile number.

**What works from outside:** everything, including leave, reports, inbox, notify, fees,
the parent portal and **class photo** attendance from a phone. The one exception is
**live webcam attendance**: that camera is the one on the college PC, so it only makes
sense in that classroom.

## E. GitHub: tests on every change + automatic updates

### E1. Put the code on GitHub (private!)

1. Go to https://github.com/new. Choose a name (e.g. `attendai`) and select **Private**. Don't
   tick any "add README / .gitignore" boxes. Then click **Create**.
2. On the PC, open PowerShell in the AttendAI folder:
   ```powershell
   git init
   git add .
   git status          # CHECK: no .env, backend/data, known_faces, class_photos, whatsapp-bridge/auth, backups
   git commit -m "AttendAI"
   git branch -M main
   git remote add origin https://github.com/YOUR-NAME/attendai.git
   git push -u origin main
   ```
   (GitHub Desktop does the same with buttons: *File > Add local repository*.)
   `.gitignore` already keeps out passwords, keys, student photos, the WhatsApp login
   and backups. **Still look at `git status` before the first commit.**
3. On GitHub, open the **Actions** tab. "AttendAI" runs the backend tests (with a real
   PostgreSQL) and the frontend tests + build. A green tick means everything passed.
   The *Update the college PC* step stays **queued** until you finish E2.

### E2. Let the PC update itself

GitHub can't reach into the college PC. Instead, a small GitHub program
(a **self-hosted runner**) on the PC asks GitHub for work. That works through any firewall.

1. On GitHub: **Settings > Actions > Runners > New self-hosted runner > Windows, x64**.
2. In PowerShell, create `C:\actions-runner` and run the **Download** and **Configure**
   commands GitHub shows you. While configuring:
   - *Enter the name of runner group*: press Enter
   - *Enter any additional labels*: type **`attendai`**
   - *Would you like to run the runner as service?*: type **N**. (`start-attendai` will start
     it as you, so it can restart AttendAI.)
3. Tell AttendAI where the runner is, then restart AttendAI:
   ```powershell
   [Environment]::SetEnvironmentVariable("ATTENDAI_RUNNER", "C:\actions-runner", "User")
   ```
   Then double-click `stop-attendai.bat` and then `start-attendai.bat`.
   GitHub's **Runners** page should show the PC as **Idle**.
4. From now on, every `git push` to `main` does this:
   **tests > (all pass) > the PC copies the code in > rebuilds > restarts**, in about 5 minutes.
   If a test fails, the PC is **not** touched. The update never touches `.env`, the
   database, photos, backups or the WhatsApp login.

> **Keep the repository private.** A self-hosted runner runs code from the repository on the
> college PC. Only add collaborators you trust.

## F. Later: your own domain (Cloudflare)

When you buy a domain (e.g. `yourcollege.in`), you can move from Tailscale to Cloudflare.
You'll get an address like `https://attendance.yourcollege.in`. Nothing else in AttendAI changes.

1. Create a free account at https://dash.cloudflare.com and choose **Add a domain**. Pick the **Free** plan.
   Change the domain's nameservers at the place you bought it to the two Cloudflare gives you.
2. In **Zero Trust > Networks > Tunnels > Create a tunnel > Cloudflared**, name it `attendai`.
   Copy the **token**: the long text after `service install` in the command shown.
3. Add a **Public hostname**: subdomain `attendance`, your domain, service **HTTP** `localhost:5000`.
4. On the PC, open PowerShell **as administrator** in `deploy\windows`:
   ```powershell
   .\tunnel-cloudflare.bat -Token PASTE-TOKEN-HERE -Url https://attendance.yourcollege.in
   ```
   This installs Cloudflare's connector as a Windows service, switches off the Tailscale
   address, saves the new `PUBLIC_URL` and restarts AttendAI.
5. Check again as in part D, then tell everyone the new address.

(Cloudflare sometimes renames its menus. Look for "Tunnels" and "Public hostname".)

## G. Everyday running

| I want to… | Do this |
|---|---|
| Open AttendAI on the PC | http://localhost:5000 |
| Stop / start it | `deploy\windows\stop-attendai.bat` / `start-attendai.bat` |
| See what went wrong | the `logs` folder: `backend.err.log`, `whatsapp.err.log`, `supervisor.log` |
| Back up now | `deploy\windows\backup.bat` (it also runs every night at 9 PM) |
| Keep backups safe | copy the `backups` folder to a pen drive or another PC each week, or set `ATTENDAI_BACKUP_DIR=D:\AttendAI-backups` in `.env` |

**Restoring from a backup**, for example after a dead disk on a new PC (after setup.bat):
```powershell
& "C:\Program Files\PostgreSQL\16\bin\pg_restore.exe" -h localhost -U attendai -d attendai --clean --if-exists backups\attendai-db-2026-11-17_2100.dump
Expand-Archive backups\attendai-files-2026-11-17_2100.zip -DestinationPath backend -Force
```
Change the date to the backup you want, and `16` to your PostgreSQL version.

### Problems

| Problem | Fix |
|---|---|
| Phone can't open the address | Is the PC on, logged in and not asleep? Does http://localhost:5000 work on the PC? Run `tunnel-tailscale.bat` again. |
| `/api/health` shows `"you": "127.0.0.1"` | Check `.env` has `BEHIND_TUNNEL=1` and `HOST=127.0.0.1`, then stop and start AttendAI. |
| "Can't reach the server" banner | Look at `logs\backend.err.log`. Usually PostgreSQL isn't running: *Services > postgresql > Start*. |
| GitHub update is stuck on *queued* | The runner isn't running: check `ATTENDAI_RUNNER` (part E2), then stop and start AttendAI. |
| GitHub update failed | Open the run in the Actions tab. The red step shows the message. The PC keeps the old version running. |
| Too many wrong logins | Wait: the lock is 1 minute, doubling up to 15. An admin can reset a teacher's password on the Team page. |

### Security checklist before giving parents the address
- [ ] Every account has its own password (the app forces this at first login).
- [ ] `git status` shows no secrets or photos before every push, and the repository is **private**.
- [ ] Windows Update is on, and the PC has a Windows password.
- [ ] Backups are being copied off the PC.
- [ ] Only people who need it know the Tailscale / Cloudflare account login.
