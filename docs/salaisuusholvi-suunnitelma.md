# Salaisuuksien hallinta: yleinen periaate

Tila: periaate. Yksityiskohtainen suunnitelma on yksityisessä docs-repossa.

Periaatteet:
- Tunnukset pidetään yhdessä paikassa, ei hajallaan palveluiden asetustiedostoissa.
- Agentti ei näe tunnusta. Välittäjä tekee kutsun agentin puolesta, kirjaa sen auditointilokiin ja hälyttää estetystä pyynnöstä.
- Käyttöoikeus on kapea: jokainen palvelu saa vain omat tunnuksensa.
- Riskialtis käyttö vaatii ihmisen hyväksynnän.
- Repoon ei kirjoiteta tiedostopolkuja, tiedostonimiä, osoitteita eikä muuta, mistä salaisuuksien sijainnit selviäisivät.
