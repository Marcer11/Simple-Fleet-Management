// Společné vykreslení grafů (Chart.js). Barvy z CSS proměnných .viz-root (--series-1..8).
window.SfmCharts = (function () {
    "use strict";
    let palette = null;

    function setup() {
        if (palette) return palette;
        const root = document.querySelector(".viz-root") || document.body;
        const css = (name) => getComputedStyle(root).getPropertyValue(name).trim();
        palette = {
            series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => css("--series-" + i)),
            grid: css("--grid"), axisText: css("--axis-text"), surface: css("--chart-surface"),
        };
        Chart.defaults.color = palette.axisText;
        Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
        Chart.defaults.plugins.legend.labels.boxWidth = 12;
        Chart.defaults.plugins.legend.labels.boxHeight = 12;
        return palette;
    }

    const nf = (d) => new Intl.NumberFormat("cs-CZ", { minimumFractionDigits: d, maximumFractionDigits: d });

    function axes(yTitle, beginAtZero) {
        return {
            x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 12 } },
            y: { beginAtZero: beginAtZero !== false, grid: { color: palette.grid }, border: { display: false },
                 title: { display: !!yTitle, text: yTitle } },
        };
    }

    // "2026-11-20" -> "20.11.2026", "2026-11" -> "11/26"
    function formatX(x) {
        const parts = x.split("-");
        if (parts.length === 2) return `${+parts[1]}/${parts[0].slice(2)}`;
        return parts.reverse().join(".");
    }

    // Čárový graf: {název řady: [{x, y}]} - řady se spojí do společné osy x
    function lineChart(id, seriesByName, decimals, unitLabel) {
        const el = document.getElementById(id);
        if (!el || !window.Chart) return;
        const p = setup();
        const names = Object.keys(seriesByName);
        const labels = [...new Set(names.flatMap((n) => seriesByName[n].map((pt) => pt.x)))].sort();
        const many = labels.length > 60;
        const datasets = names.map((name, i) => {
            const byX = Object.fromEntries(seriesByName[name].map((pt) => [pt.x, pt.y]));
            const color = p.series[i % p.series.length];
            return {
                label: name,
                data: labels.map((x) => (x in byX ? byX[x] : null)),
                borderColor: color, backgroundColor: color,
                borderWidth: 2, pointRadius: many ? 2 : 4, pointHoverRadius: 6,
                pointBorderColor: p.surface, pointBorderWidth: many ? 0 : 2,
                spanGaps: true, cubicInterpolationMode: "monotone",
            };
        });
        const a = axes(unitLabel, false);
        return new Chart(el, {
            type: "line",
            data: { labels: labels.map(formatX), datasets },
            options: {
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                scales: a,
                plugins: {
                    legend: { display: names.length > 1, position: "top", align: "start" },
                    tooltip: {
                        callbacks: {
                            label: (c) => c.parsed.y == null ? null
                                : `${c.dataset.label}: ${nf(decimals).format(c.parsed.y)} ${unitLabel}`,
                        },
                    },
                },
            },
        });
    }

    // "#rrggbb" -> "rgba(r, g, b, a)" (slabší čára u grafů s body)
    function fade(color, alpha) {
        const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color || "");
        return m ? `rgba(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)}, ${alpha})` : color;
    }

    function toTime(x) {
        return new Date(x.length === 10 ? x + "T12:00:00" : x).getTime();
    }

    function dateLabel(ms, withTime) {
        const d = new Date(ms);
        let text = `${d.getDate()}. ${d.getMonth() + 1}. ${d.getFullYear()}`;
        if (withTime) text += ` ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
        return text;
    }

    // Popisky osy x na začátcích měsíců (krok podle délky období)
    function monthTicks(scale) {
        const start = new Date(scale.min), end = new Date(scale.max);
        const months = (end.getFullYear() - start.getFullYear()) * 12 + end.getMonth() - start.getMonth() + 1;
        const step = [1, 2, 3, 6, 12, 24].find((s) => months / s <= 8) || 36;
        const ticks = [];
        let d = new Date(start.getFullYear(), start.getMonth() + 1, 1);
        while (d.getMonth() % step !== 0 && step <= 12) d = new Date(d.getFullYear(), d.getMonth() + 1, 1);
        for (; d.getTime() <= scale.max; d = new Date(d.getFullYear(), d.getMonth() + step, 1)) {
            ticks.push({ value: d.getTime() });
        }
        scale.ticks = ticks;
    }

    function monthLabel(ms) {
        const d = new Date(ms);
        return d.getMonth() === 0 ? String(d.getFullYear()) : `${d.getMonth() + 1}/${String(d.getFullYear()).slice(2)}`;
    }

    // Graf v čase se skutečnými rozestupy: {řada: [{x: "YYYY-MM-DD[THH:MM]", y, ...}]}
    // opts: decimals, unit (popisek osy y), valueSuffix(point), thin (slabá čára, zvýrazněné body),
    //       details(point) -> další řádky tooltipu, withTime (čas v tooltipu)
    function timeChart(id, seriesByName, opts) {
        const el = document.getElementById(id);
        if (!el || !window.Chart) return;
        const p = setup();
        const o = Object.assign({ decimals: 0, unit: "", thin: false }, opts);
        const names = Object.keys(seriesByName);
        const total = names.reduce((n, name) => n + seriesByName[name].length, 0);
        const dense = total > 150;
        const datasets = names.map((name, i) => {
            const color = p.series[i % p.series.length];
            return {
                label: name,
                data: seriesByName[name].map((pt) => ({ x: toTime(pt.x), y: pt.y, meta: pt })),
                borderColor: o.thin ? fade(color, 0.45) : color,
                backgroundColor: color,
                borderWidth: o.thin ? 1.5 : 2,
                pointRadius: o.thin ? (dense ? 2 : 3) : (dense ? 0 : 3),
                pointHoverRadius: 6,
                pointBackgroundColor: color,
                pointBorderColor: p.surface,
                pointBorderWidth: dense ? 0 : 1,
                tension: 0,
            };
        });
        const a = axes(o.unit, o.beginAtZero === true);
        const fmt = nf(o.decimals);
        const xs = datasets.flatMap((d) => d.data.map((pt) => pt.x));
        const day = 86400000;  // osa přesně podle dat (lineární osa by zaokrouhlovala až o rok)
        const xMin = Math.min(...xs) - day, xMax = Math.max(...xs) + day;
        return new Chart(el, {
            type: "line",
            data: { datasets },
            options: {
                maintainAspectRatio: false,
                parsing: false,
                interaction: { mode: "nearest", axis: "xy", intersect: false },
                scales: {
                    x: { type: "linear", min: xMin, max: xMax, grid: { display: false }, afterBuildTicks: monthTicks,
                         ticks: { maxRotation: 0, autoSkip: false, callback: monthLabel } },
                    y: { ...a.y, ticks: { callback: (v) => fmt.format(v) } },
                },
                plugins: {
                    legend: { display: names.length > 1, position: "top", align: "start" },
                    tooltip: {
                        callbacks: {
                            title: (items) => items.length ? dateLabel(items[0].parsed.x, o.withTime) : "",
                            label: (c) => {
                                const suffix = o.valueSuffix ? o.valueSuffix(c.raw.meta) : o.unit;
                                return `${c.dataset.label}: ${fmt.format(c.parsed.y)} ${suffix}`;
                            },
                            afterLabel: (c) => (o.details ? o.details(c.raw.meta) : []),
                        },
                    },
                },
            },
        });
    }

    // Skládaný sloupcový graf měsíčních nákladů (palivo / servis / výdaje)
    function monthlyCosts(id, data) {
        const el = document.getElementById(id);
        if (!el || !window.Chart) return;
        const p = setup();
        const mk = (label, values, color) => ({
            label, data: values, backgroundColor: color,
            borderColor: p.surface, borderWidth: { top: 2 }, borderRadius: 4, borderSkipped: "start",
            maxBarThickness: 36,
        });
        const a = axes("Kč");
        return new Chart(el, {
            type: "bar",
            data: {
                labels: data.monthly_labels.map(formatX),
                datasets: [
                    mk("Palivo", data.monthly_fuel, p.series[0]),
                    mk("Servis", data.monthly_service, p.series[1]),
                    mk("Výdaje", data.monthly_expense, p.series[2]),
                ],
            },
            options: {
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                scales: { x: { ...a.x, stacked: true }, y: { ...a.y, stacked: true } },
                plugins: {
                    legend: { position: "top", align: "start" },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.dataset.label}: ${nf(0).format(c.parsed.y)} Kč`,
                            footer: (items) => `Celkem: ${nf(0).format(items.reduce((s, i) => s + i.parsed.y, 0))} Kč`,
                        },
                    },
                },
            },
        });
    }

    // Jednoduchý sloupcový graf po měsících (labels "YYYY-MM")
    function monthlyBars(id, labels, values, label, unit) {
        const el = document.getElementById(id);
        if (!el || !window.Chart) return;
        const p = setup();
        const a = axes(unit);
        return new Chart(el, {
            type: "bar",
            data: {
                labels: labels.map(formatX),
                datasets: [{ label, data: values, backgroundColor: p.series[0], borderRadius: 4,
                             borderSkipped: "start", maxBarThickness: 36 }],
            },
            options: {
                maintainAspectRatio: false,
                scales: a,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (c) => `${label}: ${nf(0).format(c.parsed.y)} ${unit}` } },
                },
            },
        });
    }

    // Vývoj kilometrů s přepínačem: "zero" = najeto od prvního bodu řady, "actual" = stav tachometru.
    // Body: {x, y, odo?} - odo je skutečný stav (když chybí, bere se y). Tlačítka: data-chart-mode="<id>" data-mode="…"
    function odometerChart(id, seriesByName, startMode) {
        const el = document.getElementById(id);
        if (!el || !window.Chart) return;
        const fmt = nf(0);
        const buttons = document.querySelectorAll('[data-chart-mode="' + id + '"]');
        let chart = null;
        function draw(mode) {
            if (chart) chart.destroy();
            const series = {};
            Object.keys(seriesByName).forEach((name) => {
                const pts = seriesByName[name];
                const base = pts.length ? (pts[0].odo != null ? pts[0].odo : pts[0].y) : 0;
                series[name] = pts.map((pt) => {
                    const odo = pt.odo != null ? pt.odo : pt.y;
                    return Object.assign({}, pt, { odo, y: mode === "zero" ? odo - base : odo });
                });
            });
            chart = timeChart(id, series, {
                unit: "km", beginAtZero: mode === "zero",
                details: (pt) => (mode === "zero" ? [`Tachometr: ${fmt.format(pt.odo)} km`] : []),
            });
            buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
        }
        buttons.forEach((b) => b.addEventListener("click", () => draw(b.dataset.mode)));
        draw(startMode || "zero");
    }

    function unitOf(fuelName) {
        return /elekt/i.test(fuelName) ? "kWh" : (/cng/i.test(fuelName) ? "kg" : "l");
    }

    function readData(id) {
        const el = document.getElementById(id || "chart-data");
        return el ? JSON.parse(el.textContent) : null;
    }

    return { lineChart, timeChart, monthlyCosts, monthlyBars, odometerChart, unitOf, readData };
})();
