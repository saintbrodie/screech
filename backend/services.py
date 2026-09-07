from __future__ import annotations

import random
import threading
import time
from typing import Any

import requests


FACTS = [
    "Red-shouldered Hawks are named for the reddish-brown feathers on their wrists, not their actual shoulders.",
    "Their distinctive 'kee-aah' call is often mimicked by Blue Jays.",
    "Young Red-shouldered Hawks can aim their waste out of the nest to keep it clean.",
    "They are excellent at sky-dancing! During breeding, pairs fly high and call to each other.",
    "These hawks prefer wetland habitats like swamps, bottomlands, and rivers.",
    "In flight, Red-shouldered Hawks have a translucent crescent 'window' near their wingtips.",
    "Female Red-shouldered hawks are noticeably larger than the males.",
    "Red-shouldered hawks possess incredible eyesight, roughly 2-3 times more acute than a human's.",
    "They typically return to the same territory and reuse the same nest year after year.",
    "The incubation period for Red-shouldered Hawks is approximately 32 to 40 days.",
    "Red-shouldered Hawks hunt primarily by stealth, swooping down from a perch to catch prey by surprise.",
    "Their diet consists mainly of small mammals, amphibians, and reptiles, giving them a very broad menu.",
    "While incredibly territorial, they have been known to share nesting areas with American Crows.",
    "Red-shouldered Hawk nests are usually built from sticks and lined with bark, leaves, and sprigs of evergreen.",
    "The oldest known wild Red-shouldered Hawk lived to be at least 25 years and 10 months old.",
]

_UNSET = object()


class TTLValue:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = max(1, ttl_seconds)
        self.value: Any = _UNSET
        self.expires_at = 0.0
        self.lock = threading.Lock()

    def get_or_update(self, loader):
        now = time.monotonic()
        with self.lock:
            if self.value is not _UNSET and now < self.expires_at:
                return self.value
            value = loader()
            self.value = value
            self.expires_at = now + self.ttl_seconds
            return value


class WeatherService:
    def __init__(self, latitude: float, longitude: float, ttl_seconds: int = 600) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.cache = TTLValue(ttl_seconds)

    def _fetch(self) -> dict[str, Any] | None:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "current": (
                "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "weather_code,wind_speed_10m"
            ),
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
        }
        try:
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            payload = response.json()
            return payload.get("current")
        except (requests.RequestException, ValueError):
            return None

    def get(self) -> dict[str, Any] | None:
        return self.cache.get_or_update(self._fetch)


class FactService:
    def __init__(self, ttl_seconds: int = 60) -> None:
        self.cache = TTLValue(ttl_seconds)

    def get(self) -> str:
        return self.cache.get_or_update(lambda: random.choice(FACTS))
