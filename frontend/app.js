let lastStatus = "";
let notificationsEnabled = false;

document.getElementById('notify-btn').addEventListener('click', async () => {
    if (Notification.permission === 'granted') {
        notificationsEnabled = true;
        document.getElementById('notify-btn').innerText = "Alerts [ON]";
    } else if (Notification.permission !== 'denied') {
        const perm = await Notification.requestPermission();
        if (perm === 'granted') {
            notificationsEnabled = true;
            document.getElementById('notify-btn').innerText = "Alerts [ON]";
        }
    }
});


const weatherCodes = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    95: "Thunderstorm"
};


async function fetchAll() {
    try {
        const res = await fetch('/api/data');
        const data = await res.json();
        
        // 1. Update Status
        const status = data.status;
        document.getElementById('ai-text').innerText = status.status;
        document.getElementById('ai-count').innerText = status.hawk_count;
        document.getElementById('ai-behavior').innerText = status.behavior || "Unknown";
        document.getElementById('stream-sys').innerText = 'Stream ' + status.stream_health;
        
        if (status.last_updated) {
            const date = new Date(status.last_updated * 1000);
            document.getElementById('ai-time').innerText = date.toLocaleTimeString();
        }
        
        if (lastStatus !== "" && lastStatus !== status.status && notificationsEnabled) {
            new Notification("Hawk Tracker Update", { body: status.status });
        }
        lastStatus = status.status;

        // 2. Update Timeline
        const list = document.getElementById('timeline-list');
        list.innerHTML = '';
        if (data.timeline.length === 0) {
            list.innerHTML = '<li class="empty-state">No events recently.</li>';
        } else {
            data.timeline.forEach(item => {
                const li = document.createElement('li');
                const d = new Date(item.timestamp + 'Z');
                li.innerHTML = `<strong>${d.toLocaleTimeString()}</strong>: ${item.event}`;
                list.appendChild(li);
            });
        }

        // 3. Update Weather (only if data exists)
        if (data.weather && !data.weather.error) {
            const w = data.weather;
            document.getElementById('w-temp').innerText = Math.round(w.temperature_2m);
            document.getElementById('w-humid').innerText = w.relative_humidity_2m;
            document.getElementById('w-wind').innerText = Math.round(w.wind_speed_10m);
            
            const weatherEmojis = {
                0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️", 45: "🌫️", 48: "🌫️",
                51: "🌧️", 53: "🌧️", 55: "🌧️", 61: "🌧️", 63: "🌧️", 65: "🌧️",
                71: "❄️", 73: "❄️", 75: "❄️", 95: "⛈️", 96: "⛈️", 99: "⛈️"
            };
            
            const emoji = weatherEmojis[w.weather_code] || "🛰️";
            const iconEl = document.getElementById('w-icon');
            if (iconEl) iconEl.innerText = emoji;
            
            const desc = weatherCodes[w.weather_code] || "Conditions OK";
            const locationEl = document.querySelector('.location');
            if (locationEl) locationEl.innerText = `Falls Church, VA • ${desc}`;
        }

        // 4. Update Facts (only rotated on the server side)
        if (data.fact) {
            document.getElementById('fact-text').innerText = data.fact;
        }

    } catch (err) {
        console.error("Critical Poll Error", err);
    }
}

function init() {
    fetchAll();
    
    // Unified optimal polling (5 seconds - reduces noise while remaining responsive)
    setInterval(fetchAll, 5000); 
}

document.addEventListener('DOMContentLoaded', init);
