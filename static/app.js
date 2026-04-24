let chart = null;
let currentRange = "1M";

const buttons = document.querySelectorAll(".range-btn");
const latestPriceEl = document.getElementById("latestPrice");
const latestDateEl = document.getElementById("latestDate");
const pointCountEl = document.getElementById("pointCount");
const refreshBtn = document.getElementById("refreshBtn");
const statusRowEl = document.getElementById("statusRow");

function formatPrice(value) {
    return "$" + Number(value || 0).toLocaleString(undefined, {
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
    });
}

function formatDateLabel(timestamp) {
    const d = new Date(timestamp);
    return d.toLocaleDateString([], { month: "numeric", day: "numeric", year: "2-digit" });
}

function formatFullDate(timestamp) {
    const d = new Date(timestamp);
    return d.toLocaleString([], {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit"
    });
}

function visibleLabels(points) {
    const maxLabels = 6;
    const step = Math.max(1, Math.ceil(points.length / maxLabels));
    return points.map((p, i) => {
        if (i === 0 || i === points.length - 1 || i % step === 0) {
            return formatDateLabel(p.timestamp_utc);
        }
        return "";
    });
}

async function loadHistory(range = currentRange) {
    const response = await fetch(`/api/history?range=${encodeURIComponent(range)}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`History HTTP ${response.status}`);

    const data = await response.json();
    const points = data.points || [];

    if (!points.length) {
        latestPriceEl.textContent = "$--";
        latestDateEl.textContent = "No price history found.";
        pointCountEl.textContent = "0 points";
        return;
    }

    const latest = data.latest || points[points.length - 1];
    latestPriceEl.textContent = formatPrice(latest.price);
    latestDateEl.textContent = `Latest saved price: ${formatFullDate(latest.timestamp_utc)}`;
    pointCountEl.textContent = `${points.length} point${points.length === 1 ? "" : "s"}`;

    const labels = visibleLabels(points);
    const prices = points.map(p => Number(p.price));

    const ctx = document.getElementById("priceChart").getContext("2d");
    if (chart) chart.destroy();

    chart = new Chart(ctx, {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: `LEMNI ${range}`,
                data: prices,
                borderColor: "#fbbf24",
                backgroundColor: "rgba(251,191,36,0.14)",
                borderWidth: 2,
                pointRadius: points.length < 45 ? 3 : 0,
                tension: 0.25,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: items => {
                            const index = items[0].dataIndex;
                            return formatFullDate(points[index].timestamp_utc);
                        },
                        label: item => formatPrice(item.parsed.y)
                    }
                }
            },
            scales: {
                x: {
                    ticks: { color: "#cbd5e1", autoSkip: false, maxRotation: 0 },
                    grid: { color: "rgba(255,255,255,0.08)" }
                },
                y: {
                    ticks: {
                        color: "#cbd5e1",
                        callback: value => "$" + Number(value).toFixed(2)
                    },
                    grid: { color: "rgba(255,255,255,0.08)" }
                }
            }
        }
    });
}

buttons.forEach(btn => {
    btn.addEventListener("click", async () => {
        buttons.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        currentRange = btn.dataset.range;
        await loadHistory(currentRange);
    });
});

refreshBtn.addEventListener("click", async () => {
    refreshBtn.disabled = true;
    refreshBtn.textContent = "Refreshing...";
    try {
        await fetch("/api/refresh", { method: "POST", cache: "no-store" });
        await loadHistory(currentRange);
        await loadStatus();
    } finally {
        refreshBtn.disabled = false;
        refreshBtn.textContent = "Refresh now";
    }
});

loadHistory(currentRange).catch(err => {
    console.error(err);
    latestDateEl.textContent = "Could not load chart data.";
});


async function loadStatus() {
    if (!statusRowEl) return;
    try {
        const response = await fetch('/api/status', { cache: 'no-store' });
        if (!response.ok) throw new Error(`Status HTTP ${response.status}`);
        const data = await response.json();
        const lf = data.last_fetch || {};
        const when = lf.timestamp_utc ? formatFullDate(lf.timestamp_utc) : 'not yet';
        const price = lf.price ? ` at ${formatPrice(lf.price)}` : '';
        statusRowEl.textContent = `Background updater: every ${data.fetch_interval_minutes} minutes. Last fetch: ${lf.status || 'unknown'} ${when}${price}.`;
    } catch (err) {
        statusRowEl.textContent = 'Background updater: status unavailable.';
        console.error(err);
    }
}

loadStatus();
setInterval(loadStatus, 60000);