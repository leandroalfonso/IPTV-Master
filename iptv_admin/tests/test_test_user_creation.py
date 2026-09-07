import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import create_app
from extensions import db
from models import Admin, User


class TestUserCreationTests(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(prefix="iptv-test-user-", suffix=".sqlite3", delete=False)
        self.db_file.close()

        class TestConfig:
            TESTING = True
            SECRET_KEY = "test-only"
            SQLALCHEMY_DATABASE_URI = "sqlite:///" + self.db_file.name
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            ADMIN_USERNAME = "admin-test"
            ADMIN_PASSWORD = "admin-password"

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
        os.unlink(self.db_file.name)

    def test_creates_random_test_user_for_eight_hours_and_one_device(self):
        login_page = self.client.get("/login")
        csrf = re.search(r'name="_csrf" value="([^"]+)"', login_page.get_data(as_text=True)).group(1)
        login = self.client.post(
            "/login",
            data={"username": "admin-test", "password": "admin-password", "_csrf": csrf},
        )
        self.assertEqual(login.status_code, 302)

        csrf = self.client.get("/admin/dashboard").get_data(as_text=True)
        csrf = re.search(r'name="_csrf" value="([^"]+)"', csrf)
        if csrf:
            csrf = csrf.group(1)
        else:
            csrf = self.client.get("/login").get_data(as_text=True)
            csrf = re.search(r'name="_csrf" value="([^"]+)"', csrf).group(1)

        response = self.client.post("/admin/usuarios/teste", data={"_csrf": csrf}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        password_match = re.search(r"Senha: ([A-Za-z0-9_-]+)", response.get_data(as_text=True))
        self.assertIsNotNone(password_match)

        with self.app.app_context():
            user = User.query.one()
            self.assertTrue(user.username.startswith("teste-"))
            self.assertEqual(user.name, "Usuário teste")
            self.assertEqual(user.device_limit, 99)
            self.assertTrue(user.active)
            remaining_hours = (user.expires_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds() / 3600
            self.assertGreater(remaining_hours, 7.9)
            self.assertLess(remaining_hours, 8.1)
            self.assertTrue(user.check_password(password_match.group(1)))
