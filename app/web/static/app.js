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
    // Datum se neodesílá při každém stisku klávesy: při psaní roku prohlížeč hlásí
    // mezistavy 0002, 0020, 0202 - odešle se až úplné datum (rok 1900-2100) po krátké
    // pauze, při opuštění pole nebo Enteru. Výběr z kalendáře se tak odešle hned po pauze.
    function plausibleDate(value) {
        if (!value) return true;  // vymazané pole = bez omezení
        const year = parseInt(value.slice(0, 4), 10);
        return year >= 1900 && year <= 2100;
    }
    document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
        let timer = null;
        let submitted = false;
        const dateInputs = Array.from(form.querySelectorAll('input[type="date"]'));
        const initial = new Map(dateInputs.map(function (i) { return [i, i.value]; }));

        function submit() {
            if (submitted) return;
            submitted = true;
            form.submit();
        }
        function dateChanged() {
            return dateInputs.some(function (i) { return i.value !== initial.get(i); });
        }
        function trySubmitDates() {
            clearTimeout(timer);
            if (dateChanged() && dateInputs.every(function (i) { return plausibleDate(i.value); })) submit();
        }

        form.addEventListener("change", function (e) {
            if (e.target.type === "date") {
                clearTimeout(timer);
                timer = setTimeout(trySubmitDates, 1200);
            } else {
                submit();
            }
        });
        dateInputs.forEach(function (input) {
            input.addEventListener("input", function () {
                clearTimeout(timer);
                timer = setTimeout(trySubmitDates, 1200);
            });
            input.addEventListener("blur", trySubmitDates);
            input.addEventListener("keydown", function (e) {
                if (e.key === "Enter") { e.preventDefault(); trySubmitDates(); }
            });
        });
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

    // Výdaj: platnost (dálniční známka, pojištění) - zobrazit jen u vhodných kategorií,
    // u známky dopočítat konec platnosti podle typu
    const validity = document.getElementById("validity");
    const category = document.getElementById("f-category");
    if (validity && category) {
        const categories = JSON.parse(validity.dataset.categories);
        const vignette = validity.dataset.vignette;
        const days = JSON.parse(validity.dataset.days);
        const variantBox = document.getElementById("vignette-field");
        const variant = document.getElementById("f-vignette_variant");
        const from = document.getElementById("f-valid_from");
        const until = document.getElementById("f-valid_until");
        const expenseDate = document.getElementById("f-expense_date");
        const hasValue = until.value !== "";

        function toggle(box, show) {
            box.hidden = !show;
            // skrytá pole se neodesílají
            box.querySelectorAll("input, select").forEach(function (el) { el.disabled = !show; });
        }
        function computeUntil() {
            if (!variant.value || !from.value) return;
            const d = new Date(from.value + "T12:00:00");
            d.setDate(d.getDate() + days[variant.value] - 1);
            until.value = d.toISOString().slice(0, 10);
        }
        function refresh() {
            const name = category.value.trim();
            toggle(validity, hasValue || categories.includes(name));
            toggle(variantBox, name === vignette);
            if (name !== vignette) variant.value = "";
            else if (!variant.value && !until.value) variant.value = "year";  // nejčastější volba
            computeUntil();
        }
        category.addEventListener("input", refresh);
        variant.addEventListener("change", computeUntil);
        from.addEventListener("change", computeUntil);
        until.addEventListener("change", function () { variant.value = ""; });  // ruční úprava = vlastní platnost
        if (expenseDate) {
            if (from.value && from.value !== expenseDate.value) from.dataset.auto = "0";  // předvyplněno (obnovení)
            expenseDate.addEventListener("change", function () {
                if (!from.value || from.dataset.auto !== "0") { from.value = expenseDate.value; computeUntil(); }
            });
            from.addEventListener("input", function () { from.dataset.auto = "0"; });
        }
        refresh();
    }

    // Tankování: dohledání pumpy v Timeline podle data a času
    const lookup = document.getElementById("timeline-lookup");
    if (lookup) {
        const status = document.getElementById("timeline-status");
        const station = document.getElementById("f-station_name");
        const address = document.getElementById("f-station_address");
        const refuelDate = document.getElementById("f-refuel_date");
        const refuelTime = document.getElementById("f-refuel_time");
        function say(text, isError) {
            status.textContent = text;
            status.classList.toggle("error-text", !!isError);
        }
        lookup.addEventListener("click", function () {
            if (!refuelDate.value || !refuelTime.value) { say("Nejdřív vyplňte datum a čas tankování.", true); return; }
            const label = lookup.textContent;
            lookup.disabled = true;
            lookup.textContent = "Hledám…";
            say("");
            const query = new URLSearchParams({ date: refuelDate.value, time: refuelTime.value });
            const controller = new AbortController();
            const timer = setTimeout(function () { controller.abort(); }, 8000);
            fetch("/fuel-records/timeline-stop?" + query, {
                headers: { Accept: "application/json" }, credentials: "same-origin", signal: controller.signal,
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.status === "found") {
                        station.value = data.name;
                        if (address) address.value = data.address || "";
                        let text = "Načteno z Timeline";
                        if (data.arrive && data.leave) text += ` (u pumpy ${data.arrive.slice(11, 16)}–${data.leave.slice(11, 16)})`;
                        if (data.minutes_off) text += ` – čas se liší o ${data.minutes_off} min`;
                        say(text + ".");
                    } else {
                        say(data.message || "Pumpu se nepodařilo dohledat.", data.status !== "not_found");
                    }
                })
                .catch(function () { say("Timeline teď není dostupná.", true); })
                .finally(function () {
                    clearTimeout(timer);
                    lookup.disabled = false;
                    lookup.textContent = label;
                });
        });
    }

    // PWA - registrace service workeru
    if ("serviceWorker" in navigator && window.isSecureContext) {
        window.addEventListener("load", function () {
            navigator.serviceWorker.register("/sw.js").catch(function () { /* nevadí */ });
        });
    }
})();
