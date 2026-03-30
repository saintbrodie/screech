import asyncio
import cv2
import torch
original_load = torch.load
def safe_load(*args, **kwargs):
    kwargs['weights_only'] = False
    return original_load(*args, **kwargs)
torch.load = safe_load
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ultralytics import YOLO
import requests
from yt_dlp import YoutubeDL
import time
import sqlite3
import numpy as np
import datetime
import os

from fastapi.staticfiles import StaticFiles

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Initialize Database
conn = sqlite3.connect("hawk_data.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        event_text TEXT,
        hawk_count INTEGER
    )
''')
conn.commit()

def log_event(text, count):
    cursor.execute("INSERT INTO events (event_text, hawk_count) VALUES (?, ?)", (text, count))
    conn.commit()

# Global state
nest_state = {
    "status": "Initializing AI Model...",
    "hawk_count": 0,
    "last_updated": time.time(),
    "stream_health": "Connecting",
    "behavior": "Unknown"
}

facts = [
    "Red-shouldered Hawks are named for the reddish-brown feathers on their wrists, not their actual shoulders.",
    "Their distinctive 'kee-aah' call is often mimicked by Blue Jays.",
    "Young Red-shouldered Hawks can aim their waste out of the nest to keep it clean.",
    "They are excellent at sky-dancing! During breeding, pairs fly high and call to each other.",
    "These hawks prefer wetland habitats like swamps, bottomlands, and rivers.",
    "In flight, Red-shouldered Hawks have a translucent crescent 'window' near their wingtips.",
    "Female Red-shouldered hawks are noticeably larger than the males.",
    "Red-shouldered hawks possess incredible eyesight, roughly 2-3 times more acute than a human's.",
    "They typically return to the same territory and reuse the same nest year after year."
]

model = None
video_id = "HRhToy9dA-Q"

def get_stream_url(vid):
    ydl_opts = {'format': 'best', 'quiet': True, 'no_warnings': True}
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
        return info['url']

async def cv_processor():
    global model, nest_state
    
    hawk_cy_history = []
    last_event_state = -1 # Used to detect changes (0=empty, 1=Freya, 2=Finn, 3=both)
    pending_state_code = -1
    pending_state_count = 0
    
    # Load YOLOv8 Nano for speed
    try:
        model = YOLO("yolov8n.pt") 
    except Exception as e:
        nest_state["status"] = f"Error loading model: {e}"
        nest_state["stream_health"] = "Offline"
        return

    nest_state["status"] = "Connecting to YouTube stream..."
    empty_frames_count = 0
    
    while True:
        try:
            # 1. Fetch stream URL
            stream_url = await asyncio.to_thread(get_stream_url, video_id)
            
            # Prevent blocking ASGI main loop
            cap = await asyncio.to_thread(cv2.VideoCapture, stream_url)

            is_opened = await asyncio.to_thread(cap.isOpened)
            if not is_opened:
                nest_state["stream_health"] = "Failed to open stream"
                await asyncio.to_thread(cap.release)
                await asyncio.sleep(10)
                continue

            nest_state["stream_health"] = "Live"
            
            # Read a few frames to clear the buffer
            for _ in range(5):
                ret, frame = await asyncio.to_thread(cap.read)
            
            if ret and frame is not None:
                # 2. Inference: COCO class 14 is 'bird', lower conf to 0.15 to increase sensitivity
                results = await asyncio.to_thread(model.predict, frame, classes=[14], conf=0.15, verbose=False)
                
                boxes = results[0].boxes
                h, w = frame.shape[:2]
                
                valid_boxes = []
                for b in boxes:
                    co = b.xyxy[0].cpu().numpy()
                    area = (co[2] - co[0]) * (co[3] - co[1])
                    if area / (h * w) >= 0.015:  # Ignore tiny false positives (e.g. bugs/shadows/distant birds)
                        valid_boxes.append(b)
                
                bird_count = len(valid_boxes)
                
                # Behavior tracking
                behavior = "Unknown"
                if bird_count == 1:
                    box = valid_boxes[0].xyxy[0].cpu().numpy()
                    cy = (box[1] + box[3]) / 2.0
                    hawk_cy_history.append(cy)
                    # Keep last 6 frames (30 seconds)
                    if len(hawk_cy_history) > 6:
                        hawk_cy_history.pop(0)
                        
                    if len(hawk_cy_history) >= 3:
                        variance = np.var(hawk_cy_history)
                        if variance < 35.0:  # low vertical movement variance
                            behavior = "Incubating / Resting"
                        else:
                            behavior = "Active / Feeding"
                else:
                    if len(hawk_cy_history) > 0:
                        hawk_cy_history.pop(0) # smooth clear instead of instant clear
                    
                nest_state["behavior"] = behavior
                
                nest_state["hawk_count"] = bird_count
                
                current_state_code = 0
                status_text = ""
                
                if bird_count == 0:
                    empty_frames_count += 1
                    if empty_frames_count >= 3:
                        status_text = "Nest appears empty"
                        current_state_code = 0
                else:
                    empty_frames_count = 0
                    if bird_count == 1:
                        # Differentiate Male vs Female by bounding box area ratio
                        box = valid_boxes[0].xyxy[0].cpu().numpy() # [x1, y1, x2, y2]
                        area = (box[2] - box[0]) * (box[3] - box[1])
                        ratio = area / (h * w)
                        
                        hawk_name = "Freya (Female)" if ratio > 0.08 else "Finn (Male)"
                        status_text = f"{hawk_name} is in the nest!"
                        current_state_code = 1 if ratio > 0.08 else 2
                        nest_state["_debug_ratio"] = float(ratio)
                    else:
                        status_text = "Freya & Finn are in the nest together!"
                        current_state_code = 3
                
                # Use the delayed status update logic to protect against jitter
                if status_text:
                    nest_state["status"] = status_text
                
                # State change detection trigger with 3-frame debounce
                if status_text:
                    if last_event_state == -1:
                        last_event_state = current_state_code
                        # don't log the very first arbitrary state frame
                    elif current_state_code != last_event_state:
                        if current_state_code == pending_state_code:
                            pending_state_count += 1
                        else:
                            pending_state_code = current_state_code
                            pending_state_count = 1
                            
                        if pending_state_count >= 3:
                            last_event_state = current_state_code
                            
                            # Database-level deduplication
                            cursor.execute("SELECT event_text FROM events ORDER BY id DESC LIMIT 1")
                            last_db_row = cursor.fetchone()
                            if not last_db_row or last_db_row[0] != status_text:
                                log_event(status_text, bird_count)
                                
                            pending_state_count = 0
                    else:
                        pending_state_count = 0
                        
                nest_state["last_updated"] = time.time()
            
            await asyncio.to_thread(cap.release)
            
        except Exception as e:
            nest_state["stream_health"] = "Error"
            nest_state["status"] = f"Stream read error: {e}"
        
        # Poll every 5 seconds to reduce load
        await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cv_processor())

@app.get("/api/status")
def get_status():
    return nest_state

@app.get("/api/weather")
def get_weather():
    try:
        # Falls Church, VA coordinates
        lat = 38.8681
        lon = -77.2183
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m&temperature_unit=fahrenheit&wind_speed_unit=mph"
        response = requests.get(url).json()
        if "current" in response:
            return response["current"]
    except Exception:
        pass
    return {"error": "Could not fetch weather"}

@app.get("/api/facts")
def get_facts():
    import random
    return {"fact": random.choice(facts)}

@app.get("/api/timeline")
def get_timeline():
    cursor.execute("SELECT timestamp, event_text, hawk_count FROM events ORDER BY id DESC LIMIT 10")
    rows = cursor.fetchall()
    return [{"timestamp": r[0], "event": r[1], "count": r[2]} for r in rows]

app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")

