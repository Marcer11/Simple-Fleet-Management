import requests

class ExchangeRate:
    def __init__(self, date: str, currency_code: str, amount: float):
        self.date = date
        self.currency_code = currency_code
        self.amount = amount

    def ConvertToCZK(self):
        response = requests.get(f"https://api.cnb.cz/cnbapi/exratesa/daily?date={self.date}&lang=CZ")
        if response.status_code != 200:
            raise Exception("Nepodařilo se získat kurzovní lístek z ČNB.")
        
        data = response.json()
        for rate in data["rates"]:
            if rate["currencyCode"] == self.currency_code:
                amount = float(rate["amount"])
                rate_value = float(rate["rate"])
                print(f"Načtěný kurz ČNB: {amount} {self.currency_code} = {rate_value} CZK")
                return (self.amount / amount) * rate_value

        raise ValueError(f"Nenalezen kurz pro měnu {self.currency_code} k datu {self.date}.")