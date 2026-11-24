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
- [Napojení na Timeline](#napojení-na-timeline) (dohledání pumpy, API pro Timeline)
- [Nasazení na server](#nasazení-na-server)
- [Struktura projektu](#struktura-projektu)
- [Testy](#testy)
- [Backlog](#backlog)

## Funkce

### Rozvržení aplikace
- **výchozí obrazovka (Přehled)**: rychlé zápisy (tankování, servis, výdaj, poznámka), upozornění
  a pod nimi časová osa všech vozidel; filtr časové osy je skrytý a zobrazí se po kliknutí na „Filtr“
- **detail vozidla**: nahoře tlačítka pro zápis k vozidlu (tankování, servis, výdaj, poznámka, přezutí,
  kontrola dezénu, upomínka), hlavní čísla a upozornění; údaje o vozidle, pneumatiky, pravidelný servis
  a upomínky a spotřeba jsou ve sbalovacích sekcích; pod nimi časová osa vozidla
- **tabulky** lze řadit kliknutím na záhlaví sloupce (datum, číslo i text, prázdné hodnoty vždy na konci)
- formuláře jsou bez ukázkových textů a vysvětlivek u polí

### Uživatelé a sdílení
- registrace a přihlášení (heslo hashované PBKDF2, ochrana CSRF, omezení pokusů o přihlášení)
- každý uživatel vidí jen svá vozidla
- **sdílení vozidla** s dalšími uživateli – role *Jen náhled* nebo *Úpravy*
  - vlastník: vše včetně smazání vozidla a správy sdílení, může vozidlo předat jinému uživateli
  - editor: zapisuje tankování, servis, výdaje, upomínky a upravuje údaje vozidla
  - čtenář: jen prohlíží
  - uživatel, se kterým je vozidlo sdíleno, může sdílení sám ukončit

### Vozidla
Druh (auto / motorka), značka, model, rok výroby, barva (+ barva pro zobrazení), SPZ, VIN, poznámka, datum, cena a stav
tachometru při nákupu a prodeji (ztráta hodnoty, najeto za dobu vlastnictví), rozměry pneumatik dle TP (jen údaj
u vozidla), aktivní/neaktivní. Vozidlo s datem prodeje se mezi aktivními nezobrazuje (zapsáním prodeje se deaktivuje).
Seznam vozidel ukazuje tachometr, spotřebu, náklady za rok a typ pneumatik; vlastník je až v detailu vozidla.
Smazání vozidla je schované dole ve formuláři úprav.

### Poznámky a časová osa
- **poznámky k vozidlu** s datem, časem a stavem tachometru (uloženo do garáže, půjčeno, nehoda…);
  stav tachometru se kontroluje proti ostatním záznamům v čase – stejný stav v různé dny je povolený
- **časová osa** (na výchozí obrazovce a v detailu vozidla; `/timeline` přesměruje): tankování, servis,
  výdaje, pneumatiky, poznámky, nákup a prodej v jednom seznamu po měsících, filtr podle vozidla, období
  a druhu události; každá událost má barvu a **ikonu** (tankování, servis, STK, výdaj, pojištění,
  dálniční známka, parkování, pneumatiky, kontrola dezénu, poškození, nehoda, garáž, půjčení…) a zabírá
  jeden řádek + zkrácený detail (kliknutím se zobrazí celý)

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
- **vlastní seznam paliv** (Tankování → Paliva): nově zadané palivo se uloží do nabídky; každé palivo má
  *druh* (benzín, nafta, LPG, CNG, elektřina), podle kterého se počítá spotřeba a určuje jednotka –
  Natural 95 i Verva 100 jsou benzín; přejmenování se promítne i do zapsaných tankování
- palivo lze navázat na **značky pump** (Verva 100 → ORLEN, V-Power → Shell, i víc značek);
  formulář tankování pak u dané pumpy nabízí jen její paliva a paliva bez omezení
- **přehled čerpacích stanic** – značka (podle názvu stanice) → jednotlivé stanice podle adresy,
  počet tankování, množství, útrata, průměrná cena za litr
- **API pro Timeline** – Timeline si načítá tankování vozidla podle SPZ do výdajů výletů

### Servis, pravidelný servis, upomínky
- servisní záznamy (místo, cena v libovolné měně) – **více položek najednou** (olej, brzdy, STK, …
  zaškrtnutím, vlastní položky čárkou); pravidelný servis se počítá i od servisu, kde byla jeho položka
  jednou z více
- **pravidelný servis** – časový a/nebo kilometrový interval od posledního servisu daného typu;
  upozornění, když zbývá méně než 10 % intervalu, nebo po termínu
- **univerzální servisní intervaly** (`/service-intervals`, Servis → Servisní intervaly) – platí pro všechna
  vozidla uživatele (volitelně jen auta nebo motorky), pokud u vozidla není interval stejného typu
  nastaven jinak; vypnutý interval vozidla univerzální interval u vozidla vypne; nabídnou se doporučené
  (olej, filtry, brzdová kapalina, rozvody, STK, klimatizace); u sdíleného vozidla platí intervaly vlastníka
- **upomínky** podle data a/nebo tachometru, jednorázové i opakované (denně–ročně, po X km),
  nastavitelný předstih upozornění
- upozornění se zobrazují na přehledu a v detailu vozidla a po uložení každého záznamu

### Pneumatiky (`/tires`)
- vlastní stránka v menu: co je teď na kterém vozidle, sklad všech pneumatik s filtrem
  (stav, typ, vozidlo), historie přezutí a poškození
- **pneumatika** = jedna guma, pár nebo sada (počet kusů) – patří uživateli, ne vozidlu, takže ji lze
  nasazovat na různá vozidla; typ (letní / zimní / univerzální), výrobce a model, rozměr, rok výroby
  a DOT, alu / plechové disky / bez disků, dezén při nákupu, místo uložení, vyřazení s důvodem;
  cena nákupu se uloží a volitelně zapíše jako výdaj „Pneumatiky“ k vybranému vozidlu
- **přezutí** na vozidle doma nebo v servisu (v servisu = servisní záznam „Přezutí pneumatik“ s cenou):
  pneumatiky se nasazují na pozice (všechna kola, přední / zadní náprava, jednotlivé kolo, rezerva);
  nasazení na obsazenou pozici původní pneumatiku sundá – při výměně jen předních zůstane zbytek sady
  vzadu; nasazením na jiné vozidlo se pneumatika z původního sundá; při sundání lze zapsat dezén
  **každého kola zvlášť** (pro zákonné minimum se hlídá nejmenší hodnota);
  stav tachometru se kontroluje proti ostatním záznamům; smazat lze přezutí, z něhož ještě nic
  nebylo sundáno (vše se vrátí, jak bylo)
- **nákres vozidla** při přezutí – kola obarvená podle typu pneumatik; kliknutím na kolo se zobrazí, co na
  něm je, pole pro dezén a výběr pneumatiky k nasazení na kolo, nápravu nebo všechna kola
- **auto / motorka** (nastavuje se u vozidla): motorka má jen přední a zadní kolo a nedostává upozornění
  na zimní pneumatiky; v přehledu a seznamu vozidel je ikona druhu vozidla a typu nasazených pneumatik
  u SPZ (letní ☀, zimní ❄, univerzální = napůl vločka a slunce)
- **kontrola dezénu** – průběžné měření během roku na obrazovce s nákresem vozidla, kde se ke každému
  kolu zapíše hloubka (u kola je vidět i poslední naměřená hodnota); kontroly jsou na časové ose
- **poškození** (pozice, popis, cena opravy jako výdaj k vozidlu, na kterém pneumatika byla)
- **životnost**: najeto (i přes více vozidel), počet nasazení a doba na voze, stáří, dezén,
  opotřebení na 1000 km a odhad km do zákonného minima (letní 1,6 mm, zimní a univerzální 4 mm),
  náklady na 1000 km; opotřebení se počítá z dezénu při nákupu a posledního měření (kontrola nebo sundání,
  nejmenší hodnota z kol, nejméně 3 000 km mezi měřeními)
- **upozornění v přehledu pneumatik** („Pozor na“): dezén pod zákonným minimem, blížící se konec vzorku
  (méně než 5 000 km, i s odhadem v měsících podle průměrného nájezdu vozidla), stáří ≥ 6 let;
  typ pneumatik je všude jen jako ikona
- **upozornění na zimní pneumatiky**: od 15. 10. a v období 1. 11. – 31. 3. u aktivních aut,
  která mají nasazené letní pneu
- přezutí a poškození jsou i na časové ose

### Výdaje a statistiky
- ostatní výdaje (dálniční známka, pojištění, mytí, mýtné, …) s převodem měny, export CSV
- **platnost výdaje** (dálniční známka, pojištění, …) – u dálniční známky stačí zvolit typ
  (roční / 30denní / 10denní / jednodenní) a konec platnosti se dopočítá; aplikace založí
  upomínku konce platnosti, při zápisu nové známky tu starou uzavře a v detailu vozidla
  ukazuje, do kdy známka platí (odkaz „Obnovit“)
  - eDálnice veřejné API pro ověření platnosti nemají, platnost se proto počítá z nákupu
- statistiky vozidla: náklady (palivo / servis / výdaje), náklady na km, ujetá vzdálenost,
  průměrná spotřeba, grafy měsíčních nákladů, spotřeby a ceny paliva (každé tankování)
- **vývoj najetých kilometrů** ve statistice vozidla: stav tachometru v čase (ze všech záznamů se stavem
  tachometru) a najeto po měsících (lineárně mezi zápisy); graf kilometrů (u vozidla i u všech vozidel)
  lze přepnout mezi „od nuly“ (najeto od začátku období) a skutečným stavem tachometru; body grafu jsou i nákup
  a prodej vozidla (datum + km, v popisku bodu „Nákup / Prodej vozidla“) – 0 km je platný stav (nové vozidlo),
  prázdné pole znamená neznámý stav a bod se nevytvoří
- **spotřeba podle druhu paliva** – v detailu i statistikách vozidla: hlavní a alternativní palivo
  (např. benzín a LPG) zvlášť, v rámci druhu rozpad na konkrétní paliva (Natural 95 / 98) a natankované
  množství; benzín i LPG lze zapsat ve stejný čas a při stejném stavu tachometru, AdBlue apod.
  (palivo bez druhu) spotřebu neovlivní
- v detailu vozidla: jak často se tankuje (průměrný počet dní a km mezi tankováními)
  a kolik se průměrně najezdí za rok
- **statistiky všech vozidel** (`/stats`): souhrn a tabulka po vozidlech (včetně km za rok a četnosti
  tankování), měsíční náklady, ujeté km od začátku období (porovnatelné i u aut s velmi rozdílným
  tachometrem) a cena paliva u každého tankování

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
python app/manage.py recalculate-consumption     # přepočet spotřeby (spouští se při každém deployi)
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

### API pro Timeline (tankování do výdajů výletů)

Opačným směrem si Timeline z evidence načítá tankování vozidla podle SPZ.
- uživatel si v **Profilu → API klíč pro Timeline** vygeneruje klíč (`fk_…`); ukáže se jen jednou,
  v databázi je uložen jen jeho SHA-256; „Vygenerovat nový“ starý zneplatní, „Zrušit“ ho smaže
- Timeline běží na stejném serveru, volá tedy přímo `http://127.0.0.1:8000/api/refuels`

```
GET /api/refuels?plate=1AB2345&from=2026-07-10T06:00:00&to=2026-07-15T20:00:00&context=full
Authorization: Bearer fk_…
```
- `plate` – SPZ, porovnává se bez mezer (i uvnitř) a velkými písmeny; vozidlo musí uživatel
  vlastnit nebo ho mít sdílené (pokud má stejnou SPZ víc vozidel, přednost má aktivní)
- `from`, `to` – místní čas bez časové zóny (samotné datum v `to` = celý den)
- `context=full` – navíc tankování od posledního tankování do plna před `from` a do prvního
  tankování do plna po `to` (včetně částečných mezi nimi)
- vrací všechna tankování vozidla (ať tankoval kdokoli) vzestupně podle času:
  `id`, `time`, `odometer`, `quantity`, `unit`, `fuel_type`, `price_total` + `currency` (původní měna),
  `price_czk`, `full`, `station_name`, `station_address`, `fueled_by` (jméno uživatele, který záznam
  zapsal; u záznamů před touto verzí `null`)
- chyby jako `{"error": "…"}`: 401 chybějící/neplatný klíč, 404 vozidlo nenalezeno nebo bez přístupu,
  400 špatné parametry

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
