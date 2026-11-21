# Going online: what's in this package

Copy everything into your AttendAI folder, keeping the same folder layout. Replace old files.

**New**
- `deploy/README-DEPLOY.md`: the step-by-step guide. **Start here.**
- `deploy/windows/*.bat / *.ps1`: setup, start/stop, Tailscale address, later Cloudflare, nightly backup, GitHub update
- `.github/workflows/ci.yml`: GitHub tests every change and updates the college PC
- `backend/serve.py`: the production server (Waitress); also serves the built app on port 5000
- `backend/tests/test_deploy.py`

**Changed**
- `backend/app.py`: serves the built app, trusts the tunnel for visitor IPs, security policy for app pages, health check shows your IP
- `backend/config.py`: `FRONTEND_DIST`, `BEHIND_TUNNEL`, `PUBLIC_URL`
- `backend/auth.py`: the first admin can only be created on the PC itself
- `backend/common.py`, `backend/parent.py`: login locks use the real visitor IP
- `backend/requirements.txt`: adds `waitress`
- `frontend/src/api.js`: the built app talks to its own address
- `frontend/src/App.jsx`: waits for the photo pass before showing pages (no failed photo requests)
- `.gitignore`: also keeps logs, backups and restart.flag off GitHub
- `README.md`: new section 8 linking to the guide

**Then:** follow `deploy/README-DEPLOY.md`, parts A to E. Part F is for when you buy a domain.
To work on the code as before: `python app.py` + `npm run dev` still work the same way.
