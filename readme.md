# Simple Fleet Management

Webová aplikace pro evidenci vozidel – tankování, spotřeba, servis, pravidelné prohlídky,
upomínky a výdaje. Vznikla jako projekt kurzu Python (Robodream).

- **Web:** FastAPI + Jinja2 šablony, bez JS frameworku (Chart.js pro grafy)
- **Databáze:** MySQL (SQLAlchemy 2, migrace Alembic), pro vývoj i SQLite
- **Konzolová aplikace** (`app/run_cli.py`) zůstává funkční, nové funkce jsou ale jen na webu

## Obsah
- [Funkce](#funkce)
- [Instalace a spuštění](#instalace-a-spuštění)
- [Databáze a migrace](#databáze-a-migrace)
- [Správa uživatelů](#správa-uživatelů)
- [Napojení na Timeline](#napojení-na-timeline)
- [Nasazení na server](#nasazení-na-server)
- [Struktura projektu](#struktura-projektu)
- [Testy](#testy)
- [Backlog](#backlog)

## Funkce

### Uživatelé a sdílení
- registrace a přihlášení (heslo hashované PBKDF2, ochrana CSRF, omezení pokusů o přihlášení)
- každý uživatel vidí jen svá vozidla
- **sdílení vozidla** s dalšími uživateli – role *Jen náhled* nebo *Úpravy*
  - vlastník: vše včetně smazání vozidla a správy sdílení, může vozidlo předat jinému uživateli
  - editor: zapisuje tankování, servis, výdaje, upomínky a upravuje údaje vozidla
  - čtenář: jen prohlíží
  - uživatel, se kterým je vozidlo sdíleno, může sdílení sám ukončit

### Vozidla
Značka, model, rok výroby, barva (+ barva pro zobrazení), SPZ, VIN, poznámka, datum nákupu
a prodeje, aktivní/neaktivní.

### Tankování
- datum, čas, tachometr, palivo, množství (l / kWh / kg), cena za jednotku **nebo** celková cena
  (druhá se dopočítá), měna, platba, stanice, poznámka
- **automatický převod cizí měny** kurzem ČNB ke dni tankování; když ČNB není dostupná,
  aplikace si vyžádá ruční kurz (nikdy neuloží cizí cenu jako Kč)
- **výpočet spotřeby** metodou „plná–plná“ – zvlášť pro každý druh paliva (LPG/benzín),
  příznak „vynechané tankování“ úsek vyřadí; po úpravě či smazání se vše přepočítá
- kontrola, že stav tachometru odpovídá chronologii
- **dohledání pumpy z aplikace Timeline** – tlačítko „Načíst pumpu“ podle data a času tankování
  doplní název a adresu stanice ze záznamů polohy (viz [Napojení na Timeline](#napojení-na-timeline))
- filtrování (vozidlo, období, palivo) a export do CSV

### Servis, pravidelný servis, upomínky
- servisní záznamy (typ, místo, cena v libovolné měně)
- **pravidelný servis** – časový a/nebo kilometrový interval od posledního servisu daného typu;
  upozornění, když zbývá méně než 10 % intervalu, nebo po termínu
- **upomínky** podle data a/nebo tachometru, jednorázové i opakované (denně–ročně, po X km),
  nastavitelný předstih upozornění
- upozornění se zobrazují na přehledu a v detailu vozidla a po uložení každého záznamu

### Výdaje a statistiky
- ostatní výdaje (dálniční známka, pojištění, mytí, mýtné, …) s převodem měny, export CSV
- **platnost výdaje** (dálniční známka, pojištění, …) – u dálniční známky stačí zvolit typ
  (roční / 30denní / 10denní / jednodenní) a konec platnosti se dopočítá; aplikace založí
  upomínku konce platnosti, při zápisu nové známky tu starou uzavře a v detailu vozidla
  ukazuje, do kdy známka platí (odkaz „Obnovit“)
  - eDálnice veřejné API pro ověření platnosti nemají, platnost se proto počítá z nákupu
- statistiky vozidla: náklady (palivo / servis / výdaje), náklady na km, ujetá vzdálenost,
  průměrná spotřeba, grafy měsíčních nákladů, spotřeby a ceny paliva
- **statistiky všech vozidel** (`/stats`): souhrn a tabulka po vozidlech, měsíční náklady,
  vývoj stavu tachometru a průměrné ceny paliva

### Instalace jako aplikace (PWA)
Na mobilu i v desktopovém Chrome/Edge lze aplikaci „nainstalovat“ (vyžaduje HTTPS).

## Instalace a spuštění

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux: source .venv/bin/activate)
pip install -r requirements.txt

cp .env.template .env             # vyplňte DB_* a SECRET_KEY
alembic upgrade head              # vytvoří / aktualizuje tabulky
python app/run_web.py             # http://127.0.0.1:8000  (--reload pro vývoj)
```

Pro rychlé vyzkoušení bez MySQL stačí v `.env` nastavit `DATABASE_URL="sqlite:///fleet.db"`.

Konzolová aplikace: `cd app && python run_cli.py`

## Databáze a migrace

Schéma spravuje **Alembic** (`app/migrations/versions`). Původní `database.sql` byl nahrazen
migracemi – první migrace vytváří tytéž tabulky, ale jen pokud ještě neexistují, takže
`alembic upgrade head` lze spustit i na databázi založené ručně z původního `database.sql`.

Změny schématu oproti původní databázi:
- nové tabulky `users`, `vehicle_shares`, `service_records`, `service_intervals`, `reminders`, `expenses`
- `vehicles.owner_id` – vlastník vozidla
- SPZ a VIN už nejsou globálně unikátní (stejné auto mohou evidovat různí uživatelé)

Nová migrace po změně modelů: `alembic revision --autogenerate -m "popis"`, výsledek zkontrolujte.

## Správa uživatelů

```bash
python app/manage.py create-user                 # nový uživatel
python app/manage.py list-users
python app/manage.py set-password <email>
python app/manage.py assign-orphans <email>      # vozidla bez vlastníka -> uživatel
python app/manage.py deactivate-user <email>
```

**Po migraci existující databáze** nemají stará vozidla vlastníka a na webu nejsou vidět.
Zaregistrujte se (nebo `create-user`) a spusťte `assign-orphans <váš e-mail>`.
Totéž platí pro vozidla založená v konzolové aplikaci.

Registraci přes web lze vypnout: `ALLOW_REGISTRATION=false`.

## Napojení na Timeline

Aplikace Timeline (běží na stejném serveru) zná podle záznamů polohy, u které pumpy uživatel byl.
- v `.env` nastavte `TIMELINE_URL` (např. `http://127.0.0.1:5000`); prázdné = funkce vypnutá
- každý uživatel si v Timeline vygeneruje API klíč (Správa → Účet a zabezpečení → API klíč)
  a uloží ho ve svém **Profilu**; klíč se zobrazuje jen zkráceně
- dotaz jde přes server aplikace (`/fuel-records/timeline-stop`), klíč se do prohlížeče
  nedostane; klíč ani poloha se nelogují, timeout 5 s, výpadek Timeline neblokuje uložení

## Nasazení na server

GitHub Actions (`.github/workflows/deploy.yml`) po pushi do `main` spustí testy a pokud projdou,
přes SSH aktualizuje kód na serveru, nainstaluje závislosti, **provede migrace** a restartuje službu.

Na serveru je potřeba v `.env` doplnit:
- `SECRET_KEY` – jinak budou uživatelé po každém restartu odhlášeni
- `SESSION_HTTPS_ONLY=true`, pokud aplikace běží za HTTPS

Aplikace naslouchá na `WEB_HOST:WEB_PORT` (výchozí 127.0.0.1:8000) a počítá s reverzní proxy
(např. nginx) před sebou. Pro kontrolu dostupnosti slouží `/healthz`.

## Struktura projektu

```
app/
  models/        SQLAlchemy modely
  services/      obchodní logika (sdílí web i konzole)
  web/
    main.py      FastAPI aplikace, middleware, obsluha chyb
    routers/     stránky podle oblastí (auth, vozidla, tankování, servis…)
    templates/   Jinja2 šablony
    static/      CSS, JS, ikony, PWA manifest a service worker
  migrations/    Alembic migrace
  cli/           konzolová aplikace
  manage.py      správcovské příkazy
  run_web.py     spuštění webu
tests/           pytest (běží proti SQLite v paměti)
```

## Testy

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Testy nikdy nesahají na databázi z `.env` ani na ČNB (kurz je podvržen).

## Backlog

- fotografie vozidla a dokladů k výdajům
- evidence pokut a bodového konta
- údaje z velkého TP přes API Datové kostky (vyžaduje registraci API klíče)
- ověření platnosti dálniční známky přímo u eDálnic (až bude veřejné API)
- e-mailové / push notifikace upomínek
- obnova zapomenutého hesla e-mailem
- import tankování z CSV (např. z jiných aplikací)
