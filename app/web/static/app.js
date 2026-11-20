// Simple Fleet Manager - drobná vylepšení formulářů
(function () {
    "use strict";

    function num(value) {
        if (value === null || value === undefined) return NaN;
        return parseFloat(String(value).replace(/\s/g, "").replace(",", "."));
    }

    function round(value, decimals) {
        const f = Math.pow(10, decimals);
        return Math.round(value * f) / f;
    }

    // Potvrzení nebezpečných akcí: <form data-confirm="...">
    document.addEventListener("submit", function (event) {
        const message = event.target.getAttribute("data-confirm");
        if (message && !window.confirm(message)) {
            event.preventDefault();
        }
    });

    // Automatické odeslání filtru po změně: <form data-autosubmit>
    document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
        form.addEventListener("change", function () { form.submit(); });
    });

    // Tankování: dopočet celkové ceny / ceny za jednotku
    const volume = document.getElementById("f-volume_liters");
    const unit = document.getElementById("f-unit_price");
    const total = document.getElementById("f-price_paid");
    if (volume && unit && total) {
        let last = unit.value ? "unit" : (total.value ? "total" : "unit");
        function recalc() {
            const v = num(volume.value);
            if (!(v > 0)) return;
            if (last === "unit" && !isNaN(num(unit.value))) {
                total.value = round(num(unit.value) * v, 2).toFixed(2);
            } else if (last === "total" && !isNaN(num(total.value))) {
                unit.value = round(num(total.value) / v, 3).toFixed(3);
            }
        }
        unit.addEventListener("input", function () { last = "unit"; recalc(); });
        total.addEventListener("input", function () { last = "total"; recalc(); });
        volume.addEventListener("input", recalc);
    }

    // Měna: pole pro ruční kurz zobrazit jen u cizí měny
    const currency = document.getElementById("f-currency_code");
    const rateField = document.getElementById("rate-field");
    if (currency && rateField) {
        function toggleRate() {
            const foreign = currency.value.trim().toUpperCase() !== "CZK" && currency.value.trim() !== "";
            rateField.hidden = !foreign;
        }
        currency.addEventListener("input", toggleRate);
        toggleRate();
    }

    // Výběr vozidla: nápověda s posledním stavem tachometru a předvyplnění paliva
    const vehicleSelect = document.getElementById("f-vehicle_id");
    const odoHint = document.getElementById("odometer-hint");
    const fuelType = document.getElementById("f-fuel_type");
    if (vehicleSelect) {
        function updateVehicleHints(initial) {
            const option = vehicleSelect.selectedOptions[0];
            if (!option) return;
            if (odoHint) {
                const odo = option.getAttribute("data-odometer");
                odoHint.textContent = odo ? "Poslední známý stav: " + Number(odo).toLocaleString("cs-CZ") + " km" : "";
            }
            if (fuelType && !initial) {
                const ft = option.getAttribute("data-fuel");
                if (ft) fuelType.value = ft;
            }
        }
        vehicleSelect.addEventListener("change", function () { updateVehicleHints(false); });
        updateVehicleHints(true);
    }

    // Barva vozidla: synchronizace výběru barvy a textového pole
    const colorPicker = document.getElementById("f-color_hex_picker");
    const colorText = document.getElementById("f-color_hex");
    if (colorPicker && colorText) {
        colorPicker.addEventListener("input", function () { colorText.value = colorPicker.value.toUpperCase(); });
        colorText.addEventListener("input", function () {
            if (/^#[0-9a-fA-F]{6}$/.test(colorText.value)) colorPicker.value = colorText.value;
        });
    }

    // PWA - registrace service workeru
    if ("serviceWorker" in navigator && window.isSecureContext) {
        window.addEventListener("load", function () {
            navigator.serviceWorker.register("/sw.js").catch(function () { /* nevadí */ });
        });
    }
})();
