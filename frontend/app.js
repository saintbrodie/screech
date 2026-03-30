async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        document.getElementById('ai-text').innerText = data.status;
        document.getElementById('ai-count').innerText = data.hawk_count;
        document.getElementById('stream-sys').innerText = 'Stream ' + data.stream_health;
        
        if (data.last_updated) {
            const date = new Date(data.last_updated * 1000);
            document.getElementById('ai-time').innerText = date.toLocaleTimeString();
        }
    } catch (err) {
        console.error("Error fetching AI status", err);
    }
}

const weatherCodes = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    95: "Thunderstorm"
};

async function fetchWeather() {
    try {
        const res = await fetch('/api/weather');
        const data = await res.json();
        
        if (!data.error) {
            document.getElementById('w-temp').innerText = Math.round(data.temperature_2m);
            document.getElementById('w-feels').innerText = Math.round(data.apparent_temperature);
            document.getElementById('w-humid').innerText = data.relative_humidity_2m;
            document.getElementById('w-wind').innerText = Math.round(data.wind_speed_10m);
            
            const desc = weatherCodes[data.weather_code] || "Conditions OK";
            const locationEl = document.querySelector('.location');
            if (locationEl) locationEl.innerText = `Falls Church, VA • ${desc}`;
        }
    } catch (err) {
        console.error("Error fetching weather", err);
    }
}

async function fetchFact() {
    try {
        const res = await fetch('/api/facts');
        const data = await res.json();
        
        document.getElementById('fact-text').innerText = `"${data.fact}"`;
    } catch (err) {
        console.error("Error fetching fact", err);
    }
}

function init() {
    fetchStatus();
    fetchWeather();
    fetchFact();
    
    // Polling intervals
    setInterval(fetchStatus, 3000); // 3 seconds for AI updates
    setInterval(fetchWeather, 600000); // 10 minutes for weather
    setInterval(fetchFact, 15000); // 15 seconds for facts
}

document.addEventListener('DOMContentLoaded', init);
