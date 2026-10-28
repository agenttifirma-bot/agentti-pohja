# agentscope (CT115, /opt/agentscope)

`virheilmoitus.py` on Telegram-virheilmoitus systemd-yksikoille ja yojonolle (`yojono-tila`, dedupe tiedostossa `/var/lib/yojono/ilmoitettu.json`). Koodi asennetaan kasin isannalle: kopioi `virheilmoitus.py` kohteeseen `/opt/agentscope/` ja `testit/test_virheilmoitus.py` kohteeseen `/opt/agentscope/testit/`. Testit: `python3 -B -m unittest discover -s testit`. Talletettu repoon 28.10.2026 isannalla olleesta versiosta (varmuuskopio ja versionhallinta).
