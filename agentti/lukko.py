"""Tiedostolukko (flock) ja atominen kirjoitus. Vain Linux/macOS (palvelinkayttoon)."""
import contextlib
import fcntl
import os
import tempfile


@contextlib.contextmanager
def lukittu(polku):
    fd = os.open(polku, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # sulkeminen vapauttaa lukon


def kirjoita_atomisesti(polku, teksti):
    hakemisto = os.path.dirname(os.path.abspath(polku))
    fd, tmp = tempfile.mkstemp(dir=hakemisto, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(teksti)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, polku)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
