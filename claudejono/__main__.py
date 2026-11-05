import sys

if len(sys.argv) > 1 and sys.argv[1] in ("laatu", "mittari", "vapauta"):
    from claudejono.laatu import main
else:
    from claudejono.ajuri import main

sys.exit(main())
