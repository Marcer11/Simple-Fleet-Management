# Simple Fleet Management

project from Robodream Python course

## Obsah
- [Simple Fleet Management](#simple-fleet-management)
  - [Obsah](#obsah)
  - [Hlavní funkce aplikace](#hlavní-funkce-aplikace)
    - [Části aplikace](#části-aplikace)
      - [Správa vozidla](#správa-vozidla)
      - [Tankování](#tankování)
      - [Servis](#servis)
      - [Pravidelný servis](#pravidelný-servis)
      - [Ostatní upomínky](#ostatní-upomínky)
    - [GUI](#gui)
      - [Obsah webu](#obsah-webu)
  - [Backlog](#backlog)


## Hlavní funkce aplikace

- aplikace s webovým prostředím pomocí flask
- pro ukládání dat bude použita MySQL databáze


### Části aplikace

#### Správa vozidla

Základní informace o vozidle, ke kterému budou vázány další záznamy v databázi.
- Značka
- Model
- Rok výroby
- Barva
- SPZ
- VIN
- Poznámka
- Zakoupeno
- Prodáno
- Aktivní


#### Tankování

Informace o tankování s automatickou konverzí cizích měn a s výpočtěm spotřeby tankovaného paliva.
- Datum
- Čas
- Tachometr
- Typ paliva
- Objem
- Cena - zaplacená (v měně platby)
- Cena - v Kč (přes ČNB API)
- Platební metoda (hotovost, karta, DKV, CCS)
- Spotřeba (výpočet)
- Vynechané tankování
- Poznámka


#### Servis

Záznamy o provedení servisu na vozidle. 
- Datum
- Čas
- Tachometr
- Místo
- Cena - zaplacená (v měně platby)
- Cena - v Kč (přes ČNB API)
- Typ servisu (olej, brzdy, atd.)
- Poznámka


#### Pravidelný servis

Pro konkrétní typ servisu bude možné uložit časový (např. STK) nebo vzdálenostní (např. olej) interval po kterém je nutné servis znovu provést. Interval bude počítán od posledního provedeného servistu daného typu. 

Na servis bude aplikace upozorňovat pokud zbývá méně, než 10% zvoleného intervalu. Intervaly se budou kontrolovat při vložení jakéhokoliv záznamu k vozidlu. Časová interval se bude kontrolovat i při spuštění aplikace.
- Časový interval
- Vzdálenostní interval
- Typ servisu


#### Ostatní upomínky

Bude sloužit jednorázové nebo opakované upozornění na základě data nebo najetých kilometrů. Aplikace může upozornit například na expiraci dokladů, nutnost zimních pneu atd.
- Datum
- Tachometr
- Notifikace
- Interval opakování (jednorázově/denně/týdně/měsíčně/ročně)


### GUI

#### Části webu

- formuláře pro zápis a editaci záznamů do výše uvedených částí
- prohlížeč zadaných údajů s vyhledáváním a filtrováním záznamů
- grafy (spotřeba, výdaje, cena za litr paliva)

## Backlog

- Část "Výdaje" (dílniční známka, provozní kapaliny, myčka, pojištění, atd.)
- Opakované výdaje (pojištení)
- Víceuživatelská aplikace s možností sdílení vozidel (pro editaci nebo jen náhled)
- možnost instalace jako webové aplikace
- možnost vložení fotografie k vozidlu a fotografií dokladů k výdajům
- Část "Pokuty" - sledování pokud a bodového konta uživatele (nutné ruční zadání)
- Zobrazení údajů z velkého TP přes API Datové kostky ministerstva dopravy pomocí zadaného VIN v části "Správa vozidla"