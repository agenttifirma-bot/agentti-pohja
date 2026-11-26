"""Selaimen yhteys katkeaa pitkan vastauksen aikana (BrokenPipe tailscale serven aikarajassa, 26.11.2026).

Vastaus pitaa olla tallessa keskustelussa, vastauslukon vapaana ja seuraavan viestin toimia. Katkos kirjataan
yhdella journal-rivilla ilman tracebackia. Selain hakee vastauksen reitilta /api/viimeisin."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import socket
import struct
import threading
import time
import unittest

from aivo import chat
from aivo.test_yksityinen_hyvaksynta import LOOP, Pohja


class KatkosTesti(Pohja):
    def setUp(self):
        super().setUp()
        self.portti = threading.Event()
        self.alkoi = threading.Event()

        def hidas(*a, **kw):
            self.alkoi.set()
            self.assertTrue(self.portti.wait(10))
            return "pitk\u00e4 vastaus"
        self.tila.kysy_yks = hidas
        self.tila.kysy = hidas

    def katkaise_kesken(self, kid, teksti):
        """Lahettaa /api/viesti-pyynnon ja katkaisee yhteyden (RST), kun vastaus on viela tekeilla."""
        runko = json.dumps({"keskustelu": kid, "teksti": teksti}).encode("utf-8")
        s = socket.create_connection((LOOP, self.srv.server_address[1]), timeout=10)
        s.sendall(b"POST /api/viesti HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n"
                  b"X-Aivo: 1\r\nCookie: " + self.ev.encode() + b"\r\nContent-Length: "
                  + str(len(runko)).encode() + b"\r\n\r\n" + runko)
        self.assertTrue(self.alkoi.wait(10))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))   # RST kuten katkaistu valityspalvelin
        s.close()
        time.sleep(0.2)

    def odota_vapaa(self, lukko):
        raja = time.monotonic() + 10
        while lukko.locked() and time.monotonic() < raja:
            time.sleep(0.02)
        self.assertFalse(lukko.locked(), "vastauslukko jai varatuksi katkoksen jalkeen")

    def aja_katkos(self, tila_nimi, lukko_nimi, ks):
        kid = self.uusi(tila_nimi)
        virheet = io.StringIO()
        with contextlib.redirect_stderr(virheet):
            self.katkaise_kesken(kid, "pitk\u00e4 kysymys")
            s, d = self.pyynto("GET", "/api/viimeisin?keskustelu=" + kid)
            self.assertEqual(s, 200)
            self.assertTrue(d["kesken"])
            self.assertIsNone(d["vastaus"])
            self.portti.set()
            self.odota_vapaa(getattr(self.tila, lukko_nimi))
            time.sleep(0.1)
        loki = virheet.getvalue()
        self.assertNotIn("Traceback", loki)
        self.assertIn("aivo-chat: yhteys katkesi ennen vastausta (POST '/api/viesti', tila 200,", loki)
        self.assertNotIn("pitk", loki)                            # ei viestien sisaltoa lokiin (myos ascii()-muodossa)
        historia = ks.lue(kid)
        self.assertEqual([v["rooli"] for v in historia], ["tony", "aivo"])
        self.assertEqual(historia[1]["teksti"], "pitk\u00e4 vastaus")
        s, d = self.pyynto("GET", "/api/viimeisin?keskustelu=" + kid)
        self.assertEqual(s, 200)
        self.assertFalse(d["kesken"])
        self.assertEqual(d["tony"], {"indeksi": 0, "teksti": "pitk\u00e4 kysymys"})
        self.assertEqual(d["vastaus"]["indeksi"], 1)
        self.assertEqual(d["vastaus"]["teksti"], "pitk\u00e4 vastaus")
        self.assertEqual(d["pituus"], 2)
        s, d = self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "seuraava"})   # ei 429
        self.assertEqual(s, 200, d)
        self.assertEqual(d["vastaus"], "pitk\u00e4 vastaus")

    def test_yksityinen_katkos_vastaus_tallessa_lukko_vapaa(self):
        self.aja_katkos("yksityinen", "yks_vastauslukko", self.tila.yks)

    def test_tyokalu_katkos_vastaus_tallessa_lukko_vapaa(self):
        self.aja_katkos("tyokalu", "vastauslukko", self.tila.keskustelut)


class ViimeisinTesti(Pohja):
    def test_tyhja_keskustelu(self):
        kid = self.uusi()
        s, d = self.pyynto("GET", "/api/viimeisin?keskustelu=" + kid)
        self.assertEqual((s, d), (200, {"pituus": 0, "kesken": False, "tony": None, "vastaus": None}))

    def test_taustaviesti_ei_ole_vastaus(self):
        kid = self.uusi()
        self.tila.yks.lisaa(kid, "tony", "kysymys")
        self.tila.yks.lisaa(kid, "aivo", "taustan tulos", lisatiedot={"tausta": "syvenna"})
        s, d = self.pyynto("GET", "/api/viimeisin?keskustelu=" + kid)
        self.assertEqual(s, 200)
        self.assertIsNone(d["vastaus"])
        self.tila.yks.lisaa(kid, "aivo", "oikea vastaus", malli="m1")
        s, d = self.pyynto("GET", "/api/viimeisin?keskustelu=" + kid)
        self.assertEqual(d["vastaus"], {"indeksi": 2, "teksti": "oikea vastaus", "malli": "m1"})

    def test_vain_viimeisin_tonyn_viesti(self):
        kid = self.uusi()
        self.assertEqual(self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "eka"})[0], 200)
        self.tila.yks.lisaa(kid, "tony", "toka")             # esim. 502: Tonyn viesti ilman vastausta
        s, d = self.pyynto("GET", "/api/viimeisin?keskustelu=" + kid)
        self.assertEqual(d["tony"], {"indeksi": 2, "teksti": "toka"})
        self.assertIsNone(d["vastaus"])                     # vanhaa vastausta ei anneta uudelle viestille

    def test_virheellinen_ja_kirjautumaton(self):
        self.assertEqual(self.pyynto("GET", "/api/viimeisin?keskustelu=..%2Fx")[0], 400)
        self.assertEqual(self.pyynto("GET", "/api/viimeisin?keskustelu=x", ev=False)[0], 401)
        self.assertEqual(self.pyynto("GET", "/api/viimeisin?keskustelu=x", otsake=False)[0], 403)


class SelainRakenneTesti(unittest.TestCase):
    """Selain: yli 45 s tai katkennut POST -> 'Aivo vastaa viela...' ja uudelleenhaku keskustelusta."""

    def setUp(self):
        h = chat.HTML
        self.laheta = h[h.index("async function laheta(s){"):h.index("document.getElementById('lomake').onsubmit")]
        self.seuraa = h[h.index("async function seuraa("):h.index("function naytaHaettu(")]
        self.h = h

    def test_aikaraja_ja_teksti(self):
        self.assertIn("ODOTUS_MS=45000", self.h)
        self.assertIn("VIELA='Aivo vastaa viel\u00e4\u2026'", self.h)
        self.assertIn("setTimeout(()=>{if(ohjaus.valmis)return;odota.textContent=VIELA;", self.laheta)

    def test_katkos_kaynnistaa_uudelleenhaun(self):
        self.assertIn("signal:ac.signal", self.laheta)
        self.assertIn("catch(x){r=null;}", self.laheta)
        self.assertIn("naytaHaettu(odota,oma,s,await (haku||seuraa(k,s,alku,ohjaus,ac)))", self.laheta)

    def test_uudelleenhaku_lukee_tilareittia_ja_vertaa_omaan_viestiin(self):
        self.assertIn("'/api/viimeisin?keskustelu='", self.h)
        self.assertIn("j.tony.indeksi>=alku&&j.tony.teksti===s.trim()", self.seuraa)
        self.assertIn("await nuku(KYSELY_MS)", self.seuraa)
        self.assertIn("Date.now()<raja", self.seuraa)          # kysely loppuu ylarajaan

    def test_lahetys_pysyy_lukittuna_haun_ajan(self):
        # lahetyksessa vapautuu vasta finallyssa, kun haku on valmis: Tony ei saa 429:aa kesken haun
        self.assertLess(self.laheta.index("await (haku||seuraa("), self.laheta.index("finally{lahetyksessa=false;"))

    def test_tuntematon_alku_kehottaa_lataamaan_sivun(self):
        self.assertIn("alku<0&&j.tony&&j.tony.teksti===s.trim()?'tuntematon':'ei-perilla'", self.seuraa)
        nayta = self.h[self.h.index("function naytaHaettu("):self.h.index("async function laheta(")]
        self.assertIn("h.tila==='tuntematon'?'Yhteys katkesi. Vastaus voi olla tallessa keskustelussa: lataa sivu", nayta)

    def test_ei_innerhtml(self):
        self.assertNotIn("innerHTML", self.h)


AJURI_JS = """
const [base, ev, kid, skenaario, alku] = process.argv.slice(2);
const KYSELY_MS=150, KYSELY_YLARAJA_MS=20000, KYSELY_VIRHEET=3;
const H={'Content-Type':'application/json','X-Aivo':'1'};
const q=encodeURIComponent;
const oikea=globalThis.fetch;
globalThis.fetch=(u,o)=>oikea(base+u,Object.assign({},o,{headers:Object.assign({},(o||{}).headers,{Cookie:ev})}));
const fs=require('fs');
eval(fs.readFileSync(process.argv[7],'utf8'));
(async()=>{const ohjaus={valmis:false},ac=new AbortController();
 let lahetys=null;
 if(skenaario==='katkos'){const p=new AbortController();setTimeout(()=>p.abort(),300);
  lahetys=fetch('/api/viesti',{method:'POST',headers:H,signal:p.signal,body:JSON.stringify({keskustelu:kid,teksti:'uusi kysymys'})}).then(()=>'ok',e=>e.name);}
 const h=await seuraa(kid,skenaario==='katkos'?'uusi kysymys':'sama',Number(alku),ohjaus,ac);
 console.log(JSON.stringify({h:h,post:lahetys?await lahetys:null}));})();
"""


@unittest.skipUnless(shutil.which("node"), "node puuttuu")
class SelainAjoTesti(Pohja):
    """Ajaa sivun omat viimeisin()- ja seuraa()-funktiot Nodessa elavaa palvelinta vasten."""

    def setUp(self):
        super().setUp()
        h = chat.HTML
        self.koodi = h[h.index("function nuku("):h.index("function naytaHaettu(")]
        self.hak = tempfile.TemporaryDirectory()
        self.addCleanup(self.hak.cleanup)
        self.ajuri = os.path.join(self.hak.name, "ajuri.js")
        self.funktiot = os.path.join(self.hak.name, "funktiot.js")
        with open(self.ajuri, "w", encoding="utf-8") as f:
            f.write(AJURI_JS)
        with open(self.funktiot, "w", encoding="utf-8") as f:
            f.write(self.koodi.replace("async function seuraa(", "globalThis.seuraa=async function(")
                    .replace("async function viimeisin(", "globalThis.viimeisin=async function(")
                    .replace("function nuku(", "globalThis.nuku=function("))

    def aja(self, kid, skenaario, alku, base=None):
        base = base or "http://%s:%d" % (LOOP, self.srv.server_address[1])
        r = subprocess.run(["node", self.ajuri, base, self.ev, kid, skenaario, str(alku), self.funktiot],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_katkennut_post_ja_haku_loytaa_vastauksen(self):
        def hidas(*a, **kw):
            time.sleep(1.5)
            return "valmis vastaus"
        self.tila.kysy_yks = hidas
        kid = self.uusi()
        with contextlib.redirect_stderr(io.StringIO()):
            t = self.aja(kid, "katkos", 0)
        self.assertEqual(t["post"], "AbortError")
        self.assertEqual(t["h"], {"tila": "valmis", "tony": 0, "v": {"indeksi": 1, "teksti": "valmis vastaus"}})

    def test_vanhaa_samaa_vastausta_ei_nayteta(self):
        kid = self.uusi()
        self.assertEqual(self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "sama"})[0], 200)
        self.assertEqual(self.aja(kid, "ei-lahetysta", 2)["h"], {"tila": "ei-perilla"})
        # alku tuntematon (alkuhaku epaonnistui) ja viimeisin Tonyn viesti vastaa lahetettya: vastaus voi olla
        # tallessa, joten selain kehottaa lataamaan sivun eika vaita, ettei viesti mennyt perille
        self.assertEqual(self.aja(kid, "ei-lahetysta", -1)["h"], {"tila": "tuntematon"})

    def test_tuntematon_alku_eri_viesti_ei_perilla(self):
        kid = self.uusi()
        self.assertEqual(self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "muu"})[0], 200)
        self.assertEqual(self.aja(kid, "ei-lahetysta", -1)["h"], {"tila": "ei-perilla"})

    def test_verkko_poikki_lopettaa_kyselyn(self):
        s = socket.socket()
        s.bind((LOOP, 0))
        vapaa = s.getsockname()[1]
        s.close()
        self.assertEqual(self.aja("x", "ei-lahetysta", 0, base="http://%s:%d" % (LOOP, vapaa))["h"], {"tila": "ei-yhteytta"})


if __name__ == "__main__":
    unittest.main()
