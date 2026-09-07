import os
import sys
import tempfile
import unittest
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import create_app
from extensions import db
from models import User


class DeviceLimitApiTests(unittest.TestCase):
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

    def test_second_device_is_rejected_but_same_device_is_allowed(self):
        first = self.app.test_client().post('/api/auth', json=self.credentials, headers={'X-Device-ID': 'device-a'})
        self.assertEqual(first.status_code, 200)

        same = self.app.test_client().post('/api/auth', json=self.credentials, headers={'X-Device-ID': 'device-a'})
        self.assertEqual(same.status_code, 200)

        second = self.app.test_client().post('/api/auth', json=self.credentials, headers={'X-Device-ID': 'device-b'})
        self.assertEqual(second.status_code, 403)
        self.assertEqual(second.get_json()['reason'], 'device_limit')

    def test_web_app_login_rejects_second_device_at_app_login(self):
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
        self.assertEqual(second.status_code, 403)
        self.assertIsNone(second.headers.get('Location'))
        self.assertIn('Limite de dispositivos atingido.', second.get_data(as_text=True))

    def test_web_app_logout_releases_device_for_next_login(self):
        client = self.app.test_client()
        form = client.get('/app/login')
        csrf = re.search(r'name="_csrf" value="([^"]+)"', form.get_data(as_text=True)).group(1)
        first = client.post('/app/login', data={
            'username': self.credentials['username'],
            'password': self.credentials['password'],
            '_csrf': csrf,
        })
        self.assertEqual(first.status_code, 302)

        logout_page = client.get('/app')
        csrf = re.search(r'name="_csrf" value="([^"]+)"', logout_page.get_data(as_text=True)).group(1)
        logout = client.post('/app/logout', data={'_csrf': csrf})
        self.assertEqual(logout.status_code, 302)

        next_client = self.app.test_client()
        form = next_client.get('/app/login')
        csrf = re.search(r'name="_csrf" value="([^"]+)"', form.get_data(as_text=True)).group(1)
        second = next_client.post('/app/login', data={
            'username': self.credentials['username'],
            'password': self.credentials['password'],
            '_csrf': csrf,
        })
        self.assertEqual(second.status_code, 302)


if __name__ == '__main__':
    unittest.main()
