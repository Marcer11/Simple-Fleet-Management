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

        // Filtr nahradí aktuální záznam v historii (tlačítko Zpět pak nevrací jednotlivé kroky
        // filtrování, ale předchozí stránku); seřazení tabulky zůstane.
        function submit() {
            if (submitted) return;
            submitted = true;
            const params = new URLSearchParams();
            new FormData(form).forEach(function (value, key) { if (value !== "") params.append(key, value); });
            const sort = new URLSearchParams(location.search).get("sort");
            if (sort) params.set("sort", sort);
            const action = form.getAttribute("action") || location.pathname;
            const query = params.toString();
            location.replace(action + (query ? "?" + query : "") + (form.getAttribute("data-hash") || ""));
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
                        if (window.sfmRefreshFuels) window.sfmRefreshFuels();
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

    // Tankování: nabídka paliv podle pumpy (palivo s vyplněnými pumpami se nabízí jen u nich)
    const fuelOptions = document.getElementById("fuel-options");
    const fuelList = document.getElementById("fuel-types");
    const stationInput = document.getElementById("f-station_name");
    if (fuelOptions && fuelList && stationInput) {
        const config = JSON.parse(fuelOptions.textContent);
        const patterns = config.patterns.map(function (p) {
            try { return [new RegExp(p[0], "i"), p[1]]; } catch (e) { return null; }
        }).filter(Boolean);
        function brandOf(name) {
            name = name.trim().replace(/\s+/g, " ");
            if (!name) return "";
            for (const [re, brand] of patterns) if (re.test(name)) return brand;
            return name.split(" ")[0];
        }
        const fuelVehicle = document.getElementById("f-vehicle_id");
        function vehicleFuels() {
            const option = fuelVehicle && fuelVehicle.selectedOptions[0];
            const value = option ? option.getAttribute("data-fuels") : "";
            return value ? value.split("|") : [];
        }
        function refreshFuels() {
            const brand = brandOf(stationInput.value).toLowerCase();
            const allowed = vehicleFuels();  // druhy paliva vozidla (prázdné = neuvedeno, nabízí se vše)
            fuelList.replaceChildren(...config.fuels
                .filter(function (f) {
                    return !allowed.length || !f.category || allowed.indexOf(f.category) !== -1;
                })
                .filter(function (f) {
                    return !brand || !f.brands.length || f.brands.some(function (b) { return b.toLowerCase() === brand; });
                })
                .map(function (f) { const o = document.createElement("option"); o.value = f.name; return o; }));
        }
        stationInput.addEventListener("input", refreshFuels);
        if (fuelVehicle) fuelVehicle.addEventListener("change", refreshFuels);
        stationInput.addEventListener("change", refreshFuels);
        refreshFuels();
        window.sfmRefreshFuels = refreshFuels;  // po načtení pumpy z Timeline
    }

    // Výběr sady pneumatik jen pro zvolené vozidlo: <select data-by-vehicle> s <option data-vehicle>
    const bySelect = document.querySelector("select[data-by-vehicle]");
    const ownerSelect = document.getElementById("f-vehicle_id");
    if (bySelect && ownerSelect) {
        const all = Array.from(bySelect.options).filter(function (o) { return o.dataset.vehicle; });
        function filterSets() {
            const vid = ownerSelect.value;
            const current = bySelect.value;
            bySelect.replaceChildren(bySelect.options[0] || new Option("– vyberte –", ""),
                ...all.filter(function (o) { return !vid || o.dataset.vehicle === vid; }));
            const still = all.some(function (o) { return o.value === current && (!vid || o.dataset.vehicle === vid); });
            bySelect.value = still ? current : "";
        }
        ownerSelect.addEventListener("change", filterSets);
        filterSets();
    }

    // Formulář závislý na vozidle (přezutí): po výběru vozidla načíst stránku znovu
    document.querySelectorAll("select[data-reload]").forEach(function (select) {
        select.addEventListener("change", function () {
            const params = new URLSearchParams(window.location.search);
            params.set(select.name, select.value);
            window.location.search = params.toString();
        });
    });

    // Přezutí: pole servisu a ceny jen při přezutí v servisu
    const placeSelect = document.querySelector("select[data-toggle-service]");
    if (placeSelect) {
        const serviceOnly = [document.querySelector("[data-service-only]"),
            (document.getElementById("f-price_paid") || {}).parentElement,
            (document.getElementById("f-currency_code") || {}).parentElement].filter(Boolean);
        function toggleService() {
            const show = placeSelect.value === "service";
            serviceOnly.forEach(function (el) { el.hidden = !show; });
            const rate = document.getElementById("rate-field");
            if (rate && !show) rate.hidden = true;
        }
        placeSelect.addEventListener("change", toggleService);
        toggleService();
    }

    // Přezutí: nákres vozidla. Kliknutím na kolo se otevře panel - co je teď na kole, dezén při sundání,
    // co nasadit a kam (kolo / náprava / všechna). Vše se zapisuje do běžných polí formuláře
    // (mount_tire_N / mount_pos_N, remove_ID, tread_ID_kolo), která jsou při zapnutém JS skrytá.
    const swapBoard = document.querySelector("[data-swap-board]");
    const swapDataEl = document.getElementById("swap-data");
    if (swapBoard && swapDataEl) initSwapDiagram(swapBoard, JSON.parse(swapDataEl.textContent));

    function initSwapDiagram(board, data) {
        const form = board.closest("form");
        const figure = board.querySelector("[data-swap-figure]");
        const panel = board.querySelector("[data-swap-panel]");
        const summary = board.querySelector("[data-swap-summary]");
        const fallback = form.querySelector("[data-swap-fallback]");
        const moto = data.kind === "moto";
        const SVG = "http://www.w3.org/2000/svg";
        const SEASON = { "Letní": "summer", "Zimní": "winter", "Univerzální": "allseason" };
        // kolo nákresu -> místo (slot) v datech; u motorky kolo = celá náprava
        const WHEELS = moto
            ? [{ key: "f", slot: "fl", label: "Přední kolo", x: 112, y: 32, w: 36, h: 80 },
               { key: "r", slot: "rl", label: "Zadní kolo", x: 110, y: 246, w: 40, h: 88 }]
            : [{ key: "fl", slot: "fl", label: "Levé přední kolo", x: 52, y: 62, w: 28, h: 62 },
               { key: "fr", slot: "fr", label: "Pravé přední kolo", x: 180, y: 62, w: 28, h: 62 },
               { key: "rl", slot: "rl", label: "Levé zadní kolo", x: 52, y: 222, w: 28, h: 62 },
               { key: "rr", slot: "rr", label: "Pravé zadní kolo", x: 180, y: 222, w: 28, h: 62 },
               { key: "spare", slot: "spare", label: "Rezerva", cx: 130, cy: 284, r: 19 }];
        const rows = [];
        for (let i = 0; ; i++) {
            const tire = form.elements["mount_tire_" + i], pos = form.elements["mount_pos_" + i];
            if (!tire || !pos) break;
            rows.push({ tire: tire, pos: pos });
        }
        let selected = WHEELS[0].key;
        let message = "";

        board.hidden = false;
        if (fallback) fallback.hidden = true;

        function slotsOf(position) { return data.slots[position] || []; }
        function overlaps(a, b) { return a.some(function (s) { return b.indexOf(s) >= 0; }); }
        function positionOf(slots) {
            const sorted = slots.slice().sort().join(",");
            return Object.keys(data.slots).find(function (k) {
                return data.positions[k] && data.slots[k].slice().sort().join(",") === sorted;
            }) || null;
        }
        function wheelSlots(wheel) { return moto ? slotsOf(wheel.key === "f" ? "front" : "rear") : [wheel.slot]; }
        function field(name) { return form.elements[name]; }
        function removeBox(mount) { return field("remove_" + mount.id); }
        function planned() {
            return rows.filter(function (r) { return r.tire.value; })
                .map(function (r) { return { row: r, tire: r.tire.value, position: r.pos.value, slots: slotsOf(r.pos.value) }; });
        }
        // co se stane se současným nasazením: "stay" | "partial" | "off"
        function fate(mount, plan) {
            const box = removeBox(mount);
            if ((box && box.checked) || plan.some(function (p) { return p.tire === String(mount.tire); })) return "off";
            const mountSlots = slotsOf(mount.position);
            const taken = plan.reduce(function (acc, p) { return acc.concat(p.slots); }, []);
            const left = mountSlots.filter(function (s) { return taken.indexOf(s) < 0; });
            if (left.length === mountSlots.length) return "stay";
            return left.length && positionOf(left) ? "partial" : "off";
        }
        function stateOf(wheel, plan) {
            const slots = wheelSlots(wheel);
            const current = data.current.find(function (m) { return overlaps(slotsOf(m.position), slots); }) || null;
            const next = plan.find(function (p) { return overlaps(p.slots, slots); }) || null;
            let after = null, isNew = false;
            if (next) { after = data.tires[next.tire]; isNew = true; }
            else if (current && fate(current, plan) !== "off") after = current;
            const leaving = current && (next || fate(current, plan) === "off") ? current : null;
            return { current: current, next: next, after: after, isNew: isNew, leaving: leaving };
        }

        // ---------- úpravy plánu ----------
        function clearRow(row) { row.tire.value = ""; row.pos.value = row.pos.options[0].value; }
        function freeSlots(slots, exceptTire) {
            planned().forEach(function (p) {
                if (p.tire === exceptTire) { clearRow(p.row); return; }
                if (!overlaps(p.slots, slots)) return;
                const rest = p.slots.filter(function (s) { return slots.indexOf(s) < 0; });
                const restPos = rest.length ? positionOf(rest) : null;
                if (restPos) p.row.pos.value = restPos; else clearRow(p.row);
            });
        }
        function mountTire(tireId, position) {
            freeSlots(slotsOf(position), tireId);
            const empty = rows.find(function (r) { return !r.tire.value; });
            if (!empty) { message = "Víc pneumatik najednou nejde – nejdřív některé nasazení zrušte."; return; }
            empty.tire.value = tireId;
            empty.pos.value = position;
            const box = data.current.find(function (m) { return String(m.tire) === tireId; });
            if (box && removeBox(box)) removeBox(box).checked = false;
        }

        // ---------- kreslení ----------
        function el(name, attrs, parent) {
            const node = document.createElementNS(SVG, name);
            Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
            if (parent) parent.appendChild(node);
            return node;
        }
        function drawBody(svg) {
            if (moto) {
                el("rect", { x: 118, y: 104, width: 24, height: 150, rx: 12, class: "veh-body" }, svg);
                el("rect", { x: 112, y: 158, width: 36, height: 80, rx: 16, class: "veh-seat" }, svg);
                el("path", { d: "M74 122 Q130 102 186 122", class: "veh-bar" }, svg);
                el("rect", { x: 116, y: 124, width: 28, height: 28, rx: 10, class: "veh-glass" }, svg);
            } else {
                el("rect", { x: 72, y: 28, width: 116, height: 292, rx: 44, class: "veh-body" }, svg);
                el("path", { d: "M88 118 Q130 100 172 118 L164 152 Q130 142 96 152 Z", class: "veh-glass" }, svg);
                el("path", { d: "M96 232 Q130 240 164 232 L170 254 Q130 264 90 254 Z", class: "veh-glass" }, svg);
                el("rect", { x: 94, y: 156, width: 72, height: 72, rx: 10, class: "veh-roof" }, svg);
            }
            const front = el("text", { x: 130, y: 16, class: "veh-front", "text-anchor": "middle" }, svg);
            front.textContent = "▲ předek";
        }
        function drawWheel(svg, wheel, state) {
            const tire = state.after;
            const season = tire ? SEASON[tire.season] || "other" : "empty";
            const g = el("g", { class: "wheel wheel-" + season + (state.isNew ? " is-new" : "") +
                (selected === wheel.key ? " is-selected" : ""), tabindex: 0, role: "button",
                "aria-pressed": selected === wheel.key ? "true" : "false",
                "aria-label": wheel.label + ": " + (tire ? tire.label : "bez pneumatiky") }, svg);
            const title = el("title", {}, g);
            title.textContent = wheel.label + (tire ? " – " + tire.label : " – prázdné");
            if (wheel.r) {
                el("circle", { cx: wheel.cx, cy: wheel.cy, r: wheel.r + 5, class: "wheel-ring" }, g);
                el("circle", { cx: wheel.cx, cy: wheel.cy, r: wheel.r, class: "wheel-tire" }, g);
                el("circle", { cx: wheel.cx, cy: wheel.cy, r: wheel.r * 0.45, class: "wheel-rim" }, g);
            } else {
                el("rect", { x: wheel.x - 5, y: wheel.y - 5, width: wheel.w + 10, height: wheel.h + 10, rx: 12, class: "wheel-ring" }, g);
                el("rect", { x: wheel.x, y: wheel.y, width: wheel.w, height: wheel.h, rx: 8, class: "wheel-tire" }, g);
                for (let y = wheel.y + 9; y < wheel.y + wheel.h - 4; y += 9) {
                    el("line", { x1: wheel.x + 5, x2: wheel.x + wheel.w - 5, y1: y, y2: y, class: "wheel-tread" }, g);
                }
            }
            if (state.isNew) {
                const bx = wheel.r ? wheel.cx + wheel.r - 2 : wheel.x + wheel.w - 2;
                const by = wheel.r ? wheel.cy - wheel.r + 2 : wheel.y + 2;
                el("circle", { cx: bx, cy: by, r: 7, class: "wheel-badge" }, g);
            }
            function choose() { selected = wheel.key; message = ""; render(); }
            g.addEventListener("click", choose);
            g.addEventListener("keydown", function (e) {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(); }
            });
        }

        // ---------- panel vybraného kola ----------
        function h(tag, attrs, text) {
            const node = document.createElement(tag);
            Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
            if (text) node.textContent = text;
            return node;
        }
        function treadInputs(mount, onlyWheels) {
            const box = h("div", { class: "tread-inputs" });
            mount.wheels.forEach(function (w) {
                if (onlyWheels && onlyWheels.indexOf(w[0]) < 0) return;
                const real = field("tread_" + mount.id + "_" + w[0]);
                if (!real) return;
                const label = h("label", { title: w[2] });
                label.appendChild(h("span", {}, w[1]));
                const input = h("input", { type: "text", inputmode: "decimal", placeholder: "mm", autocomplete: "off",
                    "aria-label": "Dezén " + w[2] });
                input.value = real.value;
                input.addEventListener("input", function () { real.value = input.value; });
                input.addEventListener("change", function () {
                    // stejná hodnota i na druhé kolo nápravy, pokud je prázdné
                    const pair = { fl: "fr", fr: "fl", rl: "rr", rr: "rl" }[w[0]];
                    const other = pair && field("tread_" + mount.id + "_" + pair);
                    if (other && !other.value) { other.value = input.value; renderSummary(); }
                });
                label.appendChild(input);
                box.appendChild(label);
            });
            return box;
        }
        function scopesFor(wheel) {
            if (moto) return [[wheel.key === "f" ? "front" : "rear", "Jen toto kolo"], ["all", "Obě kola"]];
            if (wheel.key === "spare") return [["spare", "Rezerva"]];
            const axle = wheel.key[0] === "f" ? "front" : "rear";
            return [[wheel.key, "Jen toto kolo"], [axle, axle === "front" ? "Přední náprava" : "Zadní náprava"], ["all", "Všechna kola"]];
        }
        function renderPanel(plan) {
            const wheel = WHEELS.find(function (w) { return w.key === selected; });
            const state = stateOf(wheel, plan);
            panel.replaceChildren();
            panel.appendChild(h("h4", {}, wheel.label));

            const now = h("div", { class: "swap-now" });
            if (state.current) {
                const line = h("div");
                line.appendChild(document.createTextNode("Teď: "));
                line.appendChild(h("strong", {}, state.current.label));
                line.appendChild(h("span", { class: "small muted" }, " · " + state.current.position_label.toLowerCase()));
                now.appendChild(line);
                const box = removeBox(state.current);
                if (box) {
                    const lbl = h("label", { class: "check small" });
                    const cb = h("input", { type: "checkbox" });
                    cb.checked = box.checked;
                    cb.addEventListener("change", function () { box.checked = cb.checked; render(); });
                    lbl.appendChild(cb);
                    lbl.appendChild(document.createTextNode(" sundat bez náhrady (" + state.current.position_label.toLowerCase() + ")"));
                    now.appendChild(lbl);
                }
                if (state.leaving) {
                    const t = h("div", { class: "swap-tread" });
                    t.appendChild(h("span", { class: "small" }, "Dezén při sundání (mm):"));
                    // u auta obě kola nápravy (většinou se liší přední a zadní), jinak jen toto kolo
                    const pair = { fl: "fr", fr: "fl", rl: "rr", rr: "rl" }[wheel.key];
                    t.appendChild(treadInputs(state.current, pair ? [wheel.key, pair] : [wheel.key]));
                    now.appendChild(t);
                }
            } else {
                now.appendChild(h("span", { class: "muted" }, "Teď tu není zapsaná pneumatika."));
            }
            panel.appendChild(now);

            const ids = Object.keys(data.tires);
            if (!ids.length) {
                panel.appendChild(h("p", { class: "small muted" }, "Nemáte žádné pneumatiky k nasazení."));
                return;
            }
            const pick = h("div", { class: "swap-pick" });
            const sel = h("select", { "aria-label": "Pneumatika k nasazení" });
            sel.appendChild(h("option", { value: "" }, "– vyberte pneumatiku –"));
            ids.forEach(function (id) {
                const o = h("option", { value: id }, data.tires[id].full);
                if (state.next && state.next.tire === id) o.selected = true;
                sel.appendChild(o);
            });
            pick.appendChild(h("label", { class: "small" }, "Nasadit:"));
            pick.appendChild(sel);
            const scopes = h("div", { class: "swap-scopes" });
            scopesFor(wheel).forEach(function (sc) {
                const b = h("button", { type: "button", class: "btn btn-sm" + (state.next && state.next.position === sc[0] ? " btn-primary" : "") }, sc[1]);
                b.addEventListener("click", function () {
                    if (!sel.value) { message = "Nejdřív vyberte pneumatiku."; render(); return; }
                    message = "";
                    mountTire(sel.value, sc[0]);
                    render();
                });
                scopes.appendChild(b);
            });
            pick.appendChild(scopes);
            if (state.next) {
                const undo = h("button", { type: "button", class: "btn-link small" }, "Zrušit nasazení na toto kolo");
                undo.addEventListener("click", function () { freeSlots(wheelSlots(wheel), null); message = ""; render(); });
                pick.appendChild(undo);
            }
            panel.appendChild(pick);
            if (message) panel.appendChild(h("p", { class: "small text-danger", role: "alert" }, message));
        }

        // ---------- souhrn ----------
        function renderSummary() {
            const plan = planned();
            summary.replaceChildren();
            const on = h("div");
            on.appendChild(h("h4", {}, "Nasadí se"));
            const ul = h("ul");
            plan.forEach(function (p) {
                const li = h("li");
                const t = data.tires[p.tire] || {};
                li.appendChild(h("strong", {}, t.label || "?"));
                li.appendChild(document.createTextNode(" → " + (data.positions[p.position] || p.position).toLowerCase() + " "));
                const x = h("button", { type: "button", class: "btn-link small", "aria-label": "Zrušit" }, "zrušit");
                x.addEventListener("click", function () { clearRow(p.row); render(); });
                li.appendChild(x);
                ul.appendChild(li);
            });
            if (!plan.length) ul.appendChild(h("li", { class: "muted" }, "nic – klikněte na kolo a vyberte pneumatiku"));
            on.appendChild(ul);
            summary.appendChild(on);

            const off = data.current.filter(function (m) { return fate(m, plan) !== "stay"; });
            if (off.length) {
                const box = h("div");
                box.appendChild(h("h4", {}, "Sundá se"));
                const list = h("ul");
                off.forEach(function (m) {
                    const li = h("li");
                    li.appendChild(h("strong", {}, m.label));
                    li.appendChild(document.createTextNode(" (" + m.position_label.toLowerCase() + ")"));
                    if (fate(m, plan) === "partial") li.appendChild(h("span", { class: "small muted" }, " – zbytek zůstává na voze"));
                    const treads = m.wheels.map(function (w) {
                        const f = field("tread_" + m.id + "_" + w[0]);
                        return f && f.value ? w[1] + " " + f.value : null;
                    }).filter(Boolean);
                    li.appendChild(h("div", { class: "small muted" }, treads.length ? "dezén " + treads.join(" · ") + " mm" : "dezén nezapsán"));
                    list.appendChild(li);
                });
                box.appendChild(list);
                summary.appendChild(box);
            }
        }

        function render() {
            const plan = planned();
            figure.replaceChildren();
            const svg = el("svg", { viewBox: "0 0 260 344", class: "veh-svg" + (moto ? " is-moto" : ""), role: "group",
                "aria-label": "Nákres vozidla – vyberte kolo" });
            // univerzální = svisle napůl zimní a letní
            const defs = el("defs", {}, svg);
            const grad = el("linearGradient", { id: "sfm-allseason", x1: 0, x2: 1, y1: 0, y2: 0 }, defs);
            [[0, "winter"], [0.5, "winter"], [0.5, "summer"], [1, "summer"]].forEach(function (s) {
                el("stop", { offset: s[0], class: "stop-" + s[1] }, grad);
            });
            drawBody(svg);
            WHEELS.forEach(function (w) { drawWheel(svg, w, stateOf(w, plan)); });
            figure.appendChild(svg);
            const legend = h("div", { class: "season-legend small" });
            [["summer", "letní"], ["winter", "zimní"], ["allseason", "univerzální"], ["empty", "prázdné"]].forEach(function (s) {
                const item = h("span", {});
                item.appendChild(h("i", { class: "swatch wheel-" + s[0] }));
                item.appendChild(document.createTextNode(s[1]));
                legend.appendChild(item);
            });
            const nw = h("span", {});
            nw.appendChild(h("i", { class: "swatch swatch-new" }));
            nw.appendChild(document.createTextNode("nově nasazené"));
            legend.appendChild(nw);
            figure.appendChild(legend);
            renderPanel(plan);
            renderSummary();
        }
        rows.forEach(function (r) { r.tire.addEventListener("change", render); r.pos.addEventListener("change", render); });
        render();
    }

    // Kopírování do schránky: <button data-copy="id-pole">
    document.querySelectorAll("[data-copy]").forEach(function (button) {
        button.addEventListener("click", function () {
            const input = document.getElementById(button.dataset.copy);
            if (!input) return;
            input.select();
            const label = button.textContent;
            const done = function () {
                button.textContent = "Zkopírováno";
                setTimeout(function () { button.textContent = label; }, 2000);
            };
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(input.value).then(done, function () { /* pole zůstane označené */ });
            } else if (document.execCommand && document.execCommand("copy")) {
                done();
            }
        });
    });

    // Rozbalovací panel: <button data-toggle="id-panelu" aria-expanded="false">
    document.querySelectorAll("[data-toggle]").forEach(function (button) {
        const panel = document.getElementById(button.getAttribute("data-toggle"));
        if (!panel) return;
        button.addEventListener("click", function () {
            panel.hidden = !panel.hidden;
            button.setAttribute("aria-expanded", String(!panel.hidden));
            if (!panel.hidden) {
                const first = panel.querySelector("select, input");
                if (first) first.focus();
            }
        });
    });

    // Skrytí / zobrazení polí podle zaškrtávátka: data-hide-when="id" (nákup a prodej u půjčeného vozidla),
    // data-show-when="id" (pojistné plnění u servisu a výdaje)
    document.querySelectorAll("[data-hide-when], [data-show-when]").forEach(function (block) {
        const show = block.hasAttribute("data-show-when");
        const box = document.getElementById(block.getAttribute(show ? "data-show-when" : "data-hide-when"));
        if (!box) return;
        const sync = function () { block.hidden = show ? !box.checked : box.checked; };
        box.addEventListener("change", sync);
        sync();
    });

    // Výběr pump u paliva: souhrn vybraných značek v záhlaví
    document.querySelectorAll(".brand-pick").forEach(function (pick) {
        const summary = pick.querySelector("summary");
        const sync = function () {
            const chosen = Array.from(pick.querySelectorAll('input[type="checkbox"]:checked')).map(function (c) { return c.value; });
            const extra = pick.querySelector('input[type="text"]').value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
            summary.textContent = chosen.concat(extra).join(", ") || summary.getAttribute("data-empty");
        };
        pick.addEventListener("change", sync);
        pick.addEventListener("input", sync);
    });

    // Detail události na časové ose: klik zobrazí celý text
    document.addEventListener("click", function (event) {
        const detail = event.target.closest(".tl-detail");
        if (detail) detail.classList.toggle("open");
    });

    // Řazení tabulek kliknutím na záhlaví sloupce (všechny tabulky s <thead>, kromě data-nosort)
    const DATE_RE = /^(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})(?:\s+(\d{1,2}):(\d{2}))?/;
    const NUM_RE = /^[-−]?\d[\d\s ]*(?:,\d+)?/;
    function cellValue(cell) {
        if (!cell) return { empty: true };
        const raw = cell.hasAttribute("data-sort") ? cell.getAttribute("data-sort") : cell.textContent;
        const text = raw.trim().replace(/\s+/g, " ");
        if (!text || text === "–" || text === "-") return { empty: true, text: "" };
        const d = DATE_RE.exec(text);
        const n = NUM_RE.exec(text);
        return {
            text: text,
            date: d ? new Date(+d[3], +d[2] - 1, +d[1], +(d[4] || 0), +(d[5] || 0)).getTime() : null,
            num: n ? parseFloat(n[0].replace(/[\s ]/g, "").replace("−", "-").replace(",", ".")) : null,
        };
    }
    function sortTable(table, index, th, direction) {
        const body = table.tBodies[0];
        const rows = Array.from(body.rows);
        const values = new Map(rows.map(function (r) { return [r, cellValue(r.cells[index])]; }));
        const filled = Array.from(values.values()).filter(function (v) { return !v.empty; });
        const type = filled.length && filled.every(function (v) { return v.date !== null; }) ? "date"
            : (filled.length && filled.every(function (v) { return v.num !== null; }) ? "num" : "text");
        const asc = direction ? direction === "a" : th.getAttribute("aria-sort") !== "ascending";
        table.querySelectorAll("thead th[aria-sort]").forEach(function (o) { o.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        rows.sort(function (a, b) {
            const va = values.get(a), vb = values.get(b);
            if (va.empty || vb.empty) return va.empty === vb.empty ? 0 : (va.empty ? 1 : -1);  // prázdné vždy na konec
            let c;
            if (type === "date") c = va.date - vb.date;
            else if (type === "num") c = va.num - vb.num;
            else c = va.text.localeCompare(vb.text, "cs", { sensitivity: "base", numeric: true });
            return asc ? c : -c;
        });
        rows.forEach(function (r) { body.appendChild(r); });
        // zapamatovat v adrese - po návratu z úpravy záznamu (nebo obnovení stránky) zůstane seřazeno
        if (!direction && window.history.replaceState) {
            const url = new URL(location.href);
            url.searchParams.set("sort", sortableTables.indexOf(table) + "." + index + "." + (asc ? "a" : "d"));
            history.replaceState(history.state, "", url.pathname + url.search + url.hash);
        }
    }
    const sortableTables = [];
    document.querySelectorAll("table").forEach(function (table) {
        if (table.hasAttribute("data-nosort") || !table.tHead || table.tBodies.length !== 1) return;
        const body = table.tBodies[0];
        if (body.rows.length < 2 || body.querySelector("[colspan], [rowspan], tr.group-row")) return;
        sortableTables.push(table);
        const head = table.tHead.rows[table.tHead.rows.length - 1];
        Array.from(head.cells).forEach(function (th, index) {
            if (!th.textContent.trim() || th.colSpan > 1) return;
            th.classList.add("sortable");
            th.tabIndex = 0;
            th.title = "Seřadit";
            th.addEventListener("click", function () { sortTable(table, index, th); });
            th.addEventListener("keydown", function (e) {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sortTable(table, index, th); }
            });
        });
    });

    (function restoreSort() {
        const m = /^(\d+)\.(\d+)\.([ad])$/.exec(new URLSearchParams(location.search).get("sort") || "");
        const table = m && sortableTables[+m[1]];
        const th = table && table.tHead.rows[table.tHead.rows.length - 1].cells[+m[2]];
        if (th && th.classList.contains("sortable")) sortTable(table, +m[2], th, m[3]);
    })();

    // ------------------------------------------------------------------
    // Návrat po úpravě záznamu: odkaz na formulář (…/add, …/edit, import) dostane ?next=<tato stránka>,
    // formulář pak po uložení, zrušení i smazání vrátí uživatele zpět (i se scrollem).
    // ------------------------------------------------------------------
    const FORM_LINK = /\/(add|edit|import)$/;
    const here = function () { return location.pathname + location.search; };
    document.addEventListener("click", function (event) {
        const link = event.target.closest("a[href]");
        if (!link || link.target || event.defaultPrevented) return;
        const url = new URL(link.href, location.href);
        if (url.origin !== location.origin || !FORM_LINK.test(url.pathname) || url.searchParams.has("next")) return;
        if (url.pathname === location.pathname) return;  // odkaz v rámci téhož formuláře
        const back = new URLSearchParams(location.search).get("next") && FORM_LINK.test(location.pathname)
            ? new URLSearchParams(location.search).get("next") : here();
        url.searchParams.set("next", back);
        try { sessionStorage.setItem("sfm-scroll:" + back, String(window.scrollY)); } catch (e) { /* nevadí */ }
        link.href = url.pathname + url.search + url.hash;
    });
    (function returnTarget() {
        const next = new URLSearchParams(location.search).get("next");
        if (!next || next.charAt(0) !== "/" || next.charAt(1) === "/") return;
        document.querySelectorAll('form[method="post" i]').forEach(function (form) {
            if (form.closest(".user-menu")) return;  // odhlášení
            const action = new URL(form.getAttribute("action") || location.href, location.href);
            if (!action.searchParams.has("next")) {
                action.searchParams.set("next", next);
                form.setAttribute("action", action.pathname + action.search);
            }
        });
        document.querySelectorAll(".form-actions a.btn, a[data-cancel]").forEach(function (a) {
            if (a.hasAttribute("data-cancel") || a.textContent.trim() === "Zrušit") a.href = next;
        });
    })();
    (function restoreScroll() {
        let y = null;
        try {
            const key = "sfm-scroll:" + here();
            y = sessionStorage.getItem(key);
            sessionStorage.removeItem(key);
        } catch (e) { /* nevadí */ }
        if (y !== null) window.addEventListener("load", function () { window.scrollTo(0, +y); });
    })();

    // PWA - registrace service workeru
    if ("serviceWorker" in navigator && window.isSecureContext) {
        window.addEventListener("load", function () {
            navigator.serviceWorker.register("/sw.js").catch(function () { /* nevadí */ });
        });
    }
})();
