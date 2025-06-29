import base64
import socket
import struct
import cv2
import numpy as np
import time
import threading
import os
import datetime
import mysql.connector
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
import json
import redis

violated_set = set()  # Prevents duplicate entries
violation_logged = {}
save_dir = 'violation_photos'
os.makedirs(save_dir, exist_ok=True)
r = redis.Redis(host='localhost', port=6379, db=0)

def insert_violation(track_id, timestamp, image_path):
    try:
        conn = mysql.connector.connect(
            host='localhost',
            user='root',
            password='1234',
            database='parkpatrol'
        )
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO violation(ViolationDate, LocationID, image_path) VALUES (%s, %s, %s)",
            (timestamp, 1, image_path)
        )
        conn.commit()
        cursor.close()
        conn.close()
        print(f"[INFO] Violation inserted: ID={track_id}, Time={timestamp}")
    except mysql.connector.Error as err:
        print(f"[ERROR] MySQL Error: {err}")

class VideoStreamThread:
    def __init__(self, src):
        self.stream = cv2.VideoCapture(src)
        self.valid = self.stream.isOpened()
        if not self.valid:
            print(f"[ERROR] Failed to open RTSP stream: {src}")
            return
        self.stream.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.ret, self.frame = self.stream.read()
        self.stopped = False
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.update, daemon=True)
        self.thread.start()

    def update(self):
        while not self.stopped:
            ret, frame = self.stream.read()
            if not ret or frame is None or frame.size == 0:
                continue
            with self.lock:
                self.ret, self.frame = ret, frame

    def read(self):
        with self.lock:
            return self.ret, self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.stopped = True
        if self.thread.is_alive():
            self.thread.join()
        self.stream.release()

# Setup TCP server
HOST = '127.0.0.1'
PORT = 9999

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.bind((HOST, PORT))
server_socket.listen(2)
print("Waiting for client connection...")

model = YOLO('yolov8m.pt')
model.to('cuda')

tracker = DeepSort(max_age=30, n_init=3, embedder="mobilenet")


threshold = 0.25
CAR_CLASS_ID = 2 #Car is 2
points = np.array([[602,260],[699,247],[763,279],[671,291]], np.int32).reshape((-1,1,2))

car_timers = {}
inside_polygon_timers = {}

def is_inside_polygon(point, polygon):
    return cv2.pointPolygonTest(polygon, point, False) >= 0

print("Server is ready to accept connections...")

while True:

    # rtsp_url = 'rtsp://10.0.0.51'
    rtsp_url = 'http://192.168.196.8:8081/video'
    # rtsp_url = 'http://10.0.0.116:8081/video'
    stream = VideoStreamThread(rtsp_url)
    
    if not stream.valid:
        print(f"[ERROR] Could not open RTSP stream at {rtsp_url}. Closing client connection.")
        # conn.close()
        continue

    tracker = DeepSort(max_age=30, n_init=3, embedder="mobilenet")
    car_timers = {}
    inside_polygon_timers = {}

    try:
        while True:
            ret, frame = stream.read()
            if not ret or frame is None or frame.size == 0:
                break 
                # print("[WARNING] Invalid frame, skipping...")
                # continue

            results = model.predict(frame, conf=0.25, imgsz=864, iou=0.45, verbose=False)[0]

            cv2.polylines(frame, [points], True, (0,255,0), 2)

            detections = []
            for result in results.boxes.data.tolist():
                x1, y1, x2, y2, score, class_id = result
                x1, y1, x2, y2 = map(int, [x1, y1, x2, y2])
                if score > threshold and int(class_id) == CAR_CLASS_ID:
                    w, h = x2 - x1, y2 - y1
                    detections.append(([x1, y1, w, h], score, "car"))

            tracks = tracker.update_tracks(detections, frame=frame)

            for track in tracks:
                if not track.is_confirmed() or track.time_since_update > 1:
                    continue

                track_id = track.track_id
                now = time.time()

                if track_id not in car_timers:
                    car_timers[track_id] = now
                if track_id not in inside_polygon_timers:
                    inside_polygon_timers[track_id] = 0
                    

                ltrb = track.to_ltrb()
                x1, y1, x2, y2 = map(int, ltrb)
                cx, cy = int((x1+x2)/2), int((y1+y2)/2)
                in_polygon = is_inside_polygon((cx, cy), points)
                if in_polygon:
                    inside_polygon_timers[track_id] += 1/30.0
                    
                    # Store violation in database procedure
                    if inside_polygon_timers[track_id] >= 2 and not violation_logged.get(track_id, False):
                        image_filename = f"violation_{track_id}_{int(time.time())}.jpg"
                        image_path = os.path.join(save_dir, image_filename)

                        if not os.path.exists(image_path):  # Only save once
                            car_image = frame[y1:y2, x1:x2]
                            cv2.imwrite(image_path, car_image)

                            # Save to MySQL
                            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            insert_violation(track_id, timestamp, image_path)
                            
                            message = json.dumps({
                                                'track_id': track_id,
                                                'timestamp': timestamp,
                                                'image_path': image_path
                                            })

                            r.publish('violation_channel', message)
                            violation_logged[track_id] = True

                elapsed_total = int(now - car_timers[track_id])
                inside_total = int(inside_polygon_timers[track_id])
                color = (0,0,255) if in_polygon else (0,255,0)

                cv2.rectangle(frame, (x1, y1), (x2, y2), (0,220,255), 1)
                label = f"ID {track_id} | Total {elapsed_total}s | In {inside_total}s"
                (label_w, label_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
                label_y = y1 - 10 if y1 - 10 > label_h else y1 + 15
                cv2.rectangle(frame, (x1, label_y - label_h - 4), (x1 + label_w + 4, label_y + baseline - 4), color, -1)
                cv2.putText(frame, label, (x1+2, label_y-2), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,0,0), 1)

            try:
                ret, jpeg = cv2.imencode('.jpg', frame)
                if ret:
                    r.set("latest_frame", base64.b64encode(jpeg.tobytes()))
            except Exception as e:
                print("[ERROR] Encoding failed:", e)

    except Exception as e:
        print(f"Connection with {addr} ended. Reason: {e}")
    finally:
        stream.stop()
        # conn.close()