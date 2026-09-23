const { onValueUpdated } = require("firebase-functions/v2/database");
const admin = require("firebase-admin");

admin.initializeApp();
const db = admin.firestore();

const THROTTLE_MS = 30 * 1000; // 30 seconds

// Notice the v2 trigger syntax: we pass the path directly, and use the 'event' object
// exports.archiveTelemetry = onValueUpdated("/robots/sg01", async (event) => {
exports.archiveTelemetry = onValueUpdated(
  {
    ref: "/robots/sg01",
    region: "asia-southeast1", 
    instance: "sphere-guard-2025-default-rtdb" 
  }, 
  async (event) => {
    
    // In v2, the data sits inside event.data
    const data = event.data.after.val();
    if (!data) return null;

    // 1. Check if an inspection is actively running
    const activeSessionId = data.system?.activeSessionId;
    if (!activeSessionId) {
        // If no session is active, do not log anything to Firestore
        return null; 
    }

    const lastLogRef = db.collection('system_metadata').doc('sg01_last_log');

    try {
        const lastLogDoc = await lastLogRef.get();
        const now = Date.now();

        // 2. Enforce the 30-second throttle
        if (lastLogDoc.exists) {
            const lastTimestamp = lastLogDoc.data().timestamp;
            if (now - lastTimestamp < THROTTLE_MS) {
                return null; 
            }
        }

        await lastLogRef.set({ timestamp: now });

        // 3. Map the exact JSON data to the correct Session Sub-collection
        await db.collection('inspection_sessions')
          .doc(activeSessionId)
          .collection('telemetry_logs')
          .add({
            savedAt: admin.firestore.FieldValue.serverTimestamp(), 
            
            environment: {
              temperature: data.environment?.temperature || null,
              humidity: data.environment?.humidity || null,
              gas_ppm: data.environment?.gas?.ppm || null,
              gas_quality: data.environment?.gas?.quality || null,
              light: data.environment?.light || null
            },
            system: {
              battery_pct: data.battery?.percentage || null,
              battery_volts: data.battery?.voltage || null,
              mcu_temp: data.system?.temperature?.mcu || null,
              motor_driver_temp: data.system?.temperature?.motorDriver || null,
              rssi: data.system?.connection?.rssi || null
            },
            kinematics: {
              pitch: data.telemetry?.imu_mpu6050?.pitch || null,
              roll: data.telemetry?.imu_mpu6050?.roll || null,
              speed_cmd: data.control?.movement?.speed || null,
              steering_cmd: data.control?.steering_command || null
            },
            safety: {
              obstacle_cm: data.obstacle?.distanceCm || null,
              emergency_stop: data.control?.emergencyStop || false
            }
          });
          
        console.log(`Logged data to session: ${activeSessionId}`);
        return null;

    } catch (error) {
        console.error("Error writing to Firestore:", error);
        return null;
    }
});