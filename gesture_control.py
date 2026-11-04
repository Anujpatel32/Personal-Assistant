import cv2
import mediapipe as mp
import pyautogui
import math
import time
import threading

# Disable pyautogui fail-safe to prevent thread crashes on corner hits
pyautogui.FAILSAFE = False

# Global state control flags
_keep_running = False
_active = False
SHOW_PREVIEW = False

# Cursor interpolation shared state
cursor_target_x = 0.0
cursor_target_y = 0.0
cursor_current_x = 0.0
cursor_current_y = 0.0
cursor_lock = threading.Lock()
cursor_active = False

mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils

class KalmanFilter2D:
    """A 2D Kalman Filter tracking position (x, y) and velocity (dx, dy) in pure Python."""
    def __init__(self, dt=1.0, process_noise=0.1, measurement_noise=1.5):
        self.dt = dt
        self.q = process_noise
        self.r = measurement_noise
        self.x = 0.0
        self.y = 0.0
        self.dx = 0.0
        self.dy = 0.0
        self.p_x = 1.0
        self.p_y = 1.0
        self.p_dx = 1.0
        self.p_dy = 1.0
        self.initialized = False
        
    def update(self, meas_x, meas_y):
        if not self.initialized:
            self.x = meas_x
            self.y = meas_y
            self.initialized = True
            return meas_x, meas_y
            
        # Predict state
        self.x = self.x + self.dx * self.dt
        self.y = self.y + self.dy * self.dt
        
        # Predict covariance
        self.p_x = self.p_x + self.p_dx * (self.dt ** 2) + self.q
        self.p_y = self.p_y + self.p_dy * (self.dt ** 2) + self.q
        self.p_dx = self.p_dx + self.q
        self.p_dy = self.p_dy + self.q
        
        # Calculate Kalman Gain
        k_x = self.p_x / (self.p_x + self.r)
        k_y = self.p_y / (self.p_y + self.r)
        
        # Update state
        self.x = self.x + k_x * (meas_x - self.x)
        self.y = self.y + k_y * (meas_y - self.y)
        
        self.dx = self.dx + (k_x / self.dt) * (meas_x - self.x)
        self.dy = self.dy + (k_y / self.dt) * (meas_y - self.y)
        
        # Update covariance
        self.p_x = (1.0 - k_x) * self.p_x
        self.p_y = (1.0 - k_y) * self.p_y
        self.p_dx = (1.0 - k_x) * self.p_dx
        self.p_dy = (1.0 - k_y) * self.p_dy
        
        return self.x, self.y

def cursor_interpolation_thread():
    """Background thread running at 120Hz to smoothly interpolate cursor movements."""
    global cursor_current_x, cursor_current_y
    lerp_factor = 0.25  # Fraction of distance to cover per step
    while _keep_running:
        if cursor_active:
            with cursor_lock:
                tx, ty = cursor_target_x, cursor_target_y
            
            dx = tx - cursor_current_x
            dy = ty - cursor_current_y
            
            if abs(dx) > 0.5 or abs(dy) > 0.5:
                cursor_current_x += dx * lerp_factor
                cursor_current_y += dy * lerp_factor
            else:
                cursor_current_x = tx
                cursor_current_y = ty
                
            pyautogui.moveTo(int(cursor_current_x), int(cursor_current_y))
            
        time.sleep(0.008)  # ~120 Hz

def _trigger_stop_speaking():
    """Helper function to stop speech playback dynamically via Flask app state."""
    try:
        import app
        app.stop_speaking_flag = True
        if app.mascot_widget_ref is not None:
            try:
                app.mascot_widget_ref.interrupt_speech()
            except Exception as e:
                print(f"[GESTURE] Mascot speech interrupt failed: {e}")
    except Exception as e:
        print(f"[GESTURE] Stop speaking failed: {e}")

def start_capture_loop():
    global _keep_running, _active, cursor_active, cursor_current_x, cursor_current_y, cursor_target_x, cursor_target_y
    if _active:
        print("[GESTURE] Gesture control capture loop is already active.")
        return
    
    _active = True
    _keep_running = True
    
    # Try finding an available camera index
    cap = None
    for idx in [0, 1, 2]:
        cap = cv2.VideoCapture(idx)
        if cap is not None and cap.isOpened():
            print(f"[GESTURE] Opened webcam at index: {idx}")
            break
            
    if cap is None or not cap.isOpened():
        print("[GESTURE ERROR] Could not open webcam. Ensure it is connected and not in use.")
        _active = False
        return
        
    # Configure Performance Settings on camera
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 30)
    
    # Configure MediaPipe hands tracker with requested settings
    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        model_complexity=0,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.6
    )
    
    screen_w, screen_h = pyautogui.size()
    
    # Initialize cursor position for the interpolation thread
    cursor_current_x, cursor_current_y = pyautogui.position()
    cursor_active = False
    
    # Start the sub-frame interpolation thread
    interp_thread = threading.Thread(target=cursor_interpolation_thread, daemon=True)
    interp_thread.start()
    
    # Initialize Kalman filter
    kf = KalmanFilter2D(process_noise=0.1, measurement_noise=1.5)
    prev_cx, prev_cy = screen_w // 2, screen_h // 2
    
    # Tracking variables for gesture transitions
    prev_gesture = "none"
    pinched_state = False
    last_pinch_release_time = 0.0
    
    # Fist-to-Palm (Delete) gesture tracking
    fist_closed_time = 0.0
    delete_cooldown = 0.0
    
    # Pinky (Minimize/Maximize) gesture tracking
    pinky_gesture_triggered = False
    window_is_minimized_state = False
    last_minimized_window = None
    pinky_cooldown = 0.0
    
    # Palm (Stop Speaking) gesture tracking
    palm_gesture_triggered = False
    palm_cooldown = 0.0
    
    # Rotate Finger (Volume adjustment) tracking
    prev_index_angle = None
    rotation_accumulator = 0.0
    volume_adjust_mode_until = 0.0
    
    try:
        while _keep_running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue
                
            # Mirror horizontally for intuitive coordinate mappings
            frame = cv2.flip(frame, 1)
            h, w, c = frame.shape
            
            # Downscale frame for Mediapipe to 640x360 to save CPU/GPU cycles
            frame_small = cv2.resize(frame, (640, 360))
            
            # Convert to RGB for MediaPipe processing
            rgb_frame = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)
            results = hands.process(rgb_frame)
            
            current_gesture = "none"
            now = time.time()
            
            if results.multi_hand_landmarks:
                for hand_landmarks in results.multi_hand_landmarks:
                    # Draw landmarks on preview window if enabled
                    if SHOW_PREVIEW:
                        mp_drawing.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)
                    
                    points = [(lm.x, lm.y) for lm in hand_landmarks.landmark]
                    
                    # 2D distance helper
                    def distance_2d(p1, p2):
                        return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)
                    
                    # Size scale of the hand: Wrist (0) to Index finger base MCP (5)
                    hand_scale = distance_2d(points[5], points[0])
                    
                    # Check if index finger is pointing towards the camera (foreshortened)
                    index_len_ratio = distance_2d(points[8], points[5]) / max(hand_scale, 0.001)
                    index_pointing_camera = index_len_ratio < 0.52
                    
                    # Check finger extension: Tip to MCP distance relative to hand scale
                    index_extended = index_len_ratio > 0.45 and not index_pointing_camera
                    middle_extended = (distance_2d(points[12], points[9]) / max(hand_scale, 0.001)) > 0.45
                    ring_extended = (distance_2d(points[16], points[13]) / max(hand_scale, 0.001)) > 0.45
                    pinky_extended = (distance_2d(points[20], points[17]) / max(hand_scale, 0.001)) > 0.40
                    
                    # Pinch metric: Normalized distance between thumb tip (4) and index tip (8)
                    d_pinch = distance_2d(points[4], points[8]) / max(hand_scale, 0.001)
                    
                    # --- GESTURE CLASSIFICATION ---
                    
                    # A. Fist state: all 4 fingers folded
                    is_fist = not index_extended and not middle_extended and not ring_extended and not pinky_extended
                    if is_fist:
                        fist_closed_time = now
                        
                    # B. Palm state: all 4 fingers extended
                    is_palm = index_extended and middle_extended and ring_extended and pinky_extended
                    
                    # 1. Fist-to-Palm (Delete selected file) or Palm (Stop speaking)
                    if is_palm:
                        # Check transition: was hand closed as a fist within last 1.5 seconds?
                        if now - fist_closed_time < 1.5 and now > delete_cooldown:
                            current_gesture = "delete"
                            delete_cooldown = now + 2.0
                            pyautogui.press('delete')
                            print("[GESTURE] Triggered: Fist -> Palm -> Delete File")
                            fist_closed_time = 0.0
                        else:
                            # Static Palm: Stop Speaking
                            if not palm_gesture_triggered and now > palm_cooldown:
                                palm_gesture_triggered = True
                                palm_cooldown = now + 1.5
                                current_gesture = "stop_speaking"
                                print("[GESTURE] Triggered: Palm -> Stop Speaking")
                                _trigger_stop_speaking()
                    else:
                        if not is_palm and palm_gesture_triggered and now > palm_cooldown - 1.0:
                            palm_gesture_triggered = False
                            
                    # 2. Pinky finger (Minimize / Maximize)
                    is_pinky_gesture = pinky_extended and not index_extended and not middle_extended and not ring_extended
                    if is_pinky_gesture:
                        if not pinky_gesture_triggered and now > pinky_cooldown:
                            pinky_gesture_triggered = True
                            pinky_cooldown = now + 1.5
                            current_gesture = "pinky_control"
                            
                            import pygetwindow as gw
                            try:
                                if window_is_minimized_state and last_minimized_window:
                                    print("[GESTURE] Pinky: Restoring/Maximizing window.")
                                    try:
                                        last_minimized_window.restore()
                                        last_minimized_window.maximize()
                                    except Exception:
                                        active_w = gw.getActiveWindow()
                                        if active_w:
                                            active_w.maximize()
                                    window_is_minimized_state = False
                                else:
                                    active_w = gw.getActiveWindow()
                                    if active_w and not active_w.isMinimized:
                                        print(f"[GESTURE] Pinky: Minimizing window '{active_w.title}'.")
                                        active_w.minimize()
                                        last_minimized_window = active_w
                                        window_is_minimized_state = True
                            except Exception as window_err:
                                print(f"[GESTURE ERROR] Pinky window control failed: {window_err}")
                    else:
                        if not is_pinky_gesture and pinky_gesture_triggered and now > pinky_cooldown - 1.0:
                            pinky_gesture_triggered = False
                            
                    # 3. Middle & Index pointing Up/Down/Left/Right (Scrolling)
                    is_scroll_gesture = index_extended and middle_extended and not ring_extended and not pinky_extended
                    if is_scroll_gesture:
                        vx = (points[8][0] - points[5][0]) / max(hand_scale, 0.001)
                        vy = (points[8][1] - points[5][1]) / max(hand_scale, 0.001)
                        
                        if abs(vy) > abs(vx):
                            if vy < -0.3:
                                current_gesture = "scroll_up"
                                pyautogui.scroll(120)
                            elif vy > 0.3:
                                current_gesture = "scroll_down"
                                pyautogui.scroll(-120)
                        else:
                            if vx < -0.3:
                                current_gesture = "scroll_left"
                                pyautogui.hscroll(-120)
                            elif vx > 0.3:
                                current_gesture = "scroll_right"
                                pyautogui.hscroll(120)
                                
                    # 4. Rotate finger (Volume adjustment)
                    is_rotate_gesture = index_extended and not middle_extended and not ring_extended and not pinky_extended
                    if is_rotate_gesture:
                        vy_index = (points[8][1] - points[5][1]) / max(hand_scale, 0.001)
                        if vy_index < -0.5:
                            idx_dx = points[8][0] - points[5][0]
                            idx_dy = points[8][1] - points[5][1]
                            current_angle = math.atan2(idx_dy, idx_dx)
                            
                            if prev_index_angle is not None:
                                diff = current_angle - prev_index_angle
                                diff = (diff + math.pi) % (2 * math.pi) - math.pi
                                
                                if 0.05 < abs(diff) < 1.0:
                                    rotation_accumulator += diff
                                    
                                    if rotation_accumulator > 0.4:
                                        current_gesture = "volume_up"
                                        import pc_control
                                        pc_control.adjust_volume("up")
                                        rotation_accumulator = 0.0
                                        volume_adjust_mode_until = now + 0.6
                                        print("[GESTURE] Volume Up (Clockwise Rotation)")
                                    elif rotation_accumulator < -0.4:
                                        current_gesture = "volume_down"
                                        import pc_control
                                        pc_control.adjust_volume("down")
                                        rotation_accumulator = 0.0
                                        volume_adjust_mode_until = now + 0.6
                                        print("[GESTURE] Volume Down (Counter-Clockwise Rotation)")
                            prev_index_angle = current_angle
                        else:
                            prev_index_angle = None
                            rotation_accumulator = 0.0
                    else:
                        prev_index_angle = None
                        rotation_accumulator = 0.0
                        
                    # 5. Pinch & Split (Select & Open)
                    if not middle_extended and not ring_extended and not pinky_extended:
                        if d_pinch < 0.18:
                            if not pinched_state:
                                pinched_state = True
                                if now - last_pinch_release_time < 0.5:
                                    current_gesture = "open"
                                    pyautogui.doubleClick()
                                    print("[GESTURE] Double Pinch -> Double Click Open")
                                    last_pinch_release_time = 0.0
                                else:
                                    current_gesture = "select"
                                    pyautogui.click()
                                    print("[GESTURE] Single Pinch -> Left Click Select")
                        elif d_pinch > 0.32:
                            if pinched_state:
                                pinched_state = False
                                last_pinch_release_time = now
                                
                    # 6. Cursor tracking (Index extended, others folded)
                    if index_extended and not middle_extended and not ring_extended and not pinky_extended:
                        if now > volume_adjust_mode_until:
                            if current_gesture == "none":
                                current_gesture = "cursor"
                                
                            cx_raw, cy_raw = points[8]
                            
                            # Region of interest box boundaries mapping: X [0.2, 0.8], Y [0.25, 0.75]
                            x_min, x_max = 0.2, 0.8
                            y_min, y_max = 0.25, 0.75
                            
                            cx_norm = (cx_raw - x_min) / (x_max - x_min)
                            cy_norm = (cy_raw - y_min) / (y_max - y_min)
                            
                            cx_norm = max(0.0, min(1.0, cx_norm))
                            cy_norm = max(0.0, min(1.0, cy_norm))
                            
                            target_cx = cx_norm * screen_w
                            target_cy = cy_norm * screen_h
                            
                            # A. Kalman Filter
                            kf_x, kf_y = kf.update(target_cx, target_cy)
                            
                            # B. Exponential Moving Average
                            alpha = 0.20
                            smooth_cx = alpha * kf_x + (1.0 - alpha) * prev_cx
                            smooth_cy = alpha * kf_y + (1.0 - alpha) * prev_cy
                            
                            prev_cx, prev_cy = smooth_cx, smooth_cy
                            
                            # C. Update target for Interpolation thread
                            with cursor_lock:
                                cursor_target_x = smooth_cx
                                cursor_target_y = smooth_cy
                                cursor_active = True
                        else:
                            with cursor_lock:
                                cursor_active = False
                    else:
                        with cursor_lock:
                            cursor_active = False
                            
                    # Live Text Overlay on webcam feed
                    status_text = f"Gesture: {current_gesture.upper()}"
                    if current_gesture == "cursor":
                        status_text += " (Move Cursor)"
                    elif current_gesture == "select":
                        status_text += " (Pinch Select)"
                    elif current_gesture == "open":
                        status_text += " (Split Open)"
                    elif current_gesture == "delete":
                        status_text += " (Fist to Palm Delete)"
                    elif current_gesture == "pinky_control":
                        status_text += " (Pinky Minimize/Maximize)"
                    elif current_gesture.startswith("scroll_"):
                        status_text += f" ({current_gesture.replace('_', ' ').title()})"
                    elif current_gesture == "stop_speaking":
                        status_text += " (Palm Stop Speaking)"
                    elif current_gesture.startswith("volume_"):
                        status_text += f" ({current_gesture.replace('_', ' ').title()})"
                        
                    if SHOW_PREVIEW:
                        cv2.putText(frame, status_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 229, 255), 2)
                        cv2.putText(frame, f"Pinch Ratio: {d_pinch:.2f}", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 229, 255), 1)
                        if is_rotate_gesture and prev_index_angle is not None:
                            cv2.putText(frame, f"Accumulated Rot: {rotation_accumulator:.2f}", (20, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 229, 255), 1)
                        
                    prev_gesture = current_gesture
            else:
                # Sleep briefly when no hands are detected to lower CPU load
                time.sleep(0.005)
                    
            if SHOW_PREVIEW:
                # Draw tracking bounding box overlay
                cv2.rectangle(frame, (int(w*0.2), int(h*0.25)), (int(w*0.8), int(h*0.75)), (0, 229, 255), 1)
                cv2.putText(frame, "Active Tracking Area", (int(w*0.2), int(h*0.22)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 229, 255), 1)
                cv2.imshow("Meow Gesture Control Preview", frame)

            # cv2.waitKey MUST be called every frame regardless of preview state —
            # OpenCV's video capture pipeline requires it to pump frames internally.
            key = cv2.waitKey(1) & 0xFF
            if SHOW_PREVIEW and key == 27:  # ESC closes preview window
                break
                
    except Exception as e:
        print(f"[GESTURE EXCEPTION] Loop crashed: {e}")
    finally:
        # Stop interpolation thread
        _keep_running = False
        with cursor_lock:
            cursor_active = False
            
        cap.release()
        cv2.destroyAllWindows()
        hands.close()
        _active = False
        print("[GESTURE] Gesture control capture loop stopped, resources released.")

def stop_capture_loop():
    global _keep_running, cursor_active
    _keep_running = False
    with cursor_lock:
        cursor_active = False

def toggle_preview():
    """Toggle the live camera preview window on or off at runtime."""
    global SHOW_PREVIEW
    SHOW_PREVIEW = not SHOW_PREVIEW
    if not SHOW_PREVIEW:
        # Close any open OpenCV windows when toggling off
        try:
            import cv2
            cv2.destroyAllWindows()
        except Exception:
            pass
    return SHOW_PREVIEW

def get_preview_state():
    """Return the current preview visibility state."""
    return SHOW_PREVIEW
