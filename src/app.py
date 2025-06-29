from flask import Flask, render_template, url_for, redirect, request, make_response, jsonify, Response
from flask_mysqldb import MySQL
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from MySQLdb.cursors import DictCursor
from flask_socketio import SocketIO
import socket
import struct
import cv2
import numpy as np
import threading
import os
import datetime
import mysql.connector
import json
import redis
import json
import base64

app = Flask(__name__) 
app.secret_key = '5247013322530115'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

r = redis.Redis(host='localhost', port=6379, db=0)



HOST = '127.0.0.1'
PORT = 9999



# MySQL Configuration
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = '1234'
app.config['MYSQL_DB'] = 'parkpatrol'

mysql = MySQL(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


class User(UserMixin):
    def __init__(self, id_, username):
        self.id = id_
        self.username = username

    @staticmethod
    def get(user_id):
        cur = mysql.connection.cursor()
        cur.execute("SELECT UserID, Username FROM User WHERE UserID = %s", (user_id,))
        user = cur.fetchone()
        cur.close()
        if user:
            return User(user[0], user[1])
        return None

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)



# def gen_frames():
#     try:
#         s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#         s.connect((HOST, PORT))
#     except Exception as e:
#         print(f"[ERROR] Could not connect: {e}")
#         # Return 1 error frame to stop spinner
#         img = np.zeros((480, 640, 3), dtype=np.uint8)
#         cv2.putText(img, 'Connection Failed', (50, 240), cv2.FONT_HERSHEY_SIMPLEX,
#                     1, (0, 0, 255), 2, cv2.LINE_AA)
#         ret, jpeg = cv2.imencode('.jpg', img)
#         if ret:
#             yield (b'--frame\r\n'
#                    b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
#         return

#     # Normal streaming
#     data = b''
#     payload_size = struct.calcsize(">L")
#     while True:
#         try:
#             while len(data) < payload_size:
#                 packet = s.recv(4096)
#                 if not packet:
#                     raise ConnectionError("Empty packet received")
#                 data += packet

#             packed_msg_size = data[:payload_size]
#             data = data[payload_size:]
#             msg_size = struct.unpack(">L", packed_msg_size)[0]

#             while len(data) < msg_size:
#                 packet = s.recv(4096)
#                 if not packet:
#                     raise ConnectionError("Empty packet during frame read")
#                 data += packet

#             frame_data = data[:msg_size]
#             data = data[msg_size:]

#             frame = np.frombuffer(frame_data, dtype=np.uint8)
#             img = cv2.imdecode(frame, cv2.IMREAD_COLOR)
#             if img is None:
#                 continue

#             ret, jpeg = cv2.imencode('.jpg', img)
#             if not ret:
#                 continue

#             yield (b'--frame\r\n'
#                    b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
#         except Exception as e:
#             print(f"[Streaming Error] {e}")
#             break

def gen_frames():
    while True:
        try:
            encoded_frame = r.get("latest_frame")
            if not encoded_frame:
                continue

            jpeg = base64.b64decode(encoded_frame)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')
        except Exception as e:
            print(f"[Redis Stream Error] {e}")
            break

def listen_for_violations():
    pubsub = r.pubsub()
    pubsub.subscribe('violation_channel')
    for message in pubsub.listen():
        if message['type'] == 'message':
            data = json.loads(message['data'])
            print("New Violation:", data)
            socketio.emit('violation_detected', data)



@app.route('/')
def index():
        return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
        if request.method == 'POST':
            username = request.form['username']
            password_input = request.form['password']
            cur = mysql.connection.cursor()
            cur.execute("SELECT UserID, Password FROM User WHERE Username = %s", (username,))
            user = cur.fetchone()
            cur.close()
            
            if user:
                login_user(User(user[0], username))
                return redirect(url_for('video'))

        return render_template('login.html')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video')
def video():
    return render_template('video.html', request=request)

@app.route('/dashboard')
def dashboard():
    cursor = mysql.connection.cursor(DictCursor)
    cursor.execute("""
            SELECT DATE(ViolationDate) as day, COUNT(*) as total
            FROM violation
            WHERE ViolationDate >= NOW() - INTERVAL 7 DAY
            GROUP BY day
        """)
    daily_data = cursor.fetchall()

    cursor.execute("""
            SELECT l.LocationName, COUNT(*) as total
            FROM violation v
            JOIN location l ON v.LocationID = l.LocationID
            GROUP BY l.LocationName
        """)

    location_data = cursor.fetchall()

    cursor.execute("""
                    SELECT 
                        l.LocationName, 
                        v.ViolationDate, 
                        v.image_path 
                    FROM 
                        violation AS v 
                    LEFT JOIN 
                        location AS l 
                    ON 
                        v.LocationID = l.LocationID;""")
    violation_list = cursor.fetchall()

    print("daily_data", daily_data)
    print("location_data", location_data)

    return render_template('dashboard.html', daily_data=daily_data, location_data=location_data, violation_list = violation_list)

@app.route('/api/violations')
def get_violations():
    cursor = mysql.connection.cursor(DictCursor)
    cursor.execute("SELECT * FROM violation ORDER BY ViolationDate DESC")
    row = cursor.fetchall()
    cursor.close()

    return jsonify(row)

@app.route('/api/notifications')
def get_notifications():
    cursor = mysql.connection.cursor(DictCursor)
    cursor.execute("SELECT * FROM violation WHERE is_read = FALSE ORDER BY ViolationDate DESC LIMIT 50")
    notifications = cursor.fetchall()
    cursor.close()
    return jsonify(notifications)

if __name__ == "__main__":

    socketio.start_background_task(listen_for_violations)
    socketio.run(app, debug=True)
    