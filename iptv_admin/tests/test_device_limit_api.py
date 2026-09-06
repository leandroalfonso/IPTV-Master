import os
import sys
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()
