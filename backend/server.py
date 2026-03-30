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

from fastapi.staticfiles import StaticFiles

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global state
nest_state = {
    "status": "Initializing AI Model...",
    "hawk_count": 0,
    "last_updated": time.time(),
    "stream_health": "Connecting",
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
    ydl_opts = {'format': 'best', 'quiet': True}
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
        return info['url']

async def cv_processor():
    global model, nest_state
    
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
            cap = cv2.VideoCapture(stream_url)

            if not cap.isOpened():
                nest_state["stream_health"] = "Failed to open stream"
                await asyncio.sleep(10)
                continue

            nest_state["stream_health"] = "Live"
            
            # Read a few frames to clear the buffer
            for _ in range(5):
                ret, frame = cap.read()
            
            if ret and frame is not None:
                # 2. Inference: COCO class 14 is 'bird', lower conf to 0.15 to increase sensitivity
                results = await asyncio.to_thread(model.predict, frame, classes=[14], conf=0.15, verbose=False)
                
                boxes = results[0].boxes
                bird_count = len(boxes)
                
                nest_state["hawk_count"] = bird_count
                if bird_count == 0:
                    empty_frames_count += 1
                    if empty_frames_count >= 3:
                        nest_state["status"] = "Nest appears empty"
                else:
                    empty_frames_count = 0
                    if bird_count == 1:
                        # Differentiate Male vs Female by bounding box area ratio
                        box = boxes[0].xyxy[0].cpu().numpy() # [x1, y1, x2, y2]
                        area = (box[2] - box[0]) * (box[3] - box[1])
                        h, w = frame.shape[:2]
                        ratio = area / (h * w)
                        
                        # Female hawks are larger. Using 8% ratio as a threshold.
                        hawk_name = "Freya (Female)" if ratio > 0.08 else "Finn (Male)"
                        nest_state["status"] = f"{hawk_name} is in the nest!"
                        nest_state["_debug_ratio"] = float(ratio)
                    else:
                        nest_state["status"] = "Freya & Finn are in the nest together!"
                    
                nest_state["last_updated"] = time.time()
            
            cap.release()
            
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

app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")

