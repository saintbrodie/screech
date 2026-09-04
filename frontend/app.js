let lastStatus = "";

function notificationsAvailable() {
    return "Notification" in window && window.isSecureContext;
}

let notificationsEnabled =
    localStorage.getItem("screech-notifications") === "on" &&
    notificationsAvailable() &&
    Notification.permission === "granted";

const notifyButton = document.getElementById("notify-btn");

function renderNotifyState() {
    if (!("Notification" in window)) {
        notifyButton.innerText = "Alerts [N/A]";
        notifyButton.disabled = true;
        return;
    }
    if (!window.isSecureContext) {
        notifyButton.innerText = "Alerts [HTTPS]";
        notifyButton.disabled = true;
        notifyButton.title = "Browser notifications require HTTPS or localhost.";
        return;
    }
    notifyButton.innerText = notificationsEnabled ? "Alerts [ON]" : "Alerts [OFF]";
}

notifyButton.addEventListener("click", async () => {
    if (!notificationsAvailable()) return;

    if (notificationsEnabled) {
        notificationsEnabled = false;
        localStorage.removeItem("screech-notifications");
        renderNotifyState();
        return;
    }

    if (Notification.permission === "denied") {
        notifyButton.innerText = "Alerts [BLOCKED]";
        return;
    }

    const permission =
        Notification.permission === "granted"
            ? "granted"
            : await Notification.requestPermission();

    notificationsEnabled = permission === "granted";
    if (notificationsEnabled) {
        localStorage.setItem("screech-notifications", "on");
    }
    renderNotifyState();
});

const weatherCodes = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
};

const weatherEmojis = {
    0: "☀️",
    1: "🌤️",
    2: "⛅",
    3: "☁️",
    45: "🌫️",
    48: "🌫️",
    51: "🌧️",
    53: "🌧️",
    55: "🌧️",
    61: "🌧️",
    63: "🌧️",
    65: "🌧️",
    71: "❄️",
    73: "❄️",
    75: "❄️",
    95: "⛈️",
    96: "⛈️",
    99: "⛈️",
};

function formatConfidence(value) {
    if (value === null || value === undefined) return "--";
    return `${Math.round(value * 100)}%`;
}

function renderVideo(video) {
    const iframe = document.getElementById("live-player");
    const placeholder = document.getElementById("video-placeholder");
    const embedUrl = video?.embed_url || null;

    if (embedUrl) {
        if (iframe.getAttribute("src") !== embedUrl) {
            iframe.setAttribute("src", embedUrl);
        }
        iframe.hidden = false;
        placeholder.hidden = true;
        return;
    }

    iframe.hidden = true;
    iframe.removeAttribute("src");
    placeholder.hidden = false;
    placeholder.textContent =
        "Fixture / non-embeddable source mode // AI analysis remains active";
}

function appendTimelineEvent(list, item) {
    const li = document.createElement("li");

    const line = document.createElement("div");
    line.className = "timeline-line";

    const timestamp = document.createElement("strong");
    const date = new Date(`${item.timestamp}Z`);
    timestamp.textContent = Number.isNaN(date.getTime())
        ? item.timestamp
        : date.toLocaleTimeString();

    const text = document.createElement("span");
    text.textContent = `: ${item.event}`;

    line.append(timestamp, text);
    li.appendChild(line);

    if (item.confidence !== null && item.confidence !== undefined) {
        const meta = document.createElement("div");
        meta.className = "timeline-meta";
        meta.textContent = `confidence ${formatConfidence(item.confidence)} • ${item.event_type}`;
        li.appendChild(meta);
    }

    if (item.snapshot_url) {
        const image = document.createElement("img");
        image.src = item.snapshot_url;
        image.alt = `Detection snapshot for ${item.event}`;
        image.loading = "lazy";
        image.className = "timeline-snapshot";
        li.appendChild(image);
    }

    list.appendChild(li);
}

function renderStats(stats) {
    const chart = document.getElementById("stats-chart");
    chart.innerHTML = "";

    const available = (stats || []).filter((day) => day.samples > 0);
    if (available.length === 0) {
        chart.innerHTML = '<div class="empty-state">Awaiting observation history...</div>';
        document.getElementById("today-occupancy").textContent = "--";
        document.getElementById("today-activity").textContent = "--";
        return;
    }

    const today = stats[stats.length - 1];
    document.getElementById("today-occupancy").textContent = `${today.occupancy_pct}%`;
    document.getElementById("today-activity").textContent = `${today.activity_pct}%`;

    stats.forEach((day) => {
        const row = document.createElement("div");
        row.className = "stat-row";

        const label = document.createElement("span");
        label.className = "stat-day";
        label.textContent = day.day.slice(5);

        const bars = document.createElement("div");
        bars.className = "stat-bars";

        const occupancy = document.createElement("div");
        occupancy.className = "stat-bar occupancy";
        occupancy.style.width = `${Math.max(0, Math.min(100, day.occupancy_pct))}%`;
        occupancy.title = `Occupancy ${day.occupancy_pct}%`;

        const activity = document.createElement("div");
        activity.className = "stat-bar activity";
        activity.style.width = `${Math.max(0, Math.min(100, day.activity_pct))}%`;
        activity.title = `Activity ${day.activity_pct}%`;

        bars.append(occupancy, activity);
        row.append(label, bars);
        chart.appendChild(row);
    });
}

async function fetchAll() {
    try {
        const res = await fetch("/api/data", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        renderVideo(data.video);

        const status = data.status;
        document.getElementById("ai-text").innerText = status.status;
        document.getElementById("ai-count").innerText = status.hawk_count;
        document.getElementById("ai-raw-count").innerText = status.raw_hawk_count;
        document.getElementById("ai-behavior").innerText = status.behavior || "Unknown";
        document.getElementById("ai-confidence").innerText = formatConfidence(status.confidence);
        document.getElementById("raw-scan").innerText = status.raw_status || "No scan yet";
        document.getElementById("stream-sys").innerText = `Source ${status.stream_health}`;

        if (status.last_updated) {
            const date = new Date(status.last_updated * 1000);
            document.getElementById("ai-time").innerText = date.toLocaleTimeString();
        }

        if (
            lastStatus !== "" &&
            lastStatus !== status.status &&
            notificationsEnabled &&
            notificationsAvailable() &&
            Notification.permission === "granted"
        ) {
            new Notification("S.C.R.E.E.C.H. Nest Update", { body: status.status });
        }
        lastStatus = status.status;

        const list = document.getElementById("timeline-list");
        list.innerHTML = "";
        if (!data.timeline || data.timeline.length === 0) {
            list.innerHTML = '<li class="empty-state">No stable state changes recorded yet.</li>';
        } else {
            data.timeline.forEach((item) => appendTimelineEvent(list, item));
        }

        if (data.weather) {
            const w = data.weather;
            document.getElementById("w-temp").innerText = Math.round(w.temperature_2m);
            document.getElementById("w-humid").innerText = w.relative_humidity_2m;
            document.getElementById("w-wind").innerText = Math.round(w.wind_speed_10m);
            document.getElementById("w-icon").innerText = weatherEmojis[w.weather_code] || "🛰️";
            document.querySelector(".location").innerText =
                `Falls Church, VA • ${weatherCodes[w.weather_code] || "Conditions OK"}`;
        } else {
            document.querySelector(".location").innerText = "Falls Church, VA • Weather unavailable";
        }

        if (data.fact) {
            document.getElementById("fact-text").innerText = data.fact;
        }

        renderStats(data.stats);

        const frameAge = data.health?.frame_age_seconds;
        const ageText = frameAge === null || frameAge === undefined ? "no frame" : `${frameAge}s ago`;
        document.getElementById("health-text").innerText =
            `${data.health?.model || "model"} • frame ${ageText}`;
    } catch (err) {
        console.error("Critical Poll Error", err);
        document.getElementById("stream-sys").innerText = "API Offline";
        document.getElementById("health-text").innerText = "dashboard poll failed";
    }
}

function init() {
    renderNotifyState();
    fetchAll();
    setInterval(fetchAll, 5000);
}

document.addEventListener("DOMContentLoaded", init);
