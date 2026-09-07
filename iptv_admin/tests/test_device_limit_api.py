import os
import sys
import tempfile
import unittest
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from extensions import db
from models import User
from device_policy import can_claim_device


class DeviceLimitDisabledTests(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db_file.close()

        class TestConfig:
            TESTING = True
            SECRET_KEY = 'test-secret'
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{self.db_file.name}"
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            WTF_CSRF_ENABLED = False
            ADMIN_USERNAME = ''
            ADMIN_PASSWORD = ''

        self.app = create_app(TestConfig)
        with self.app.app_context():
            user = User(username='cliente', name='Cliente', active=True, device_limit=1)
            user.set_password('senha-segura')
            user.expires_at = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).replace(microsecond=0)
            user.expires_at += __import__('datetime').timedelta(days=30)
            db.session.add(user)
            db.session.commit()
            self.credentials = {
                'username': 'cliente',
                'password': 'senha-segura',
                'access_token': user.access_token,
            }

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
        os.unlink(self.db_file.name)

    def test_policy_allows_unlimited_devices(self):
        # Device limit is disabled: any device may claim a slot.
        self.assertTrue(can_claim_device(['phone-a'], 'phone-a', 1))
        self.assertTrue(can_claim_device(['phone-a'], 'phone-b', 1))
        self.assertTrue(can_claim_device(['phone-a', 'phone-b'], 'phone-c', 1))

    def test_api_auth_accepts_many_devices(self):
        first = self.app.test_client().post('/api/auth', json=self.credentials, headers={'X-Device-ID': 'device-a'})
        self.assertEqual(first.status_code, 200)
        second = self.app.test_client().post('/api/auth', json=self.credentials, headers={'X-Device-ID': 'device-b'})
        self.assertEqual(second.status_code, 200)
        third = self.app.test_client().post('/api/auth', json=self.credentials, headers={'X-Device-ID': 'device-c'})
        self.assertEqual(third.status_code, 200)

    def test_web_app_login_accepts_second_device_without_limit(self):
        first_client = self.app.test_client()
        first_form = first_client.get('/app/login')
        csrf = re.search(r'name="_csrf" value="([^"]+)"', first_form.get_data(as_text=True)).group(1)
        first = first_client.post('/app/login', data={
            'username': self.credentials['username'],
            'password': self.credentials['password'],
            '_csrf': csrf,
        })
        self.assertEqual(first.status_code, 302)
        self.assertIn('iptv_device_id=', first.headers.get('Set-Cookie', ''))

        second_client = self.app.test_client()
        second_form = second_client.get('/app/login')
        csrf = re.search(r'name="_csrf" value="([^"]+)"', second_form.get_data(as_text=True)).group(1)
        second = second_client.post('/app/login', data={
            'username': self.credentials['username'],
            'password': self.credentials['password'],
            '_csrf': csrf,
        })
        # With the limit removed, the second device logs in successfully (302).
        self.assertEqual(second.status_code, 302)
        self.assertIn('iptv_device_id=', second.headers.get('Set-Cookie', ''))

    def test_web_app_login_rejects_wrong_password(self):
        client = self.app.test_client()
        form = client.get('/app/login')
        csrf = re.search(r'name="_csrf" value="([^"]+)"', form.get_data(as_text=True)).group(1)
        resp = client.post('/app/login', data={
            'username': self.credentials['username'],
            'password': 'senha-errada',
            '_csrf': csrf,
        })
        self.assertEqual(resp.status_code, 401)
        self.assertIn('Usuário ou senha inválidos', resp.get_data(as_text=True))

    def test_web_app_logout_releases_session(self):
        client = self.app.test_client()
        form = client.get('/app/login')
        csrf = re.search(r'name="_csrf" value="([^"]+)"', form.get_data(as_text=True)).group(1)
        client.post('/app/login', data={
            'username': self.credentials['username'],
            'password': self.credentials['password'],
            '_csrf': csrf,
        })
        logout = client.get('/app/logout')
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(logout.headers['Location'], '/app/login')


if __name__ == '__main__':
    unittest.main()
