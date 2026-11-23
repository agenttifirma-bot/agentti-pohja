"""Ajastinmallit: oneshot-palvelun toisto lasketaan edellisen ajon paattymisesta (23.11.2026).

Kontin 122 aivo-tiivista-yksityinen.timer (OnBootSec + OnUnitActiveSec, palvelu Type=oneshot) ajoi kerran,
mutta seuraavaa ajoa ei ajastettu (NEXT "-"). Testi kay lapi repon *.timer.mall-tiedostot seka
Markdown-ohjeiden koodilohkot ja hylkaa ajastimen, jonka ainoa toisto on OnUnitActiveSec ja jonka palvelu on
Type=oneshot. Markdownissa ajastimen palveluksi tulkitaan Unit=-rivi tai lahin edeltava [Service]-lohko.
"""
import re
import unittest
from pathlib import Path

JUURI = Path(__file__).resolve().parent.parent
OHITA = {".git", "node_modules", "__pycache__"}
# Toistot, jotka saavat lahtopisteen oneshot-palvelullekin: ajon paattyminen tai kello.
TOIMIVA_TOISTO = ("OnUnitInactiveSec", "OnCalendar")
KOODILOHKO = re.compile(r"^[ \t]*```[^\n]*\n(.*?)^[ \t]*```", re.S | re.M)


def osiot(teksti):
    """Palauttaa {"[Osio]": {avain: [arvot]}}; kommentit ja tyhjat rivit ohitetaan."""
    tulos, osio = {}, None
    for rivi in teksti.splitlines():
        rivi = rivi.strip()
        if not rivi or rivi.startswith(("#", ";")):
            continue
        if rivi.startswith("[") and rivi.endswith("]"):
            osio = rivi
            tulos.setdefault(osio, {})
            continue
        if osio and "=" in rivi:
            avain, arvo = rivi.split("=", 1)
            tulos[osio].setdefault(avain.strip(), []).append(arvo.strip())
    return tulos


def toisto_vain_unitactive(timer):
    """True, jos [Timer]-osion ainoa toisto on OnUnitActiveSec (ei OnUnitInactiveSec/OnCalendar)."""
    t = timer.get("[Timer]", {})
    if not any(t.get("OnUnitActiveSec", [])):
        return False
    return not any(any(t.get(k, [])) for k in TOIMIVA_TOISTO)


def on_oneshot(palvelu):
    return palvelu.get("[Service]", {}).get("Type", [""])[-1] == "oneshot"


def tiedostot(paate):
    for polku in sorted(JUURI.rglob("*" + paate)):
        if not OHITA.intersection(polku.relative_to(JUURI).parts):
            yield polku


def palvelumalli(timer_polku, timer):
    """Etsii ajastimen palvelun mallitiedoston: Unit= tai sama nimi, .service.mall."""
    unit = timer.get("[Timer]", {}).get("Unit", [""])[-1]
    if unit:
        nimi = unit.replace("%i", "")
    else:
        nimi = timer_polku.name[: -len(".timer.mall")] + ".service"
    ehdokkaat = [timer_polku.parent / (nimi + ".mall")]
    ehdokkaat += [p for p in tiedostot(".service.mall") if p.name == nimi + ".mall"]
    for p in ehdokkaat:
        if p.is_file():
            return p
    return None


def mallien_virheet():
    virheet = []
    for polku in tiedostot(".timer.mall"):
        timer = osiot(polku.read_text(encoding="utf-8"))
        if not toisto_vain_unitactive(timer):
            continue
        palvelu = palvelumalli(polku, timer)
        if palvelu is None:
            virheet.append(f"{polku.relative_to(JUURI)}: toisto vain OnUnitActiveSec, palvelun mallia ei loydy")
        elif on_oneshot(osiot(palvelu.read_text(encoding="utf-8"))):
            virheet.append(f"{polku.relative_to(JUURI)}: toisto vain OnUnitActiveSec, palvelu Type=oneshot")
    return virheet


def markdown_virheet(teksti, nimi="<teksti>"):
    virheet, viimeisin_palvelu, palvelut = [], None, {}
    for osuma in KOODILOHKO.finditer(teksti):
        lohko = osiot(osuma.group(1))
        if "[Service]" in lohko:
            viimeisin_palvelu = lohko
        if "[Timer]" not in lohko or not toisto_vain_unitactive(lohko):
            continue
        rivi = teksti.count("\n", 0, osuma.start()) + 1
        palvelu = viimeisin_palvelu
        if palvelu is None:
            virheet.append(f"{nimi}:{rivi}: toisto vain OnUnitActiveSec, palvelulohkoa ei loydy")
        elif on_oneshot(palvelu):
            virheet.append(f"{nimi}:{rivi}: toisto vain OnUnitActiveSec, palvelu Type=oneshot")
    return virheet


class AjastinToisto(unittest.TestCase):
    def test_repon_ajastinmallit(self):
        self.assertEqual(mallien_virheet(), [])

    def test_repon_ohjeet(self):
        virheet = []
        for polku in tiedostot(".md"):
            virheet += markdown_virheet(polku.read_text(encoding="utf-8"), str(polku.relative_to(JUURI)))
        self.assertEqual(virheet, [])

    def test_ohjeiden_tiivistysajastimet_inaktiivista(self):
        for nimi in ("docs/aivo-yksityinen.md", "docs/aivo-chat.md"):
            teksti = (JUURI / nimi).read_text(encoding="utf-8")
            ajastimet = [osiot(o.group(1))["[Timer]"] for o in KOODILOHKO.finditer(teksti)
                         if "[Timer]" in osiot(o.group(1))]
            self.assertEqual(len(ajastimet), 1, nimi)
            t = ajastimet[0]
            self.assertEqual(t.get("OnUnitInactiveSec"), ["15min"], nimi)
            self.assertEqual(t.get("OnActiveSec"), ["1min"], nimi)
            self.assertNotIn("OnUnitActiveSec", t, nimi)
            self.assertIn("--no-pager", teksti)
            self.assertRegex(teksti, r"list-timers aivo-tiivista[\w-]*\.timer --no-pager")


class Tarkistin(unittest.TestCase):
    VANHA = """
3. Palvelu:

   ```
   [Service]
   Type=oneshot
   ExecStart=/bin/true
   ```

4. Ajastin:

   ```
   [Timer]
   OnBootSec=10min
   OnUnitActiveSec=15min
   ```
"""

    def test_hylkaa_pelkan_onunitactivesec_oneshotilla(self):
        virheet = markdown_virheet(self.VANHA)
        self.assertEqual(len(virheet), 1)
        self.assertIn("Type=oneshot", virheet[0])

    def test_hyvaksyy_onunitinactivesec(self):
        uusi = self.VANHA.replace("OnUnitActiveSec=15min", "OnActiveSec=1min\n   OnUnitInactiveSec=15min")
        self.assertEqual(markdown_virheet(uusi), [])

    def test_hyvaksyy_simple_palvelun(self):
        self.assertEqual(markdown_virheet(self.VANHA.replace("Type=oneshot", "Type=simple")), [])

    def test_hylkaa_ilman_palvelulohkoa(self):
        vain_ajastin = "```\n[Timer]\nOnUnitActiveSec=5min\n```\n"
        self.assertEqual(len(markdown_virheet(vain_ajastin)), 1)

    def test_kommentoitu_rivi_ei_laske(self):
        self.assertFalse(toisto_vain_unitactive(osiot("[Timer]\n# OnUnitActiveSec=15min\nOnCalendar=daily\n")))

    def test_tyhja_arvo_ei_ole_toisto(self):
        # OnUnitInactiveSec= (tyhja) nollaa ajastimet eika anna toistoa.
        self.assertTrue(toisto_vain_unitactive(osiot("[Timer]\nOnUnitInactiveSec=\nOnUnitActiveSec=5min\n")))


if __name__ == "__main__":
    unittest.main()
