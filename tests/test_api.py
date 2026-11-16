"""Exercise real HTTP, cookies and SQLite against an isolated temporary database."""
import http.cookiejar
import json
import os
import re
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import server


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ""

    def request(self, path, method="GET", data=None, headers=None):
        headers = {"Content-Type": "application/json", "X-CSRF-Token": self.csrf, **(headers or {})}
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + "/api" + path, data=body, method=method, headers=headers)
        try:
            response = self.opener.open(req, timeout=5)
            return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def login_link(self, token):
        result = self.request("/auth/link", "POST", {"token": token})
        if result[0] == 200:
            self.csrf = self.request("/bootstrap")[1]["user"]["csrf"]
        return result

    def login_admin(self):
        result = self.request("/auth/admin", "POST", {"id": "teacher", "password": "teacher123"})
        self.csrf = self.request("/bootstrap")[1]["user"]["csrf"]
        return result


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path_patch = patch.object(server, "DB_PATH", Path(cls.temp.name) / "test.sqlite3")
        cls.path_patch.start()
        cls.env_patch = patch.dict(os.environ, {"INTEGRATION_TOKEN": "a" * 40, "ADMIN_PASSWORD": "teacher123"})
        cls.env_patch.start()
        cls.demo_patch = patch.object(server, "DEMO", True)
        cls.demo_patch.start()
        server.initialize()
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        cls.demo_patch.stop()
        cls.env_patch.stop()
        cls.path_patch.stop()
        cls.temp.cleanup()

    def setUp(self):
        server.RATE.clear()
        self.client = Client(self.base)
        with server.database() as db:
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM mail")
            db.execute("DELETE FROM challenges")
            db.execute("DELETE FROM card_events")
            db.execute("DELETE FROM warnings")
            db.execute("DELETE FROM records WHERE lesson_id IN (SELECT id FROM lessons WHERE day>=?)", (server.now().date().isoformat(),))
            self.lesson = server.one(db, "SELECT * FROM lessons WHERE day=? ORDER BY first_start LIMIT 1", (server.now().date().isoformat(),))

    def swipe(self, sid="24C1001", mode="entry", clock="09:05:00", event_id=None):
        body = {"event_id": event_id or f"test-{time.time_ns()}", "student_id": sid, "lesson_id": self.lesson["id"],
                "mode": mode, "occurred_at": self.lesson["day"] + "T" + clock + "+09:00"}
        return self.client.request("/integrations/card-events", "POST", body, {"Authorization": "Bearer " + "a" * 40})

    def code_for(self, sid):
        with server.database() as db:
            message = server.one(db, "SELECT body FROM mail WHERE student_id=? AND kind='login' ORDER BY id DESC LIMIT 1", (sid,))
        return re.search(r"#login=([\w-]{43})", message["body"]).group(1)

    def test_full_student_flow_uses_card_time_and_only_own_data(self):
        self.assertEqual(self.swipe()[0], 200)
        self.assertEqual(self.swipe("24C1002", clock="09:00:00")[0], 200)
        code = self.code_for("24C1001")
        self.assertEqual(self.client.login_link(code)[0], 200)
        data = self.client.request("/student/data?student_id=24C1002")[1]
        self.assertEqual({r["student_id"] for r in data["records"]}, {"24C1001"})
        self.assertEqual({m["student_id"] for m in data["mail"]}, {"24C1001"})
        self.assertEqual(self.client.request("/admin/data")[0], 403)
        self.assertEqual(self.client.request("/student/confirm", "POST", {"student_id": "24C1002"})[0], 200)
        data = self.client.request("/student/data")[1]
        record = next(r for r in data["records"] if r["lesson_id"] == self.lesson["id"])
        self.assertEqual((record["first_status"], record["second_status"]), ("late", "present"))
        self.assertIn("09:05:00", record["entry_at"])
        self.assertTrue(record["confirmed"])
        notices = [m for m in data["mail"] if m["kind"] == "confirmation"]
        self.assertEqual(len(notices), 1)
        self.client.request("/student/confirm", "POST", {})
        self.assertEqual(len([m for m in self.client.request("/student/data")[1]["mail"] if m["kind"] == "confirmation"]), 1)
        self.assertEqual(Client(self.base).login_link(code)[0], 401)

    def test_link_expiry_and_rate_limit(self):
        self.swipe()
        token = self.code_for("24C1001")
        with server.database() as db:
            db.execute("UPDATE challenges SET expires_at=?", (time.time()-1,))
        self.assertEqual(self.client.login_link(token)[0], 401)
        for _ in range(server.LINK_FAILURES - 1):  # the expired link above was already failure number one
            self.assertEqual(self.client.login_link("A" * 43)[0], 401)
        self.assertEqual(self.client.login_link("A" * 43)[0], 429)

    def test_link_is_long_random_lives_ten_minutes_and_logins_do_not_count_toward_limit(self):
        self.swipe()
        token = self.code_for("24C1001")
        self.assertEqual(len(token), 43)
        with server.database() as db:
            life = db.execute("SELECT expires_at-? FROM challenges", (time.time(),)).fetchone()[0]
        self.assertTrue(550 < life <= 600, life)
        for _ in range(server.LINK_FAILURES + 5):  # many students log in from the one reader PC
            self.swipe()
            self.assertEqual(Client(self.base).login_link(self.code_for("24C1001"))[0], 200)

    def test_login_only_from_school_network(self):
        self.swipe()
        token = self.code_for("24C1001")
        with patch.dict(os.environ, {"ALLOWED_NETWORKS": "10.0.0.0/8, 192.168.0.0/16"}):
            result = self.client.login_link(token)
            self.assertEqual(result[0], 403)
        with patch.dict(os.environ, {"ALLOWED_NETWORKS": "10.0.0.0/8, 127.0.0.0/8"}):
            self.assertEqual(self.client.login_link(token)[0], 200)  # the refused try did not use the link up
            self.assertEqual(self.client.request("/student/data")[0], 200)
        with patch.dict(os.environ, {"ALLOWED_NETWORKS": "10.0.0.0/8"}):  # an existing session also stops working off-network
            self.assertEqual(self.client.request("/student/data")[0], 403)

    def test_repeat_entry_reissues_link_without_rewriting_card_time(self):
        self.assertEqual(self.swipe(clock="09:00:00")[0], 200)
        first = self.code_for("24C1001")
        self.assertEqual(self.swipe(clock="10:00:00")[0], 200)
        second = self.code_for("24C1001")
        self.assertNotEqual(first, second)
        self.assertEqual(self.client.login_link(first)[0], 401)
        self.assertEqual(self.client.login_link(second)[0], 200)
        self.client.request("/student/confirm", "POST", {})  # unconfirmed scans turn absent once the lesson is over
        data = self.client.request("/student/data")[1]
        record = next(r for r in data["records"] if r["lesson_id"] == self.lesson["id"])
        self.assertIn("09:00:00", record["entry_at"])
        self.assertEqual((record["first_status"], record["second_status"]), ("present", "present"))

    def test_unauthorized_and_csrf(self):
        self.assertEqual(self.client.request("/student/data")[0], 401)
        self.assertEqual(self.client.request("/admin/data")[0], 401)
        self.client.login_admin()
        self.assertEqual(self.client.request("/admin/admins", "POST", {}, {"X-CSRF-Token": "invalid"})[0], 403)
        self.assertEqual(self.client.request("/auth/logout", "POST", {}, {"Origin": "https://attacker.invalid"})[0], 400)
        self.assertEqual(self.client.request("/integrations/card-events", "POST", {})[0], 401)

    def test_exit_needs_login_and_submission_then_correction_notifies_only_affected_student(self):
        self.swipe(clock="08:55:00")
        self.assertEqual(self.swipe(mode="exit", clock="10:15:00")[0], 400)  # entry not yet confirmed
        student = Client(self.base)
        student.login_link(self.code_for("24C1001"))
        student.request("/student/confirm", "POST", {})
        self.assertEqual(self.swipe(mode="exit", clock="10:15:00")[0], 200)
        record = next(r for r in student.request("/student/data")[1]["records"] if r["lesson_id"] == self.lesson["id"])
        self.assertEqual((record["first_status"], record["second_status"], record["exit_at"]), ("present", "present", None))
        self.assertEqual(student.request("/student/submit-exit", "POST", {})[0], 400)  # entry login cannot submit an exit
        leaver = Client(self.base)
        self.assertEqual(leaver.login_link(self.code_for("24C1001"))[0], 200)
        self.assertEqual(leaver.request("/student/confirm", "POST", {})[0], 400)  # exit login cannot re-confirm entry
        self.assertEqual(leaver.request("/student/submit-exit", "POST", {})[0], 200)
        record = next(r for r in student.request("/student/data")[1]["records"] if r["lesson_id"] == self.lesson["id"])
        self.assertEqual((record["first_status"], record["second_status"]), ("present", "early"))
        self.client.login_admin()
        body = {"student_id": "24C1001", "lesson_id": self.lesson["id"], "first_status": "excused", "second_status": "excused", "reason": "公欠届を確認"}
        self.assertEqual(self.client.request("/admin/records", "PUT", body)[0], 200)
        data = student.request("/student/data")[1]
        message = next(m for m in data["mail"] if m["kind"] == "correction")
        self.assertIn("1コマ目：公欠", message["body"])
        self.assertEqual(message["recipient"], "hana.sato@example.edu")
        with server.database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM mail WHERE student_id='24C1002' AND kind IN ('exit','correction')").fetchone()[0], 0)

    def test_usage_log_lists_scan_login_and_confirmation(self):
        self.swipe()
        self.client.login_link(self.code_for("24C1001"))
        self.client.request("/student/confirm", "POST", {})
        actions = [u["action"] for u in self.client.request("/student/data")[1]["usage"]]
        for expected in ("カード読取（入室）", "ログイン", "出席手続き"):
            self.assertIn(expected, actions)

    def test_confirmation_history_includes_skipped_lessons_of_that_course_only(self):
        with server.database() as db:
            skipped = server.one(db, "SELECT l.* FROM lessons l WHERE l.course_id=? AND l.day<? ORDER BY l.day LIMIT 1", (self.lesson["course_id"], self.lesson["day"]))
            db.execute("DELETE FROM records WHERE student_id='24C1001' AND lesson_id=?", (skipped["id"],))
        self.swipe()
        self.client.login_link(self.code_for("24C1001"))
        self.client.request("/student/confirm", "POST", {})
        body = next(m for m in self.client.request("/student/data")[1]["mail"] if m["kind"] == "confirmation")["body"]
        self.assertIn(f"{skipped['day']}  1コマ目：欠席 / 2コマ目：欠席", body)
        for other in ("データベース", "情報ネットワーク"):
            self.assertNotIn(other, body)

    def test_warning_mail_when_absences_near_limit(self):
        cid = self.lesson["course_id"]
        with server.database() as db:
            db.execute("INSERT OR IGNORE INTO records(student_id,lesson_id,first_auto,second_auto,confirmed,updated_at) SELECT '24C1001',id,'present','present',1,? FROM lessons WHERE course_id=? AND day<?", (server.stamp(), cid, self.lesson["day"]))
            db.execute("UPDATE records SET first_auto='present',second_auto='present',first_override=NULL,second_override=NULL WHERE student_id='24C1001' AND lesson_id IN (SELECT id FROM lessons WHERE course_id=?)", (cid,))
            ids = [r["id"] for r in db.execute("SELECT r.id FROM records r JOIN lessons l ON l.id=r.lesson_id WHERE r.student_id='24C1001' AND l.course_id=? AND l.day<? ORDER BY l.day LIMIT 3", (cid, self.lesson["day"]))]
            db.executemany("UPDATE records SET first_auto='absent',second_auto='absent' WHERE id=?", [(i,) for i in ids])
        self.swipe(clock="12:00:00")  # absent for both periods: 6 + 2 of a 9-period limit
        self.client.login_link(self.code_for("24C1001"))
        self.client.request("/student/confirm", "POST", {})
        self.client.request("/student/confirm", "POST", {})
        warnings = [m for m in self.client.request("/student/data")[1]["mail"] if m["kind"] == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("あと 1 コマ", warnings[0]["body"])
        self.assertIn("欠席：8 コマ / 上限：9 コマ", warnings[0]["body"])

    def test_student_login_ends_before_the_lesson_does(self):
        if server.now().hour >= 23:
            self.skipTest("lesson end would cross midnight")
        end = (server.now() + timedelta(minutes=40)).strftime("%H:%M")
        with server.database() as db:
            original = self.lesson["second_end"]
            db.execute("UPDATE lessons SET second_end=? WHERE id=?", (end, self.lesson["id"]))
        try:
            self.swipe()
            self.assertEqual(self.client.login_link(self.code_for("24C1001"))[0], 200)
            left = self.client.request("/bootstrap")[1]["user"]["expires_at"] - time.time()
            self.assertTrue(1300 < left < 1600, left)  # 40 minutes to the end, minus 15 (and the dropped seconds)
        finally:
            with server.database() as db:
                db.execute("UPDATE lessons SET second_end=? WHERE id=?", (original, self.lesson["id"]))

    def test_card_mapping_replay_and_rollback(self):
        payload = {"event_id": "external-001", "card_id": "CARD-003", "lesson_id": self.lesson["id"], "mode": "entry",
                   "occurred_at": self.lesson["day"]+"T09:00:00+09:00"}
        headers = {"Authorization": "Bearer " + "a" * 40}
        first = self.client.request("/integrations/card-events", "POST", payload, headers)
        second = self.client.request("/integrations/card-events", "POST", payload, headers)
        self.assertEqual(first, second)
        self.assertNotIn("token", json.dumps(first[1]))
        self.assertEqual(self.client.login_link(self.code_for("24C1003"))[0], 200)
        self.assertEqual(self.client.request("/bootstrap")[1]["user"]["id"], "24C1003")
        bad = {**payload, "event_id": "external-002", "card_id": "CARD-004", "occurred_at": "not a time"}
        self.assertEqual(self.client.request("/integrations/card-events", "POST", bad, headers)[0], 400)
        self.assertEqual(self.swipe("24C1004")[0], 200)  # the failed event must not leave a partial entry

    def test_administrator_and_year_setup_crud(self):
        self.client.login_admin()
        student = {"id": "TEST001", "name": "テスト 学生", "email": "test@example.edu", "card_id": "TEST-CARD", "year": 2027, "course_ids": [1]}
        self.assertEqual(self.client.request("/admin/students", "POST", student)[0], 200)
        student["email"] = "updated@example.edu"
        self.assertEqual(self.client.request("/admin/students", "PUT", student)[0], 200)
        course = {"name": "テスト科目", "code": "TEST101", "teacher": "テスト教員", "room": "C101", "year": 2027,
                  "start_date": "2027-04-01", "weeks": 15, "first_start": "09:00", "first_end": "09:45", "second_start": "09:45", "second_end": "10:30", "student_ids": ["TEST001"]}
        self.assertEqual(self.client.request("/admin/courses", "POST", course)[0], 200)
        data = self.client.request("/admin/data")[1]
        cid = next(c["id"] for c in data["courses"] if c["code"] == "TEST101")
        self.assertEqual(len([l for l in data["lessons"] if l["course_id"] == cid]), 15)
        self.assertEqual(self.client.request("/admin/enrollments", "PUT", {"course_id": cid, "student_ids": ["TEST001", "24C1001"]})[0], 200)
        self.assertEqual(self.client.request("/admin/admins", "POST", {"id": "test-teacher", "name": "テスト教員", "password": "long-test-password"})[0], 200)
        self.assertEqual(self.client.request("/admin/admins", "DELETE", {"id": "teacher"})[0], 400)
        self.assertEqual(self.client.request("/admin/admins", "DELETE", {"id": "test-teacher"})[0], 200)
        self.assertEqual(self.client.request("/admin/students", "DELETE", {"id": "TEST001"})[0], 200)
        self.assertNotIn("TEST001", [s["id"] for s in self.client.request("/admin/data")[1]["students"]])

    def test_production_hides_demo_endpoints(self):
        with patch.object(server, "DEMO", False):
            self.assertEqual(self.client.request("/demo/data")[0], 404)
            self.assertEqual(self.client.request("/demo/event", "POST", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
