"""End-to-end API tests on a throw-away SQLite file (needs fastapi, sqlalchemy, httpx):

    cd backend && python -m unittest discover -s tests -p "test_api*.py" -v
"""
import unittest

import _env  # noqa: F401  (must be first: sets up the test environment)

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Ticket, TicketCall  # noqa: E402
from app.agent import followup  # noqa: E402


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()  # runs lifespan: creates tables + seeds
        from app.rag.semantic.index import semantic_index
        semantic_index.wait_idle(30)  # (no-op unless EMBEDDING_PROVIDER=local)
        r = cls.client.post("/auth/login", json={"username": "superadmin", "password": "Sup3r-Admin-pass"})
        assert r.status_code == 200, r.text
        cls.admin = bearer(r.json()["access_token"])
        r = cls.client.post("/customer-auth/signup", json={
            "username": "ali", "password": "password123", "phone": "01012345678", "name": "Ali"})
        assert r.status_code == 200, r.text
        cls.cust = bearer(r.json()["access_token"])

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    # ---------------------------------------------------------------- basics
    def test_01_health_and_pages(self):
        h = self.client.get("/health").json()
        self.assertEqual(h["status"], "ok")
        self.assertEqual(h["database"], "sqlite")
        self.assertEqual(h["app"], "Call Center Agent")
        for path in ("/", "/index.html", "/admin", "/admin.html"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("Call Center Agent", r.text)
            self.assertNotIn("CallCenter Agent", r.text)

    def test_02_auth_rules(self):
        self.assertEqual(self.client.get("/admin/stats").status_code, 401)
        self.assertEqual(self.client.get("/admin/stats", headers=self.cust).status_code, 401)  # wrong token kind
        self.assertEqual(self.client.post("/tickets/message", json={"problem_text": "x"}).status_code, 401)
        self.assertEqual(self.client.post("/tickets/message", json={"problem_text": "x"},
                                          headers=self.admin).status_code, 401)
        bad = self.client.post("/auth/login", json={"username": "superadmin", "password": "nope"})
        self.assertEqual(bad.status_code, 401)
        dup = self.client.post("/customer-auth/signup", json={
            "username": "ALI", "password": "password123", "phone": "01012345678"})
        self.assertEqual(dup.status_code, 409)
        short = self.client.post("/customer-auth/signup", json={
            "username": "bob", "password": "123", "phone": "01012345678"})
        self.assertEqual(short.status_code, 422)
        ok = self.client.post("/customer-auth/login", json={"username": "Ali", "password": "password123"})
        self.assertEqual(ok.status_code, 200)

    def test_03_login_rate_limit(self):
        for _ in range(5):
            self.client.post("/customer-auth/login", json={"username": "ghost", "password": "wrongwrong"})
        r = self.client.post("/customer-auth/login", json={"username": "ghost", "password": "wrongwrong"})
        self.assertEqual(r.status_code, 429)

    # ---------------------------------------------------------------- portal flow
    def test_10_personas_public(self):
        personas = self.client.get("/personas").json()
        self.assertEqual(len(personas), 4)
        self.assertEqual(sum(1 for p in personas if p["is_default"]), 1)

    def test_11_problem_answered_from_kb(self):
        r = self.client.post("/tickets/message", headers=self.cust,
                             json={"problem_text": "الانترنت عندي بطيء جدا والصفحات بتفتح ببطء"})
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["source"], "kb")
        self.assertEqual(data["status"], "resolved_by_rag")
        self.assertIn("الراوتر", data["answer"])
        self.assertIsNone(data["followup_call_in_seconds"])  # follow-ups disabled in tests
        detail = self.client.get(f"/customer-auth/my/tickets/{data['ticket_id']}", headers=self.cust).json()
        self.assertEqual([m["sender"] for m in detail["messages"]], ["customer", "agent"])
        st = self.client.get(f"/tickets/{data['ticket_id']}/status", headers=self.cust).json()
        self.assertEqual(st["status"], "resolved_by_rag")

    def test_12_unknown_problem_escalates_and_single_word_clarifies(self):
        r = self.client.post("/tickets/message", headers=self.cust,
                             json={"problem_text": "عايز اعرف مواعيد رحلات الطيران لباريس الاسبوع الجاي"}).json()
        self.assertEqual(r["status"], "escalated")
        r2 = self.client.post("/tickets/message", headers=self.cust, json={"problem_text": "مرحبا"}).json()
        self.assertEqual(r2["source"], "clarify")
        self.assertEqual(r2["status"], "open")

    def test_13_tickets_are_private_per_customer(self):
        other = self.client.post("/customer-auth/signup", json={
            "username": "sara", "password": "password123", "phone": "01099999999"}).json()
        mine = self.client.get("/customer-auth/my/tickets", headers=self.cust).json()
        self.assertGreaterEqual(len(mine), 2)
        theirs = self.client.get("/customer-auth/my/tickets", headers=bearer(other["access_token"])).json()
        self.assertEqual(theirs, [])
        r = self.client.get(f"/customer-auth/my/tickets/{mine[0]['id']}", headers=bearer(other["access_token"]))
        self.assertEqual(r.status_code, 404)

    def test_14_voice_and_tts_need_key(self):
        r = self.client.post("/speech/tts", headers=self.cust, json={"text": "مرحبا"})
        self.assertEqual(r.status_code, 503)
        r = self.client.post("/tickets/message/voice", headers=self.cust,
                             files={"audio": ("a.webm", b"123", "audio/webm")})
        self.assertEqual(r.status_code, 503)

    # ---------------------------------------------------------------- admin
    def test_20_stats_metrics_tickets(self):
        s = self.client.get("/admin/stats", headers=self.admin).json()
        self.assertGreaterEqual(s["total"], 3)
        self.assertEqual(s["total"], s["resolved"] + s["escalated"] + s["open"])
        m = self.client.get("/admin/metrics", headers=self.admin).json()
        self.assertEqual(m["total_tickets"], s["total"])
        self.assertIsNotNone(m["escalation_rate"])
        self.assertIsNone(m["fcr_rate"])  # no calls yet -> no fake number
        tickets = self.client.get("/admin/tickets", headers=self.admin).json()
        d = self.client.get(f"/admin/tickets/{tickets[0]['id']}", headers=self.admin).json()
        self.assertIn("messages", d)
        self.assertEqual(self.client.get("/admin/tickets/does-not-exist", headers=self.admin).status_code, 404)

    def test_21_kb_crud_changes_answers(self):
        body = {"product": "تطبيق", "ticket_type": "Technical issue", "subject": "التطبيق يقفل فجأة",
                "description": "تطبيق الخدمة يغلق نفسه بعد فتحه مباشرة",
                "resolution": "حدّث التطبيق لآخر إصدار وامسح الكاش ثم أعد تثبيته.",
                "status": "Closed", "priority": "Medium", "channel": "Chat"}
        created = self.client.post("/admin/kb", headers=self.admin, json=body)
        self.assertEqual(created.status_code, 201, created.text)
        aid = created.json()["id"]
        r = self.client.post("/tickets/message", headers=self.cust,
                             json={"problem_text": "التطبيق بيقفل فجأة بعد ما افتحه"}).json()
        self.assertEqual(r["source"], "kb")
        self.assertIn("حدّث التطبيق", r["answer"])
        body["subject"] = "التطبيق يقفل"
        self.assertEqual(self.client.put(f"/admin/kb/{aid}", headers=self.admin, json=body).status_code, 200)
        self.assertEqual(self.client.delete(f"/admin/kb/{aid}", headers=self.admin).status_code, 200)
        self.assertEqual(self.client.delete(f"/admin/kb/{aid}", headers=self.admin).status_code, 404)
        bad = dict(body, priority="Urgent!")
        self.assertEqual(self.client.post("/admin/kb", headers=self.admin, json=bad).status_code, 422)

    def test_22_customers_admin(self):
        rows = self.client.get("/admin/customers", headers=self.admin).json()
        ali = next(c for c in rows if c["username"] == "ali")
        self.assertGreaterEqual(ali["ticket_count"], 2)
        self.assertEqual(self.client.delete(f"/admin/customers/{ali['id']}", headers=self.admin).status_code, 409)
        sara = next(c for c in rows if c["username"] == "sara")
        r = self.client.put(f"/admin/customers/{sara['id']}/active", headers=self.admin, json={"is_active": False})
        self.assertEqual(r.status_code, 200)
        login = self.client.post("/customer-auth/login", json={"username": "sara", "password": "password123"})
        self.assertEqual(login.status_code, 403)
        self.client.put(f"/admin/customers/{sara['id']}/password", headers=self.admin,
                        json={"new_password": "newpass99"})
        self.client.put(f"/admin/customers/{sara['id']}/active", headers=self.admin, json={"is_active": True})
        login = self.client.post("/customer-auth/login", json={"username": "sara", "password": "newpass99"})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.delete(f"/admin/customers/{sara['id']}", headers=self.admin).status_code, 200)

    def test_23_personas_admin(self):
        personas = self.client.get("/admin/personas", headers=self.admin).json()
        other = next(p for p in personas if not p["is_default"])
        r = self.client.put(f"/admin/personas/{other['id']}", headers=self.admin, json={
            "name": other["name"], "role": other["role"], "description": other["description"],
            "tone_instructions_ar": other["tone_instructions_ar"], "is_default": True})
        self.assertEqual(r.status_code, 200)
        after = self.client.get("/personas").json()
        self.assertEqual([p["id"] for p in after if p["is_default"]], [other["id"]])

    def test_24_staff_roles(self):
        r = self.client.post("/staff", headers=self.admin, json={"username": "agent1", "password": "agentpass1",
                                                                    "role": "agent"})
        self.assertEqual(r.status_code, 201, r.text)
        agent_id = r.json()["id"]
        tok = self.client.post("/auth/login", json={"username": "agent1", "password": "agentpass1"}).json()
        agent = bearer(tok["access_token"])
        self.assertEqual(tok["role"], "agent")
        self.assertEqual(self.client.get("/admin/stats", headers=agent).status_code, 200)
        self.assertEqual(self.client.get("/admin/metrics", headers=agent).status_code, 403)
        self.assertEqual(self.client.get("/staff", headers=agent).status_code, 403)
        self.assertEqual(self.client.post("/admin/reset", headers=agent).status_code, 403)
        self.assertEqual(self.client.put(f"/staff/{agent_id}/role", headers=self.admin,
                                         json={"role": "admin"}).status_code, 200)
        me = self.client.get("/auth/me", headers=self.admin).json()
        self.assertEqual(self.client.delete(f"/staff/{me['id']}", headers=self.admin).status_code, 403)
        self.assertEqual(self.client.delete(f"/staff/{agent_id}", headers=self.admin).status_code, 200)
        # deleted account's token stops working
        self.assertEqual(self.client.get("/admin/stats", headers=agent).status_code, 401)

    # ---------------------------------------------------------------- follow-up call logic (no real calls)
    def test_30_followup_state_machine(self):
        r = self.client.post("/tickets/message", headers=self.cust,
                             json={"problem_text": "الانترنت مقطوع ومؤشر الراوتر احمر"}).json()
        tid = r["ticket_id"]
        with SessionLocal() as db:
            call = TicketCall(ticket_id=tid, attempt=1, status="in_progress", answered=True)
            db.add(call)
            db.commit()
            ncco = followup.handle_input(db, call, "1", 0)
            self.assertEqual(ncco[0]["action"], "talk")
            self.assertEqual(db.get(Ticket, tid).status, "resolved_confirmed")
            self.assertEqual(call.outcome, "resolved_confirmed")

            t2 = db.get(Ticket, tid)
            call2 = TicketCall(ticket_id=t2.id, attempt=1, status="in_progress", answered=True)
            db.add(call2)
            db.commit()
            followup.handle_input(db, call2, "2", 0)
            self.assertEqual(db.get(Ticket, tid).status, "escalated")
            self.assertEqual(call2.outcome, "transferred_to_agent")

        m = self.client.get("/admin/metrics", headers=self.admin).json()
        self.assertEqual(m["fcr_rate"], 50.0)
        self.assertEqual(m["call_reachability_rate"], 100.0)

    def test_31_vonage_webhook_signature(self):
        with SessionLocal() as db:
            tid = db.query(Ticket).first().id
            call = TicketCall(ticket_id=tid, attempt=1, status="in_progress")
            db.add(call)
            db.commit()
            cid = call.id
        bad = self.client.post(f"/vonage/event?call_id={cid}&sig=forged", json={"status": "answered"})
        self.assertEqual(bad.status_code, 403)
        ok = self.client.post(f"/vonage/event?call_id={cid}&sig={followup.call_signature(cid)}",
                              json={"status": "answered"})
        self.assertEqual(ok.status_code, 200)
        r = self.client.post(f"/vonage/input?call_id={cid}&sig={followup.call_signature(cid)}&attempt=0",
                             json={"dtmf": {"digits": "1"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]["action"], "talk")

    def test_32_phone_normalisation(self):
        self.assertEqual(followup.normalize_phone("01012345678"), "201012345678")
        self.assertEqual(followup.normalize_phone("+20 101 234 5678"), "201012345678")
        self.assertEqual(followup.normalize_phone("00201012345678"), "201012345678")

    # ---------------------------------------------------------------- reset (last)
    def test_99_reset(self):
        self.assertEqual(self.client.post("/admin/reset", headers=self.admin).status_code, 200)
        self.assertEqual(self.client.get("/admin/stats", headers=self.admin).json()["total"], 0)
        self.assertEqual(len(self.client.get("/admin/kb", headers=self.admin).json()) > 0, True)  # KB kept
        self.assertEqual(len(self.client.get("/personas").json()), 4)


if __name__ == "__main__":
    unittest.main()
