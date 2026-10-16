"""Komentorivi: python -m agentti [--agentti NIMI] [--llm] [--send] [--tila HAKEMISTO] [--env TIEDOSTO]

Paluukoodit: 0 ok, 1 ajo epaonnistui (virhekoodi stderriin), 2 kayttovirhe."""
import argparse
import importlib
import os
import re
import sys

from . import ajo, config

NIMI_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


def main(argv=None):
    p = argparse.ArgumentParser(prog="agentti", description="Aja agentti (oletus: kuiva-ajo ilman verkkoa).")
    p.add_argument("--agentti", default="esimerkki", help="agentin moduulin nimi (agentti/agentit/NIMI.py)")
    p.add_argument("--llm", action="store_true", help="kutsu mallia (kuluu rahaa, kulukatto voimassa)")
    p.add_argument("--send", action="store_true", help="laheta Telegramiin (korkeintaan kerran paivassa)")
    p.add_argument("--tila", default=os.environ.get("AGENTTI_TILA", "tila"), help="tilahakemisto (kulu, lahetysmerkit)")
    p.add_argument("--env", help="KEY=VALUE-tiedosto; ymparistomuuttujat ohittavat sen")
    args = p.parse_args(argv)

    if not NIMI_RE.match(args.agentti):
        print("virhe: virheellinen agentin nimi", file=sys.stderr)
        return 2
    try:
        agentti = importlib.import_module("agentti.agentit." + args.agentti)
    except ImportError:
        print("virhe: agenttia ei loydy", file=sys.stderr)
        return 2

    env = {}
    if args.env:
        try:
            env.update(config.lue_env(args.env))
        except config.EnvVirhe as e:
            print("virhe: %s" % e, file=sys.stderr)
            return 2
    env.update({k: v for k, v in os.environ.items() if k in (
        "LLM_BASE_URL", "LLM_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SYDAN_URL")})

    tulos = ajo.suorita(agentti, env, args.tila, llm=args.llm, laheta=args.send)
    print(tulos["teksti"])
    if tulos["virhe"]:
        print("virhe: %s" % tulos["virhe"], file=sys.stderr)
    if tulos["lahetys"]:
        print("lahetys: %s" % tulos["lahetys"], file=sys.stderr)
    return tulos["koodi"]


if __name__ == "__main__":
    sys.exit(main())
