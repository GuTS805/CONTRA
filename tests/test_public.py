"""Hosted-mode checks: the server behind a TLS proxy with a public hostname."""
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

PUBLIC_HOST = "contra-test.onrender.com"


class PublicModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        # Bind to loopback for the test, but configure everything else as Render would.
        env = {**os.environ, "CONTRA_DB": os.path.join(cls.tmp.name, "public.sqlite3"), "CONTRA_HOST": "127.0.0.1",
               "CONTRA_PUBLIC": "1", "PORT": str(cls.port), "RENDER_EXTERNAL_HOSTNAME": PUBLIC_HOST,
               "CONTRA_LLM": "0", "CONTRA_ENV_FILE": os.devnull}
        env.pop("CONTRA_PORT", None)
        cls.process = subprocess.Popen([sys.executable, "-m", "contra.server"], env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            try:
                if cls.request("GET", "/health")[0] == 200:
                    return
            except OSError:
                time.sleep(.05)
        cls.process.terminate()
        raise RuntimeError("public-mode server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.tmp.cleanup()

    @classmethod
    def request(cls, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=5)
        try:
            base = {"Host": PUBLIC_HOST, "X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.9"}
            connection.request(method, path, body=body, headers={**base, **(headers or {})})
            response = connection.getresponse()
            return response.status, response.getheader("Set-Cookie"), response.getheader("Strict-Transport-Security"), \
                json.loads(response.read() or b"null") if response.getheader("Content-Type", "").startswith("application/json") else None
        finally:
            connection.close()

    def test_public_host_secure_cookie_and_origin(self):
        status, *_ = self.request("GET", "/v1/stocks", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        status, cookie, hsts, user = self.request("POST", "/v1/auth/guest", b"{}", {
            "Content-Type": "application/json", "Origin": "https://" + PUBLIC_HOST})
        self.assertEqual(status, 201)
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertTrue(hsts)
        session = cookie.split(";")[0]
        status, *_ = self.request("GET", "/v1/profiles", headers={"Cookie": session})
        self.assertEqual(status, 200)
        for origin in ("http://" + PUBLIC_HOST, "https://evil.example"):
            with self.subTest(origin=origin):
                status, *_ = self.request("POST", "/v1/analyses", b"{}", {
                    "Content-Type": "application/json", "Origin": origin, "Cookie": session})
                self.assertEqual(status, 403)
        status, *_ = self.request("GET", "/", headers={"Host": PUBLIC_HOST})
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
