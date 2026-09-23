#  test using Luxonis OAK-D camera and OpenCV to stream video to a React dashboard via Flask and Firebase


import cv2
import os
import time
import socket
import firebase_admin
from firebase_admin import credentials, db
from flask import Flask, Response

# 1. Initialize Firebase (Use the exact same path/URL as your SG01 setup)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, "..", "serviceAccountKey.json") # Change this to your actual file path
DATABASE_URL = "https://sphere-guard-2025-default-rtdb.asia-southeast1.firebasedatabase.app/" # Change this!

cred = credentials.Certificate(CREDENTIALS_PATH)
firebase_admin.initialize_app(cred, {'databaseURL': DATABASE_URL})

app = Flask(__name__)

# Initialize Camera (0 is the default USB or V4L2 camera)
camera = cv2.VideoCapture(0, cv2.CAP_V4L2)

def get_ip_address():
    """Helper function to grab the Pi's local Wi-Fi IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def generate_frames():
    """Captures frames from the camera and encodes them for web streaming."""
    while True:
        success, frame = camera.read()
        if not success:
            break
        else:
            # Resize to 640x480 for a smooth, low-latency stream
            frame = cv2.resize(frame, (640, 480))
            # Compress to JPEG
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            frame = buffer.tobytes()
            
            # Yield the frame in byte format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/stream')
def video_feed():
    """The route the React app will connect to."""
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    # 2. Get IP and format the URL
    pi_ip = get_ip_address()
    stream_url = f"http://{pi_ip}:5000/stream"
    
    print(f"Starting camera server on: {stream_url}")
    
    # 3. Update Firebase so the React app knows where to look
    cam_ref = db.reference('robots/sg02/system/camera')
    cam_ref.update({
        'status': 'ONLINE',
        'url': stream_url,
        'timestamp': int(time.time() * 1000)
    })

    try:
        # Run the server on all network interfaces
        app.run(host='0.0.0.0', port=5000, threaded=True)
    except KeyboardInterrupt:
        print("\nStopping camera...")
    finally:
        # Set status to offline when script is closed
        cam_ref.update({'status': 'OFFLINE', 'url': ''})
        camera.release()