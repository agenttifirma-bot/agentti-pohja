"""Oikea HTTP-kierros paikallista palvelinta vasten (ei ulkoverkkoa)."""
import http.server
import json
import threading
import unittest

from agentti import llm
from test.apu import OK_JSON, llm_vastaus


class Kasittelija(http.server.BaseHTTPRequestHandler):
    nahdyt = []

    def do_POST(self):
        pituus = int(self.headers.get("Content-Length", 0))
        runko = json.loads(self.rfile.read(pituus))
        Kasittelija.nahdyt.append((self.path, self.headers.get("Authorization"), runko))
        if self.path == "/uudelleenohjaus/chat/completions":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/varas")
            self.end_headers()
            return
        if self.path == "/rikki/chat/completions":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ei json")
            return
        if self.path == "/virhe/chat/completions":
            self.send_response(500)
            self.end_headers()
            return
        data = json.dumps(llm_vastaus(OK_JSON)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class HttpTesti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.palvelin = http.server.HTTPServer(("127.0.0.1", 0), Kasittelija)
        cls.osoite = "http://127.0.0.1:%d" % cls.palvelin.server_port
        threading.Thread(target=cls.palvelin.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.palvelin.shutdown()
        cls.palvelin.server_close()

    def setUp(self):
        Kasittelija.nahdyt.clear()

    def test_onnistunut_kierros_lahettaa_bearer_avaimen(self):
        v = llm._http_post(self.osoite + "/v1/chat/completions", "salainen", {"a": 1})
        self.assertEqual(v["choices"][0]["message"]["content"], OK_JSON)
        polku, auth, runko = Kasittelija.nahdyt[0]
        self.assertEqual((polku, auth, runko), ("/v1/chat/completions", "Bearer salainen", {"a": 1}))

    def test_uudelleenohjausta_ei_seurata(self):
        with self.assertRaises(llm.LLMVirhe) as e:
            llm._http_post(self.osoite + "/uudelleenohjaus/chat/completions", "salainen", {})
        self.assertEqual(e.exception.koodi, "llm_http_302")
        self.assertEqual(len(Kasittelija.nahdyt), 1)

    def test_http_500_ja_rikkinainen_json(self):
        with self.assertRaises(llm.LLMVirhe) as e:
            llm._http_post(self.osoite + "/virhe/chat/completions", "k", {})
        self.assertEqual(e.exception.koodi, "llm_http_500")
        with self.assertRaises(llm.LLMVirhe) as e:
            llm._http_post(self.osoite + "/rikki/chat/completions", "k", {})
        self.assertEqual(e.exception.koodi, "llm_vastaus_rakenne")

    def test_yhteys_kiinni(self):
        with self.assertRaises(llm.LLMVirhe) as e:
            llm._http_post("http://127.0.0.1:1/v1/chat/completions", "k", {})
        self.assertIn(e.exception.koodi, ("llm_yhteys",))


if __name__ == "__main__":
    unittest.main()
