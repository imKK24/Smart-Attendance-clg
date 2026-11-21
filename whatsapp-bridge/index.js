// ============================================================
//  AttendAI WhatsApp bridge (Baileys = WhatsApp Web over a WebSocket)
//  RUN : npm start          ->  http://127.0.0.1:5100 (only this PC)
//
//  The Flask API sends messages through this small server.
//  First run: open the WhatsApp page in AttendAI and scan the QR code
//  with the school phone (WhatsApp > Linked devices > Link a device).
//
//  NOTE: Baileys is unofficial. WhatsApp may ban numbers that send
//  bulk or spam-like messages. Use a dedicated school number, only
//  message parents who expect it, and keep the delay between messages.
// ============================================================
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import makeWASocket, {
  Browsers, DisconnectReason, fetchLatestBaileysVersion, useMultiFileAuthState,
} from "@whiskeysockets/baileys";
import express from "express";
import pino from "pino";
import QRCode from "qrcode";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");

// Read KEY=value lines from ../.env without another dependency.
function loadEnv(file) {
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
}
loadEnv(path.join(ROOT, ".env"));

const PORT = Number(process.env.WA_BRIDGE_PORT || 5100);
// Where parents' replies are sent (the Flask API).
const API_URL = (process.env.ATTENDAI_API_URL || `http://127.0.0.1:${process.env.PORT || 5000}`).replace(/\/$/, "");
const AUTH_DIR = path.join(HERE, "auth"); // the linked-device login. Keep it private.
const TOKEN_FILE = path.join(ROOT, "backend", "data", "bridge.token");

function readToken() {
  if (process.env.WA_BRIDGE_TOKEN) return process.env.WA_BRIDGE_TOKEN.trim();
  if (fs.existsSync(TOKEN_FILE)) return fs.readFileSync(TOKEN_FILE, "utf8").trim();
  return "";
}

const logger = pino({ level: process.env.WA_LOG_LEVEL || "silent" });
const status = { state: "starting", qr: null, me: null, error: "" };
let sock = null;
let retries = 0;
let reconnectTimer = null;
const lookups = new Map(); // phone digits -> jid or null

function toDigits(phone) {
  return String(phone || "").replace(/\D/g, "");
}

// ---------------- incoming messages -> AttendAI ----------------
// WhatsApp may hide the number behind a private id (...@lid); then the real
// number is in remoteJidAlt. Groups, status updates and our own messages are skipped.
function senderPhone(key) {
  for (const jid of [key.remoteJid, key.remoteJidAlt]) {
    if (jid && jid.endsWith("@s.whatsapp.net")) return toDigits(jid.split("@")[0].split(":")[0]);
  }
  return "";
}

function readText(message) {
  const m = message || {};
  const text = m.conversation || m.extendedTextMessage?.text || m.imageMessage?.caption || m.videoMessage?.caption
    || m.documentMessage?.caption || m.documentWithCaptionMessage?.message?.documentMessage?.caption || "";
  const kind = m.conversation || m.extendedTextMessage ? "text" : m.imageMessage ? "photo" : m.videoMessage ? "video"
    : m.audioMessage ? "voice" : m.documentMessage || m.documentWithCaptionMessage ? "document"
      : m.stickerMessage ? "sticker" : m.locationMessage ? "location" : "other";
  return { text, kind };
}

const outbox = []; // replies waiting to reach the API (it may be restarting)

async function forward(item) {
  try {
    const r = await fetch(`${API_URL}/api/whatsapp/incoming`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Bridge-Token": readToken() },
      body: JSON.stringify(item),
    });
    return r.ok;
  } catch {
    return false;
  }
}

async function flushOutbox() {
  while (outbox.length) {
    if (!(await forward(outbox[0]))) return;
    outbox.shift();
  }
}
setInterval(flushOutbox, 15000);

async function onMessages({ messages, type }) {
  if (type !== "notify") return; // "append" = old history, not new messages
  for (const msg of messages) {
    const key = msg.key || {};
    if (key.fromMe || !msg.message || key.remoteJid?.endsWith("@g.us") || key.remoteJid === "status@broadcast") continue;
    const phone = senderPhone(key);
    if (!phone) continue;
    const { text, kind } = readText(msg.message);
    if (kind === "other" && !text) continue; // reactions, receipts, protocol messages
    outbox.push({ id: key.id, phone, name: msg.pushName || "", text, kind, ts: Number(msg.messageTimestamp) || undefined });
    if (outbox.length > 500) outbox.shift();
  }
  await flushOutbox();
}

async function connect() {
  clearTimeout(reconnectTimer);
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  let version;
  try {
    ({ version } = await fetchLatestBaileysVersion());
  } catch {
    version = undefined; // fall back to the version bundled with Baileys
  }
  status.state = "connecting";
  sock = makeWASocket({
    auth: state,
    version,
    logger,
    browser: Browsers.windows("AttendAI"),
    markOnlineOnConnect: false,
    syncFullHistory: false,
  });
  sock.ev.on("creds.update", saveCreds);
  sock.ev.on("messages.upsert", (u) => onMessages(u).catch((e) => console.error("Incoming message error:", e)));
  sock.ev.on("connection.update", async (u) => {
    if (u.qr) {
      status.state = "qr";
      status.qr = await QRCode.toDataURL(u.qr, { margin: 1, width: 280 });
      console.log("Scan the QR code on the AttendAI WhatsApp page.");
    }
    if (u.connection === "open") {
      retries = 0;
      status.state = "open";
      status.qr = null;
      status.error = "";
      status.me = { id: sock.user?.id?.split(":")[0]?.split("@")[0] || "", name: sock.user?.name || "" };
      console.log("WhatsApp connected as", status.me.id);
    }
    if (u.connection === "close") {
      const code = u.lastDisconnect?.error?.output?.statusCode;
      status.me = null;
      if (code === DisconnectReason.loggedOut) {
        fs.rmSync(AUTH_DIR, { recursive: true, force: true });
        status.state = "logged_out";
        status.error = "This computer was unlinked from WhatsApp. Scan the new QR code.";
        reconnectTimer = setTimeout(connect, 1000);
        return;
      }
      if (code === DisconnectReason.connectionReplaced) {
        status.state = "error";
        status.error = "WhatsApp was opened by another AttendAI bridge. Close the other one, then restart this bridge.";
        return;
      }
      retries += 1;
      status.state = "connecting";
      status.error = code === DisconnectReason.restartRequired ? "" : "Connection dropped. Reconnecting...";
      const wait = code === DisconnectReason.restartRequired ? 500 : Math.min(30000, 2000 * retries);
      reconnectTimer = setTimeout(() => connect().catch(onFatal), wait);
    }
  });
}

function onFatal(err) {
  status.state = "error";
  status.error = String(err?.message || err);
  console.error("WhatsApp bridge error:", err);
  reconnectTimer = setTimeout(() => connect().catch(onFatal), 15000);
}

async function jidFor(phone) {
  const digits = toDigits(phone);
  if (digits.length < 10 || digits.length > 15) throw Object.assign(new Error("Invalid phone number."), { http: 400 });
  if (lookups.has(digits)) return lookups.get(digits);
  const [hit] = (await sock.onWhatsApp(digits)) || [];
  const jid = hit?.exists ? hit.jid : null;
  lookups.set(digits, jid);
  return jid;
}

// ---------------- HTTP API (local only) ----------------
const app = express();
app.use(express.json({ limit: "64kb" }));
app.use((req, res, next) => {
  const token = readToken();
  if (!token || req.get("X-Bridge-Token") !== token) {
    return res.status(401).json({ ok: false, error: "Bad bridge token." });
  }
  return next();
});

app.get("/status", (req, res) => res.json({ ok: true, ...status }));

app.post("/send", async (req, res) => {
  if (status.state !== "open") {
    return res.status(503).json({ ok: false, error: "WhatsApp is not connected. Scan the QR code on the WhatsApp page." });
  }
  const text = String(req.body?.text || "").slice(0, 4000);
  if (!text.trim()) return res.status(400).json({ ok: false, error: "Message is empty." });
  try {
    const jid = await jidFor(req.body?.to);
    if (!jid) return res.status(404).json({ ok: false, error: "This number is not on WhatsApp." });
    const sent = await sock.sendMessage(jid, { text });
    return res.json({ ok: true, id: sent?.key?.id || "" });
  } catch (err) {
    return res.status(err.http || 500).json({ ok: false, error: String(err?.message || err) });
  }
});

app.post("/check", async (req, res) => {
  if (status.state !== "open") return res.status(503).json({ ok: false, error: "WhatsApp is not connected." });
  try {
    return res.json({ ok: true, exists: !!(await jidFor(req.body?.to)) });
  } catch (err) {
    return res.status(err.http || 500).json({ ok: false, error: String(err?.message || err) });
  }
});

app.post("/logout", async (req, res) => {
  try {
    if (sock && status.state === "open") await sock.logout();
  } catch {
    /* already gone */
  }
  fs.rmSync(AUTH_DIR, { recursive: true, force: true });
  lookups.clear();
  status.me = null;
  status.state = "connecting";
  reconnectTimer = setTimeout(() => connect().catch(onFatal), 1000);
  res.json({ ok: true });
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`AttendAI WhatsApp bridge on http://127.0.0.1:${PORT}`);
  if (!readToken()) console.log("Waiting for backend/data/bridge.token. Start the Flask API (python app.py) once.");
  connect().catch(onFatal);
});
