# API Simple Fleet Management pro Timeline

Popis pro aplikaci, která se k evidenci vozidel připojuje (Timeline). Obě volání používají stejný
klíč a stejný způsob přihlášení.

## Přihlášení

- Uživatel si klíč vygeneruje v evidenci v **Profilu → API klíč pro Timeline**. Klíč má tvar `fk_…`
  (46 znaků) a ukáže se jen jednou.
- Klíč se posílá jen v hlavičce, nikdy v adrese:
  ```
  Authorization: Bearer fk_…
  ```
- Klíč patří jednomu uživateli. API vrací jen vozidla, která uživatel vlastní nebo která mu někdo nasdílel.
- Klíč ani odpovědi nelogujte (obsahují osobní údaje). Odpovědi mají `Cache-Control: no-store`.
- Adresa: Timeline běží na stejném serveru, volá tedy přímo `http://127.0.0.1:8000`.
  Zvenku je API na `https://fleet.martinc.cz`.

## Chyby

Chyba je vždy JSON `{"error": "popis"}` s kódem:

| Kód | Kdy |
|-----|-----|
| 401 | chybí klíč, je neplatný, byl zrušen nebo nahrazen novým, uživatel je deaktivovaný (hlavička `WWW-Authenticate: Bearer`) |
| 400 | špatné parametry |
| 404 | vozidlo nenalezeno nebo k němu uživatel nemá přístup (jen `/api/refuels`) |

## Seznam vozidel – `GET /api/vehicles`

```
GET /api/vehicles?status=active
Authorization: Bearer fk_…
```

| Parametr | Hodnoty | Výchozí |
|----------|---------|---------|
| `status` | `active` = jen aktivní vozidla, `all` = všechna včetně neaktivních, prodaných a vrácených | `active` |

Aktivní vozidlo je vozidlo označené jako aktivní, které není prodané (datum prodeje je dnes nebo dřív)
a u půjčeného vozidla ještě není vrácené. Je to stejné jako záložka „Jen aktivní“ v evidenci.

Vozidla jsou seřazená: nejdřív aktivní, pak ostatní; v rámci skupiny podle značky a modelu.

### Odpověď

```json
{
  "status": "all",
  "vehicles": [
    {
      "id": "12",
      "plate": "1AB2345",
      "name": "Škoda Octavia",
      "brand": "Škoda",
      "model": "Octavia",
      "kind": "car",
      "production_year": 2019,
      "engine_volume": 1498,
      "engine_power": 110,
      "color": "šedá",
      "color_hex": "#8A8D8F",
      "vin": "TMBJJ7NE0K0123456",
      "active": true,
      "status": "active",
      "role": "owner",
      "owner": "Martin",
      "odometer": 154320,
      "fuel_types": ["Natural 95"],
      "consumption": [{"fuel": "Benzín", "value": 6.42, "unit": "l"}],
      "tire_sizes": ["205/55 R16 91V"],
      "purchase": {"date": "2021-03-15", "odometer": 61200, "price_czk": 389000.0},
      "sale": {"date": null, "odometer": null, "price_czk": null},
      "vignette": {"status": "valid", "date": "2027-02-28"},
      "is_rental": false,
      "rental": null,
      "last_record": "2026-11-20",
      "note": "Servisní knížka v příruční schránce",
      "notes": [
        {"id": "93", "time": "2026-11-20T18:05:00", "odometer": 154320, "category": "Garáž",
         "text": "Uloženo v garáži u chalupy", "author": "Martin"},
        {"id": "71", "time": "2026-08-02T09:40:00", "odometer": null, "category": null,
         "text": "Škrábnutí na zadním nárazníku\nNafoceno", "author": "Jana"}
      ]
    },
    {
      "id": "17",
      "plate": "2CD3456",
      "name": "Toyota Yaris",
      "brand": "Toyota",
      "model": "Yaris",
      "kind": "car",
      "production_year": null,
      "engine_volume": null,
      "engine_power": null,
      "color": null,
      "color_hex": "#FFFFFF",
      "vin": null,
      "active": false,
      "status": "returned",
      "role": "owner",
      "owner": "Martin",
      "odometer": 15420,
      "fuel_types": ["Natural 95"],
      "consumption": [],
      "tire_sizes": [],
      "purchase": {"date": null, "odometer": null, "price_czk": null},
      "sale": {"date": null, "odometer": null, "price_czk": null},
      "vignette": null,
      "is_rental": true,
      "rental": {"provider": "Půjčovna AutoPraha", "from": "2026-05-01T08:30:00", "to": "2026-05-04"},
      "last_record": "2026-05-04",
      "note": null,
      "notes": []
    }
  ]
}
```

### Položky vozidla

Prázdné údaje jsou `null` (seznamy `[]`). Hodnota `0` je platná (např. tachometr 0 km), nezaměňujte ji s `null`.

| Položka | Popis |
|---------|-------|
| `id` | ID vozidla v evidenci (řetězec), stálé |
| `plate` | SPZ bez mezer, velkými písmeny; může být `null`. Stejnou SPZ lze použít v `/api/refuels` |
| `name` | značka a model pro zobrazení |
| `brand`, `model` | značka, model |
| `kind` | `car` (auto) nebo `moto` (motorka) |
| `production_year` | rok výroby |
| `engine_volume` | objem motoru v cm³ (u elektromobilu může být `0`) |
| `engine_power` | výkon v kW |
| `color` | barva slovy (jak je zapsaná v evidenci) |
| `color_hex` | barva pro zobrazení – barva, kterou evidence vozidlo označuje v seznamech a grafech (`#RRGGBB`, vždy vyplněná, výchozí `#FFFFFF`) |
| `vin` | VIN |
| `active` | `true` = aktivní vozidlo (viz výše) |
| `status` | `active`, `inactive` (ručně vyřazené), `sold` (prodané), `returned` (vrácené půjčené) |
| `role` | vztah uživatele k vozidlu: `owner` (vlastník), `editor` (může zapisovat), `viewer` (jen čte) |
| `owner` | jméno vlastníka vozidla |
| `odometer` | nejvyšší známý stav tachometru v km ze všech záznamů |
| `fuel_types` | paliva, která se do vozidla tankovala (abecedně) |
| `consumption` | průměrná spotřeba za celou dobu, zvlášť pro každý druh paliva: `fuel` (druh: Benzín, Nafta, LPG, CNG, Elektřina…), `value` (spotřeba na 100 km, 2 desetinná místa), `unit` (`l`, `kg` nebo `kWh`). Počítá se metodou „plná–plná“ (od tankování do plna po další tankování do plna); dokud nejsou aspoň dvě tankování do plna, je seznam prázdný. Hlavní palivo bývá první, pořadí ale není zaručené |
| `tire_sizes` | rozměry pneumatik podle technického průkazu |
| `purchase` | nákup: `date`, `odometer` (km), `price_czk` |
| `sale` | prodej: `date`, `odometer` (km), `price_czk` |
| `vignette` | česká dálniční známka podle zapsaných výdajů, nebo `null`, když žádná není zapsaná. `status`: `valid` (platí, `date` = poslední den platnosti), `expiring` (platí, ale končí do 7 dní), `future` (koupená dopředu, `date` = první den platnosti), `expired` (`date` = poslední den poslední známky) |
| `is_rental` | půjčené vozidlo (půjčovna, od známého) |
| `rental` | jen u půjčeného vozidla: poslední půjčení. `provider` (od koho), `from` a `to` (datum `YYYY-MM-DD`, nebo datum a čas `YYYY-MM-DDTHH:MM:SS`, když je čas zapsaný; `to` je `null`, dokud není vráceno) |
| `last_record` | datum posledního záznamu u vozidla (tankování, servis, výdaj, poznámka, pneumatiky, půjčení, nákup / prodej), jen do dneška |
| `note` | poznámka v údajích vozidla (jeden text, např. kde je servisní knížka) |
| `notes` | poznámky k vozidlu v čase (jako na časové ose: garáž, nehoda, poškození…), od nejnovější. `id`, `time` (místní čas), `odometer` (km nebo `null`), `category` (typ poznámky nebo `null`), `text` (může mít víc řádků, nebo `null`), `author` (jméno uživatele, který poznámku zapsal) |

Data jsou ve formátu `YYYY-MM-DD`, časy jsou místní (Praha) bez časové zóny, částky jsou čísla v Kč.

## Tankování vozidla – `GET /api/refuels`

```
GET /api/refuels?plate=1AB2345&from=2026-07-10T06:00:00&to=2026-07-15T20:00:00&context=full
Authorization: Bearer fk_…
```

| Parametr | Popis |
|----------|-------|
| `plate` | SPZ (povinná). Porovnává se bez mezer a velkými písmeny. Má-li stejnou SPZ víc vozidel, přednost má aktivní |
| `from`, `to` | místní čas bez časové zóny (povinné). Samotné datum v `to` znamená celý den |
| `context` | `full` = navíc tankování od posledního tankování do plna před `from` do prvního tankování do plna po `to` |

Odpověď:

```json
{
  "vehicle": {"plate": "1AB2345", "name": "Škoda Octavia"},
  "refuels": [
    {
      "id": "481",
      "time": "2026-07-12T17:34:00",
      "odometer": 152870,
      "quantity": 41.7,
      "unit": "l",
      "fuel_type": "Natural 95",
      "price_total": 1538.73,
      "currency": "CZK",
      "price_czk": 1538.73,
      "full": true,
      "station_name": "Orlen",
      "station_address": "Pražská 12, Benešov",
      "fueled_by": "Martin"
    }
  ]
}
```

Tankování jsou seřazená vzestupně podle času a jsou to všechna tankování vozidla, ať tankoval kdokoli.
`price_total` je v původní měně (`currency`), `price_czk` přepočtená na Kč. `fueled_by` je jméno uživatele,
který záznam zapsal (u starých záznamů `null`).

## Příklad (Python)

```python
import requests

BASE = "http://127.0.0.1:8000"
headers = {"Authorization": f"Bearer {api_key}"}   # klíč uživatele z nastavení Timeline

vehicles = requests.get(f"{BASE}/api/vehicles", params={"status": "active"},
                        headers=headers, timeout=5)
vehicles.raise_for_status()
for v in vehicles.json()["vehicles"]:
    print(v["plate"], v["name"], v["odometer"])
```
