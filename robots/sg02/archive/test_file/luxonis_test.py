# This is a test script to verify that the Luxonis OAK-D camera is working correctly with DepthAI.

import cv2
import depthai as dai

# 1. Create pipeline
pipeline = dai.Pipeline()

# 2. Define sources and outputs (Use this specific syntax)
cam_rgb = pipeline.create(dai.node.ColorCamera)
xout_rgb = pipeline.create(dai.node.XLinkOut)

xout_rgb.setStreamName("rgb")

# 3. Properties
cam_rgb.setPreviewSize(640, 480)
cam_rgb.setInterleaved(False)
cam_rgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)

# 4. Linking
cam_rgb.preview.link(xout_rgb.input)

# 5. Connect and start
with dai.Device(pipeline) as device:
    q_rgb = device.getOutputQueue(name="rgb", maxSize=4, blocking=False)
    while True:
        in_rgb = q_rgb.get()
        frame = in_rgb.getCvFrame()
        cv2.imshow("Luxonis OAK-D", frame)
        if cv2.waitKey(1) == ord('q'):
            break

cv2.destroyAllWindows()
