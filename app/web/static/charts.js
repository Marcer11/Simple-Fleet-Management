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

    function unitOf(fuelName) {
        return /elekt/i.test(fuelName) ? "kWh" : (/cng/i.test(fuelName) ? "kg" : "l");
    }

    function readData(id) {
        const el = document.getElementById(id || "chart-data");
        return el ? JSON.parse(el.textContent) : null;
    }

    return { lineChart, monthlyCosts, unitOf, readData };
})();
