"""Batch 3: parents' WhatsApp replies (two-way chat) and fee reminders."""
from datetime import date, timedelta

from test_api import DETAILS, register
from test_batch2 import login, two_branches


def bridge(client, body, token=None):
    import config
    return client.post("/api/whatsapp/incoming", json=body,
                       headers={"X-Bridge-Token": token if token is not None else config.WA_BRIDGE_TOKEN})


def test_incoming_whatsapp_and_reply(client, auth, sent):
    import notify
    two_branches(client, auth)          # Dhanish (CSE, parent +919876543210), Shubham (IT, same parent phone in DETAILS)
    assert bridge(client, {"id": "a1", "phone": "919876543210", "text": "hi"}, token="wrong").status_code == 401
    r = bridge(client, {"id": "x1", "phone": "15550001111", "text": "spam"})
    assert r.json["stored"] is False                                       # unknown number: not kept
    r = bridge(client, {"id": "a1", "phone": "919876543210", "name": "Ravi", "text": "Dhanish is sick today", "kind": "text"})
    assert r.json["stored"] is True
    assert bridge(client, {"id": "a1", "phone": "919876543210", "text": "dup"}).json["stored"] is False
    bridge(client, {"id": "a2", "phone": "919876543210", "text": "", "kind": "photo"})

    chats = client.get("/api/whatsapp/chats", headers=auth).json
    assert chats["unread"] == 2 and len(chats["chats"]) == 1
    c = chats["chats"][0]
    assert c["name"] == "Ravi Kumar" and "parent of" in c["role"] and c["last_text"] == "[photo]"

    r = client.post("/api/whatsapp/chats/919876543210/reply", json={"text": "Get well soon"}, headers=auth)
    assert r.status_code == 200
    notify.process_queue()
    assert sent["whatsapp"] == [("+919876543210", "Get well soon")]
    conv = client.get("/api/whatsapp/chats/919876543210", headers=auth).json
    assert [m["dir"] for m in conv["messages"]] == ["in", "in", "out"]
    assert conv["messages"][-1]["status"] == "sent"
    assert client.get("/api/whatsapp/chats", headers=auth).json["unread"] == 0
    assert client.post("/api/whatsapp/chats/15550001111/reply", json={"text": "x"}, headers=auth).status_code == 404


def test_teacher_sees_only_their_parents_chats(client, auth):
    register(client, auth)                                                   # CSE, +919876543210
    register(client, auth, name="Shubham Sharma", details={**DETAILS, "roll_no": "73", "branch": "IT", "parent_phone": "9123456780"})
    bridge(client, {"id": "c1", "phone": "919876543210", "text": "CSE parent"})
    bridge(client, {"id": "c2", "phone": "919123456780", "text": "IT parent"})
    client.post("/api/users", json={"username": "it@college.edu", "password": "teach-pass-1", "role": "teacher", "branches": ["IT"]}, headers=auth)
    t = login(client, "it@college.edu", "teach-pass-1")
    assert [c["last_text"] for c in client.get("/api/whatsapp/chats", headers=t).json["chats"]] == ["IT parent"]
    assert client.get("/api/whatsapp/chats/919876543210", headers=t).status_code == 404
    assert client.get("/api/fees", headers=t).status_code == 403            # fees are admin only


def test_fees_payments_and_reminders(client, auth, sent):
    import fees
    import notify
    two_branches(client, auth)
    assert fees.inr(120000) == "₹1,20,000" and fees.inr(45000.5) == "₹45,000.50" and fees.inr(999) == "₹999"
    today = date.today()
    r = client.post("/api/fees", json={"title": "Semester 6 tuition", "amount": 45000, "due_date": str(today - timedelta(days=2))}, headers=auth)
    assert r.json["added"] == 2
    assert client.post("/api/fees", json={"title": "Semester 6 tuition", "amount": 45000, "due_date": str(today)}, headers=auth).json["added"] == 0
    client.post("/api/fees", json={"title": "Bus fee", "amount": 6000, "due_date": str(today + timedelta(days=20)), "branch": "IT"}, headers=auth)

    data = client.get("/api/fees", headers=auth).json
    tuition = {f["name"]: f for f in data["fees"] if f["title"] == "Semester 6 tuition"}
    assert {f["status"] for f in tuition.values()} == {"overdue"}
    bus = [f for f in data["fees"] if f["title"] == "Bus fee"]
    assert len(bus) == 1 and bus[0]["status"] == "unpaid"

    r = client.post(f"/api/fees/{tuition['Dhanish Kumar']['id']}/pay", json={"amount": 20000}, headers=auth)
    assert r.json["fee"]["balance"] == 25000 and "₹25,000 still due" in r.json["message"]
    r = client.post(f"/api/fees/{tuition['Shubham Sharma']['id']}/pay", json={"full": True}, headers=auth)
    assert r.json["fee"]["status"] == "paid"
    g = next(x for x in client.get("/api/fees", headers=auth).json["groups"] if x["title"] == "Semester 6 tuition")
    assert (g["total"], g["collected"], g["paid"], g["overdue"]) == (90000, 65000, 1, 1)

    r = client.post("/api/fees/remind", json={"title": "Semester 6 tuition", "channels": ["whatsapp"]}, headers=auth)
    assert r.json["queued"] == 1                                            # Shubham already paid
    notify.process_queue()
    text = sent["whatsapp"][0][1]
    assert "*Fee overdue*" in text and "Amount due: ₹25,000 (paid so far: ₹20,000)" in text and "2 days overdue" in text
    f = next(x for x in client.get("/api/fees", headers=auth).json["fees"] if x["id"] == tuition["Dhanish Kumar"]["id"])
    assert f["reminders_sent"] == 1 and f["last_reminded_at"]

    # automatic reminders: off by default, then on (3 days before, repeat every 7 days)
    assert fees.run_auto_reminders() == 0
    client.post("/api/fees/settings", json={"fee_auto": True, "fee_days_before": 3, "fee_repeat_days": 7, "fee_channels": ["whatsapp"]}, headers=auth)
    assert fees.run_auto_reminders() == 0                                    # Dhanish was just reminded, bus fee is 20 days away
    assert fees.run_auto_reminders(today + timedelta(days=17)) == 2          # bus fee now 3 days away + tuition repeat
    assert client.post(f"/api/fees/{bus[0]['id']}/undo", headers=auth).status_code == 200
    assert client.post("/api/fees/delete-title", json={"title": "Bus fee"}, headers=auth).json["message"].startswith("Removed")
