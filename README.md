# ATLAS OS 0.1

Een persoonlijke assistentwerkruimte voor een Raspberry Pi 5 (4 GB) met een
officieel touchscreen. ATLAS draait **boven Raspberry Pi OS**; het is een
fullscreen dashboard, geen vervanging van de Linux-kernel of Raspberry Pi OS.

## Wat werkt in deze versie?

| Onderdeel | Functies |
|---|---|
| Dashboard | Overzicht van open taken, vandaag en geheugen; responsive touchscreenbediening |
| School | Taken, toetsen en deadlines toevoegen, bewerken, afvinken en heropenen |
| Agenda | Afspraken toevoegen/verwijderen; automatische verdeling van schoolwerk over zeven dagen |
| Geheugen | Lokale notities; UTF-8 TXT/Markdown importeren en zoeken |
| Keuken | Recepten bewaren; hoeveelheden in g, ml en stuks naar porties omrekenen |
| Systeem | Vrije opslag, Pi-temperatuur, instellingen, gegevens als JSON exporteren |
| AI | Officiële Sign in with ChatGPT; accountkeuze, modelkeuze, vernieuwen en uitloggen |
| Actiemanager | AI kan taken en notities bewaren en de week plannen; optioneel automatisch uitvoeren |
| Opstart | systemd-service + Chromium fullscreen bij desktop-login |

De lokale functies hebben geen AI of internet nodig. ChatGPT gebruikt internet.
Google/Outlook Calendar-synchronisatie, spraak, PDF/Word-extractie,
volledige keukenwerkplanning en computerbediening worden nog niet aangeboden.

## Installatie op de Pi

Benodigd: Raspberry Pi OS **64-bit Desktop**, Python 3.11 of nieuwer,
internet voor installatie en ChatGPT, en je gewone Pi-gebruikersaccount.

1. Pak de download uit zodat `run.py` in `~/atlas-os/` staat. Houd de map
   op die plek; de service verwijst naar dat pad.
2. Open Terminal op de Pi:

   ```bash
   cd ~/atlas-os
   bash install.sh
   ```

   Het script vraagt sudo voor pakketinstallatie en de systemd-service.
   Het maakt een eigen Python-omgeving, voert tests uit en installeert
   `/etc/systemd/system/atlas-os.service` en een desktop-autostartbestand.
3. Open **http://127.0.0.1:8080** op de Pi.
4. Activeer desgewenst **desktop auto-login** via Raspberry Pi Configuration.
   De service start bij het opstarten; het fullscreen dashboard start zodra
   de grafische desktop is ingelogd. Het script verandert auto-login niet.
5. Sluit Chromium met `Alt+F4` om terug te gaan naar de gewone desktop.

Het touchscreen werkt als normale browserinvoer. Een schermtoetsenbord hangt
af van je Raspberry Pi OS-desktopconfiguratie; ATLAS installeert er zelf geen.

### Zonder automatische opstart

```bash
cd ~/atlas-os
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

Open http://127.0.0.1:8080. Gebruik geen `0.0.0.0`: deze versie is bewust
voor lokaal gebruik en heeft geen netwerk-login voor andere apparaten.

## ChatGPT Plus verbinden

1. Open **Assistent → Continue with ChatGPT** op de Pi.
2. Log in op OpenAI's pagina en geef toestemming voor ChatGPT-plan gebruik.
3. Je komt terug op ATLAS; kies een model uit de opgehaalde catalogus.
4. Probeer bijvoorbeeld: “Maak een taak voor Nederlands, vrijdag om 12:00,
   45 minuten: leesverslag afmaken.”
5. Controleer het voorstel onder **Acties** en klik op **Uitvoeren**.

Er is **geen betaalde OpenAI API-key** nodig. Deze integratie gebruikt een
OAuth-token voor ondersteunde Responses-verzoeken uit je bestaande
ChatGPT-abonnement. Toegang, beschikbare modellen en gebruikslimieten
worden door OpenAI bepaald. ATLAS schakelt nooit over op API-billing.
De inlogfunctie geeft geen toegang tot je bestaande ChatGPT-gesprekken.

Log in in een browser **op dezelfde Pi**, want OpenAI stuurt je terug naar
`http://127.0.0.1:8080/auth/callback`. Een browser op je laptop verwijst met
127.0.0.1 naar de laptop, niet naar de Pi.

ATLAS ondersteunt aparte accountregistraties, elk met eigen client-ID en
inloggegevens. Je kiest een bestaand account of voegt een nieuw account toe.
Uitloggen wist lokale tokens en probeert de vernieuwbare sessie bij OpenAI
in te trekken; als dat niet bevestigd kan worden, meldt ATLAS dit.

## Zelfstandig uitvoerbare acties

Standaard staan automatische AI-acties uit. Zet ze aan bij **Systeem** als
ATLAS deze drie acties direct mag uitvoeren:

- `create_task`: schooltaak, toets of deadline toevoegen;
- `create_note`: notitie bewaren;
- `plan_week`: toekomstige automatisch geplande studieblokken vervangen.

Elke actie krijgt een logregel. Andere toolnamen worden afgewezen. Een
afgebroken AI-stream leidt tot geen acties. Elke actie kan maximaal één keer
worden goedgekeurd. Een actie die door een crash op `running` blijft staan,
wordt niet automatisch opnieuw uitgevoerd; controleer eerst het resultaat.
ATLAS voert geen door een model geschreven shellcommando's uit.

De planner werkt in Europe/Amsterdam, standaard dagelijks tussen 16:00 en
20:00. Zet je lessen, werk en andere bezette tijden eerst in de agenda.
De planner verdeelt open taken in blokken van maximaal 45 minuten met
10 minuten tussen opeenvolgende blokken van dezelfde taak, respecteert
afspraken en deadlines en meldt resterende minuten als niet alles past.
De planner schat geen werkelijke voortgang; pas de benodigde minuten zelf
aan als je gedeeltelijk klaar bent. Het opnieuw plannen gebeurt op verzoek
of als AI-actie, niet via een achtergrondtimer.

## Gegevens en privacy

- Standaard staat de database in `~/.local/share/atlas/atlas.sqlite3`.
- Lokale gegevens worden tussen herstarts bewaard. Tokens staan apart,
  versleuteld met Fernet, in `accounts.enc`. De sleutel staat in `vault.key`;
  eigenaarstoegang beschermt beide. Dit beschermt niet tegen iemand die
  volledige toegang tot je Pi-gebruikersaccount heeft.
- Tokens en sleutels worden niet geëxporteerd in de JSON-gegevensbackup.
- Een AI-verzoek deelt het bericht, maximaal 100 open taken en maximaal 100
  komende afspraken met OpenAI. Notities worden alleen gedeeld als je dit
  aanvinkt: de laatste tien, maximaal 3000 tekens per notitie.
- Recepten, documenten en notities blijven lokaal als je ze niet deelt.
- Er zijn geen advertenties, analytics of externe frontend-assets.
- Bewaar een volledige back-up van de datamap als je de complete installatie
  wilt kunnen herstellen. Houd sleutel en accountbestanden privé. De
  JSON-export is voor je werkgegevens; een JSON-import is nog niet gebouwd.

## Onderhoud

```bash
systemctl status atlas-os.service
sudo systemctl restart atlas-os.service
journalctl -u atlas-os.service -n 50
```

Automatisch dashboard openen uitschakelen: verwijder of hernoem
`~/.config/autostart/atlas-os.desktop`. De service uitschakelen:

```bash
sudo systemctl disable --now atlas-os.service
```

Om code bij te werken, vervang projectbestanden en installeer eventuele nieuwe
requirements in `.venv`; herstart daarna de service. Laat de datamap staan.

## Tests en huidige verificatie

```bash
python -m unittest discover -s tests -v
node --check atlas/static/app.js
bash -n install.sh
```

De eerste 13 tests zijn lokaal uitgevoerd op Windows/Python 3.12: opslag,
CSRF, hostcontrole, documenten, receptberekening, actiebeleid,
planning en OAuth met ondertekende testtokens en gesimuleerde netwerkantwoorden.
In een echte browser zijn een taak en een studieplanning aangemaakt.
De GitHub-workflow voert de checks op Linux/Python 3.11 uit zodra de code
is gepubliceerd.

**Nog te verifiëren op jouw Pi:** apt-installatie, systemd, fullscreen
desktop-opstart, touchscreen en een echte ChatGPT-autorisatie plus AI-verzoek.
De login is geïmplementeerd volgens de officiële documentatie, maar er is
in deze bouwsessie geen echte OAuth-toestemming of betaalde AI-aanroep gedaan.

## Officiële integratiebronnen

- [Overzicht en beschikbaarheid](https://developers.openai.com/siwc/token-sharing-open-source)
- [Registratie, PKCE, OIDC en scopecontrole](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Accountbeheer, tokenvernieuwing en uitloggen](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [Modellen en Responses-streaming](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)

MIT-licentie. ATLAS is een zelfstandig project en geen officieel OpenAI-product.
