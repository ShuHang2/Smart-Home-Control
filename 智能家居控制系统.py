import mediapipe as mp
import cv2
import numpy as np
import joblib
import time
from PIL import Image, ImageDraw, ImageFont
from collections import deque
import RPi.GPIO as GPIO
import smbus2
import math

# 语音识别相关导入
from aip import AipSpeech
import sounddevice as sd
import threading
import queue
from scipy.io.wavfile import write

# AI语音交互相关导入
import requests
import json
import websocket
import datetime
import hashlib
import base64
import hmac
from urllib.parse import urlencode
import ssl
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime
import _thread as thread
import os
import pygame
import websocket

# 百度语音识别API配置
APP_ID = '119430179'
API_KEY = 'p6XESiKFjeCf9b46o4egdW3c'
SECRET_KEY = 'pums8L48pSBUku5D7gM6VOoEii7jcSBp'

# AI语音交互配置
# 讯飞语音合成配置
XF_APPID = '63f7d86c'
XF_API_SECRET = 'ZGYxM2U3MGY4OTUxYWJhNjUyNjI5MThh'
XF_API_KEY = '9d94a876bd34f5fca5e45b620e855487'
XF_TTS_URL = 'wss://cbm01.cn-huabei-1.xf-yun.com/v1/private/mcd9m97e6'

# 星火大模型配置
SPARK_URL = "https://spark-api-open.xf-yun.com/v1/chat/completions"
SPARK_TOKEN = "npGjMbdcpmkCxLGroLaN:vkyqkOYXezfCIzZpOJAi"

# 语音识别参数
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_DURATION = 0.2
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION)
BUF_DURATION = 1.5
BUF_SIZE = int(SAMPLE_RATE * BUF_DURATION)
TEMP_FILE = "temp_audio.wav"

# 语音指令模糊匹配词典
COMMAND_PATTERNS = {
    'red_on': ['开红灯', '打开红灯', '红灯开', '开红色', '打开红色', '凯红灯', '开洪灯', '开虹灯'],
    'red_off': ['关红灯', '关闭红灯', '红灯关', '关红色', '关闭红色', '关洪灯', '关虹灯'],
    'green_on': ['开绿灯', '打开绿灯', '绿灯开', '开绿色', '打开绿色', '凯绿灯', '开吕灯', '开律灯'],
    'green_off': ['关绿灯', '关闭绿灯', '绿灯关', '关绿色', '关闭绿色', '关吕灯', '关律灯'],
    'all_on': ['开灯', '打开灯', '全开', '都开', '开所有灯', '凯灯', '开等'],
    'all_off': ['关灯', '关闭灯', '全关', '都关', '关所有灯', '关等'],
    'voice_mode': ['语音模式', '语音控制', '声音模式', '声控'],
    'gesture_mode': ['手势模式', '手势控制', '手控'],
    'motion_mode_on': ['运动模式', '运动检测', '动作模式'],
    'motion_mode_off': ['关闭运动', '停止运动', '退出运动'],
    'check_temperature': ['温度', '查看温度', '当前温度', '现在温度', '多少度', '温度多少']
}

def match_command(text):
    """模糊匹配语音指令"""
    text = text.strip()
    
    # 先进行精确匹配
    for command, patterns in COMMAND_PATTERNS.items():
        for pattern in patterns:
            if pattern in text:
                return command
    
    # 如果精确匹配失败，进行模糊匹配
    return fuzzy_match_command(text)

def fuzzy_match_command(text):
    """基于拼音相似度的模糊匹配"""
    # 定义拼音相似的字符映射
    similar_chars = {
        '开': ['凯', '该', '盖'],
        '关': ['观', '官', '管'],
        '红': ['洪', '虹', '轰'],
        '绿': ['吕', '律', '率'],
        '灯': ['等', '登', '邓'],
        '打': ['大', '达', '答'],
        '色': ['涩', '瑟']
    }
    
    # 对文本进行字符替换匹配
    for command, patterns in COMMAND_PATTERNS.items():
        for pattern in patterns:
            if fuzzy_text_match(text, pattern, similar_chars):
                return command
    
    return None

def fuzzy_text_match(text, pattern, similar_chars):
    """检查文本是否与模式模糊匹配"""
    # 简单的模糊匹配：检查是否包含相似字符组合
    for i, char in enumerate(pattern):
        if char in text:
            continue
        # 检查相似字符
        if char in similar_chars:
            found_similar = False
            for similar_char in similar_chars[char]:
                if similar_char in text:
                    found_similar = True
                    break
            if not found_similar:
                return False
        else:
            return False
    return True

class UIButton:
    """UI按钮类"""
    def __init__(self, x, y, width, height, text, color, text_color=(255, 255, 255), action=None):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.text = text
        self.color = color
        self.text_color = text_color
        self.action = action
        self.is_hovered = False
        self.is_pressed = False
        
    def is_point_inside(self, px, py):
        """检查点是否在按钮内"""
        return (self.x <= px <= self.x + self.width and 
                self.y <= py <= self.y + self.height)
    
    def draw(self, img, font_func):
        """绘制按钮"""
        # 根据状态调整颜色
        color = self.color
        if self.is_pressed:
            # 按下时变暗
            color = tuple(int(c * 0.7) for c in color)
        elif self.is_hovered:
            # 悬停时变亮
            color = tuple(min(255, int(c * 1.2)) for c in color)
        
        # 绘制按钮背景
        cv2.rectangle(img, (self.x, self.y), 
                     (self.x + self.width, self.y + self.height), 
                     color, -1)
        
        # 绘制边框
        border_color = (255, 255, 255) if not self.is_pressed else (200, 200, 200)
        cv2.rectangle(img, (self.x, self.y), 
                     (self.x + self.width, self.y + self.height), 
                     border_color, 2)
        
        # 绘制文本
        text_x = self.x + 10
        text_y = self.y + self.height // 2 - 10
        img = font_func(img, self.text, (text_x, text_y), self.text_color)
        
        return img

class GestureDetector:
    def __init__(self, model_path="gesture_model.pkl"):
        # Initialize MediaPipe hand detection
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7)
        self.drawing_utils = mp.solutions.drawing_utils

        # Load trained gesture recognition model
        self.model = joblib.load(model_path)

        # Camera initialization
        self.cap = None
        self.camera_on = False

        # FPS calculation
        self.frame_times = deque(maxlen=50)
        self.current_fps = 0.0
        self.avg_fps = 0.0

        # Font loading - 支持中文显示
        self.font = None
        # 尝试加载中文字体
        chinese_fonts = [
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",  # 文泉驿正黑
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # 文泉驿微米黑
            "/usr/share/fonts/truetype/arphic/uming.ttc",  # AR PL UMing
            "/usr/share/fonts/truetype/arphic/ukai.ttc",   # AR PL UKai
            "/System/Library/Fonts/PingFang.ttc",  # macOS 苹方字体
            "C:/Windows/Fonts/simhei.ttf",  # Windows 黑体
            "C:/Windows/Fonts/simsun.ttc",  # Windows 宋体
            "C:/Windows/Fonts/msyh.ttc",   # Windows 微软雅黑
        ]
        
        for font_path in chinese_fonts:
            try:
                self.font = ImageFont.truetype(font_path, 20)
                print(f"成功加载中文字体: {font_path}")
                break
            except Exception:
                continue
        
        # 如果中文字体加载失败，尝试加载英文字体
        if self.font is None:
            try:
                self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
                print("加载英文字体: DejaVuSans")
            except Exception as e:
                print(f"字体加载失败: {e}")
                self.font = ImageFont.load_default()
                print("使用默认字体")

        # LED control setup
        self.pins = {'pin_R': 11, 'pin_G': 12}
        self.p_R = None
        self.p_G = None
        try:
            GPIO.setmode(GPIO.BOARD)
            for pin in self.pins.values():
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)
            self.p_R = GPIO.PWM(self.pins['pin_R'], 2000)
            self.p_G = GPIO.PWM(self.pins['pin_G'], 2000)
            self.p_R.start(0)
            self.p_G.start(0)
            print("GPIO LED初始化成功")
        except Exception as e:
            print(f"GPIO LED初始化错误: {e}")
            self.p_R = None
            self.p_G = None

        # PIR sensor setup
        self.pir_pin = 36
        GPIO.setup(self.pir_pin, GPIO.IN)
        self.motion_mode = False
        self.last_motion_time = 0
        self.motion_counter = 0
        self.output_interval = 5
        self.last_output_time = 0

        # Temperature sensor setup
        self.temp_adc_addr = 0x48
        self.temp_do_pin = 11
        self.bus = smbus2.SMBus(1)
        try:
            GPIO.setup(self.temp_do_pin, GPIO.IN)
        except Exception as e:
            print(f"温度传感器GPIO错误: {e}")
        self.last_temp_time = 0
        self.last_temp = None
        self.temp_display = False
        self.last_temp_announce_time = 0  # 上次温度播报时间

        # Control flags
        self.running = False

        # 语音识别初始化
        self.speech_client = AipSpeech(APP_ID, API_KEY, SECRET_KEY)
        self.is_voice_recording = False
        self.audio_buffer = np.zeros(BUF_SIZE, dtype=np.int16)
        self.buffer_lock = threading.Lock()
        self.audio_queue = queue.Queue(maxsize=3)
        self.voice_recognition_thread = None
        self.voice_record_thread = None
        self.silence_threshold = 200
        self.voice_mode = True  # Voice control mode switch
        self.gesture_mode = False  # Gesture control mode switch (default enabled)

        # 鼠标状态
        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_clicked = False
        
        # Gesture debouncing for OK gesture
        self.last_ok_gesture_time = 0
        self.ok_gesture_cooldown = 2.0  # 2 seconds cooldown
        
        # 手势播报控制
        self.last_announced_gesture = None  # 上次播报的手势
        
        # 语音指令播报控制
        self.last_announced_voice_command = None  # 上次播报的语音指令
        self.last_voice_command_time = 0  # 上次语音指令时间
        
        # AI语音交互初始化
        self.ai_mode = False  # AI交互模式开关
        self.ai_listening = False  # AI语音输入状态
        self.ai_audio_buffer = np.zeros(BUF_SIZE, dtype=np.int16)
        self.ai_audio_queue = queue.Queue(maxsize=3)
        self.ai_record_thread = None
        self.ai_response_text = ""
        self.ai_speaking = False
        
        # 初始化pygame音频播放
        try:
            pygame.mixer.init()
            pygame.mixer.music.set_volume(1.0)  # 设置音量为最大
            print("音频播放器初始化成功")
        except Exception as e:
            print(f"音频播放器初始化失败: {e}")
        
        # 初始化UI按钮
        self.init_buttons()

    def init_buttons(self):
        """初始化UI按钮"""
        self.buttons = []
        
        # 第一行按钮
        # 摄像头控制按钮
        self.camera_btn = UIButton(50, 50, 120, 50, "摄像头: 关闭", (0, 100, 200), action="toggle_camera")
        self.buttons.append(self.camera_btn)
        
        # 控制模式切换按钮
        self.mode_btn = UIButton(180, 50, 120, 50, "模式: 语音", (100, 200, 0), action="toggle_mode")
        self.buttons.append(self.mode_btn)
        
        # 运动模式按钮
        self.motion_btn = UIButton(310, 50, 120, 50, "运动: 关闭", (200, 0, 200), action="toggle_motion")
        self.buttons.append(self.motion_btn)
        
        # AI模式按钮
        self.ai_btn = UIButton(440, 50, 120, 50, "AI: 关闭", (255, 165, 0), action="toggle_ai")
        self.buttons.append(self.ai_btn)
        
        # 退出按钮
        self.exit_btn = UIButton(570, 50, 100, 50, "退出", (200, 0, 0), action="exit")
        self.buttons.append(self.exit_btn)
        
        # 第二行按钮（仅在AI模式开启时显示）
        # AI语音输入按钮
        self.ai_input_btn = UIButton(200, 110, 150, 50, "AI语音输入", (0, 200, 200), action="ai_voice_input")
        
        # AI停止说话按钮
        self.ai_stop_btn = UIButton(370, 110, 150, 50, "停止AI说话", (200, 100, 0), action="ai_stop_speaking")

    def mouse_callback(self, event, x, y, flags, param):
        """鼠标回调函数"""
        self.mouse_x = x
        self.mouse_y = y
        
        # 更新按钮悬停状态
        for button in self.buttons:
            button.is_hovered = button.is_point_inside(x, y)
        
        if event == cv2.EVENT_LBUTTONDOWN:
            self.mouse_clicked = True
            # 检查哪个按钮被点击
            for button in self.buttons:
                if button.is_point_inside(x, y):
                    button.is_pressed = True
                    self.handle_button_click(button.action)
                    break
            
            # 检查AI按钮点击（仅在AI模式开启时）
            if self.ai_mode:
                if self.ai_input_btn.is_point_inside(x, y):
                    self.ai_input_btn.is_pressed = True
                    self.handle_button_click("ai_voice_input")
                elif self.ai_stop_btn.is_point_inside(x, y):
                    self.ai_stop_btn.is_pressed = True
                    self.handle_button_click("ai_stop_speaking")
        
        elif event == cv2.EVENT_LBUTTONUP:
            self.mouse_clicked = False
            # 重置所有按钮的按下状态
            for button in self.buttons:
                button.is_pressed = False
            
            # 重置AI按钮状态
            if self.ai_mode:
                self.ai_input_btn.is_pressed = False
                self.ai_stop_btn.is_pressed = False

    def handle_button_click(self, action):
        """处理按钮点击事件"""
        if action == "toggle_camera":
            if self.camera_on:
                self.turn_off_camera()
            else:
                self.turn_on_camera()
        
        elif action == "toggle_mode":
            if self.gesture_mode:
                self.gesture_mode = False
                self.voice_mode = True
                print("切换到语音控制模式")
                # 重置播报状态
                self.last_announced_gesture = None
                self.last_announced_voice_command = None
                # 切换到语音模式时，自动开始语音录制
                if not self.is_voice_recording:
                    self.start_voice_recording()
                    print("自动开始语音录制")
            else:
                self.gesture_mode = True
                self.voice_mode = False
                print("切换到手势控制模式")
                # 重置播报状态
                self.last_announced_gesture = None
                self.last_announced_voice_command = None
                # 切换到手势模式时，停止语音录制
                if self.is_voice_recording:
                    self.stop_voice_recording()
        
        elif action == "toggle_motion":
            self.motion_mode = not self.motion_mode
            status = "开启" if self.motion_mode else "关闭"
            print(f"运动模式 {status}")
        
        elif action == "toggle_ai":
            self.ai_mode = not self.ai_mode
            status = "开启" if self.ai_mode else "关闭"
            print(f"AI模式 {status}")
            if not self.ai_mode and self.ai_speaking:
                self.stop_ai_speaking()
        
        elif action == "ai_voice_input":
            if self.ai_mode:
                if not self.ai_listening:
                    self.start_ai_listening()
                else:
                    self.stop_ai_listening()
        
        elif action == "ai_stop_speaking":
            if self.ai_speaking:
                self.stop_ai_speaking()
        
        elif action == "exit":
            self.running = False

    def update_button_states(self):
        """更新按钮状态显示"""
        # 更新摄像头按钮
        self.camera_btn.text = "摄像头: 开启" if self.camera_on else "摄像头: 关闭"
        self.camera_btn.color = (0, 200, 0) if self.camera_on else (200, 0, 0)
        
        # 更新模式按钮
        mode_text = "手势" if self.gesture_mode else "语音"
        self.mode_btn.text = f"模式: {mode_text}"
        self.mode_btn.color = (0, 150, 200) if self.gesture_mode else (200, 150, 0)
        
        # 更新运动模式按钮
        self.motion_btn.text = "运动: 开启" if self.motion_mode else "运动: 关闭"
        self.motion_btn.color = (0, 200, 0) if self.motion_mode else (200, 0, 0)
        
        # 更新AI模式按钮
        self.ai_btn.text = "AI: 开启" if self.ai_mode else "AI: 关闭"
        self.ai_btn.color = (0, 200, 0) if self.ai_mode else (200, 0, 0)
        
        # 更新AI语音输入按钮状态
        if self.ai_mode:
            self.ai_input_btn.text = "AI录音中..." if self.ai_listening else "AI语音输入"
            self.ai_input_btn.color = (0, 200, 0) if self.ai_listening else (0, 150, 200)
            
            self.ai_stop_btn.text = "停止AI说话"
            self.ai_stop_btn.color = (200, 0, 0) if self.ai_speaking else (100, 100, 100)

    def draw_ui(self, img):
        """绘制UI界面"""
        # 根据AI模式调整背景面板高度
        panel_height = 180 if self.ai_mode else 120
        
        # 绘制半透明背景面板
        overlay = img.copy()
        cv2.rectangle(overlay, (30, 30), (750, 30 + panel_height), (0, 0, 0), -1)
        img = cv2.addWeighted(img, 0.7, overlay, 0.3, 0)
        
        # 更新按钮状态
        self.update_button_states()
        
        # 绘制第一行按钮
        for button in self.buttons:
            img = button.draw(img, self._put_text)
        
        # 如果AI模式开启，绘制第二行AI相关按钮
        if self.ai_mode:
            # 更新AI按钮悬停状态
            self.ai_input_btn.is_hovered = self.ai_input_btn.is_point_inside(self.mouse_x, self.mouse_y)
            self.ai_stop_btn.is_hovered = self.ai_stop_btn.is_point_inside(self.mouse_x, self.mouse_y)
            
            # 绘制AI按钮
            img = self.ai_input_btn.draw(img, self._put_text)
            img = self.ai_stop_btn.draw(img, self._put_text)
            
            # 显示AI状态信息
            if self.ai_listening:
                ai_status = "AI正在听取语音输入..."
                color = (0, 255, 0)
            elif self.ai_speaking:
                ai_status = "AI正在播放回答..."
                color = (255, 255, 0)
            else:
                ai_status = "AI待机中，点击语音输入开始对话"
                color = (255, 255, 255)
            
            img = self._put_text(img, ai_status, (50, 170), color)
            
            # 显示AI回答内容（如果有）
            if self.ai_response_text:
                # 文本换行处理
                max_width = 60  # 每行最大字符数
                lines = []
                for i in range(0, len(self.ai_response_text), max_width):
                    lines.append(self.ai_response_text[i:i+max_width])
                
                y_offset = 200
                for line in lines[:3]:  # 最多显示3行
                    img = self._put_text(img, f"AI回答: {line}", (50, y_offset), (0, 255, 255))
                    y_offset += 25
        
        # 绘制鼠标位置指示器（调试用）
        cv2.circle(img, (self.mouse_x, self.mouse_y), 3, (0, 255, 255), -1)
        
        return img

    def _extract_features(self, landmarks):
        if not landmarks:
            return None
        landmarks = np.array(landmarks)
        reference_point = landmarks[0]
        return (landmarks - reference_point).flatten()

    def _put_text(self, img, text, position, color=(0, 255, 0)):
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        draw = ImageDraw.Draw(pil_img)
        try:
            draw.text(position, text, font=self.font, fill=color)
        except:
            default_font = ImageFont.load_default()
            draw.text(position, text, font=default_font, fill=color)
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    def set_color(self, r, g):
        """设置LED颜色"""
        try:
            if self.p_R is not None:
                self.p_R.ChangeDutyCycle(r)
            if self.p_G is not None:
                self.p_G.ChangeDutyCycle(g)
        except Exception as e:
            print(f"LED颜色设置错误: {e}")

    def set_red_light(self):
        self.set_color(100, 0)

    def set_green_light(self):
        self.set_color(0, 100)

    def set_white_light(self, brightness):
        self.set_color(brightness, brightness)

    def lights_off(self):
        self.set_color(0, 0)

    def destroy_lights(self):
        """安全清理GPIO资源"""
        try:
            if hasattr(self, 'p_R') and self.p_R is not None:
                self.p_R.stop()
        except Exception as e:
            print(f"红灯PWM停止错误: {e}")
        
        try:
            if hasattr(self, 'p_G') and self.p_G is not None:
                self.p_G.stop()
        except Exception as e:
            print(f"绿灯PWM停止错误: {e}")
        
        try:
            for pin in self.pins.values():
                GPIO.output(pin, GPIO.LOW)
        except Exception as e:
            print(f"GPIO输出设置错误: {e}")
        
        try:
            GPIO.cleanup()
        except Exception as e:
            print(f"GPIO清理错误: {e}")

    def get_temperature(self):
        try:
            self.bus.write_byte(self.temp_adc_addr, 0x40)
            self.bus.read_byte(self.temp_adc_addr)
            analog_val = self.bus.read_byte(self.temp_adc_addr)
            vr = 5 * float(analog_val) / 255
            rt = 10000 * vr / (5 - vr)
            temp = 1 / (((math.log(rt / 10000)) / 3950) + (1 / (273.15 + 25)))
            return temp - 273.15
        except Exception as e:
            print(f"温度读取错误: {e}")
            return None

    def is_motion_detected(self):
        return GPIO.input(self.pir_pin) == GPIO.HIGH

    def run_motion_detection(self, frame):
        current_time = time.time()
        motion_detected = self.is_motion_detected()

        if motion_detected and (current_time - self.last_motion_time > 2):
            self.last_motion_time = current_time
            self.motion_counter += 1
            print(f"运动检测 #{self.motion_counter}: 有人经过!")
            self.set_red_light()
            self.last_output_time = current_time
        else:
            if current_time - self.last_output_time >= self.output_interval:
                print("无人经过。")
                self.set_green_light()
                self.last_output_time = current_time

        status_text = "运动: 活跃" if motion_detected else "运动: 空闲"
        frame = self._put_text(frame, status_text, (10, 250), (255, 255, 0))
        return frame

    def detect_gesture(self, frame):
        detected_gesture = None
        original_frame = frame.copy()

        # Gesture detection - "ok" gesture works in both modes for voice control
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(img_rgb)

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                self.drawing_utils.draw_landmarks(frame, hand_landmarks, self.mp_hands.HAND_CONNECTIONS)
                landmarks = [[lm.x, lm.y, lm.z] for lm in hand_landmarks.landmark]
                features = self._extract_features(landmarks)

                if features is not None:
                    features = features.reshape(1, -1)
                    gesture_probs = self.model.predict_proba(features)[0]
                    gesture_idx = np.argmax(gesture_probs)
                    gesture_label = self.model.classes_[gesture_idx]
                    confidence = gesture_probs[gesture_idx]

                    if confidence > 0.7:
                        text = f"手势: {gesture_label} ({confidence:.2f})"
                        frame = self._put_text(frame, text, (10, 220), (0, 255, 0))
                        detected_gesture = gesture_label

                # "OK" gesture to toggle voice control mode and recording
                # Try multiple possible labels for OK gesture
                ok_gestures = ["7", "ok", "OK", "thumbs_up", "thumb_up"]
                if gesture_label in ok_gestures:
                    current_time = time.time()
                    # Check cooldown to prevent rapid toggling
                    if current_time - self.last_ok_gesture_time > self.ok_gesture_cooldown:
                        self.last_ok_gesture_time = current_time
                        if not self.voice_mode:
                            # 切换到语音控制模式并开始录音
                            self.voice_mode = True
                            self.gesture_mode = False
                            # 重置播报状态
                            self.last_announced_gesture = None
                            self.last_announced_voice_command = None
                            self.start_voice_recording()
                            print(f"OK手势检测: 切换到语音控制模式并开始录音 ({gesture_label})")
                    else:
                        # 已经在语音模式，切换录音状态
                        if not self.is_voice_recording:
                            self.start_voice_recording()
                            print(f"OK手势检测: 开始语音录音 ({gesture_label})")
                        else:
                            self.stop_voice_recording()
                            print(f"OK手势检测: 停止语音录音 ({gesture_label})")

        # Only perform other gesture detection and control in gesture mode
        if self.gesture_mode and detected_gesture:
            # Normal gesture light control (excluding 7 for OK gesture)
            if detected_gesture in ["0", "1", "2", "3", "4", "5", "6"]:
                # 检查是否是新的手势，只有手势变化时才播报
                should_announce = (self.last_announced_gesture != detected_gesture)
                
                if detected_gesture == "0":
                    self.set_red_light()
                    self.temp_display = False
                    if should_announce:
                        threading.Thread(target=self._announce_action, args=("红灯已开启",)).start()
                elif detected_gesture == "1":
                    self.set_white_light(66)
                    self.temp_display = False
                    if should_announce:
                        threading.Thread(target=self._announce_action, args=("灯光中等亮度",)).start()
                elif detected_gesture == "2":
                    self.set_white_light(33)
                    self.temp_display = False
                    if should_announce:
                        threading.Thread(target=self._announce_action, args=("灯光低亮度",)).start()
                elif detected_gesture == "3":
                    self.lights_off()
                    self.temp_display = False
                    if should_announce:
                        threading.Thread(target=self._announce_action, args=("灯光已关闭",)).start()
                elif detected_gesture == "4":
                    self.set_white_light(80)
                    self.temp_display = False
                    if should_announce:
                        threading.Thread(target=self._announce_action, args=("灯光高亮度",)).start()
                elif detected_gesture == "5":
                    self.set_green_light()
                    self.temp_display = False
                    if should_announce:
                        threading.Thread(target=self._announce_action, args=("绿灯已开启",)).start()
                elif detected_gesture == "6":
                    self.temp_display = True
                    if should_announce:
                        threading.Thread(target=self._announce_action, args=("温度显示已开启",)).start()
                
                # 更新上次播报的手势
                if should_announce:
                    self.last_announced_gesture = detected_gesture

            # Temperature display
            if self.temp_display:
                now = time.time()
                if now - self.last_temp_time > 1:
                    self.last_temp = self.get_temperature()
                    self.last_temp_time = now
                    # 播报温度（每5秒播报一次，避免过于频繁）
                    if (self.last_temp is not None and 
                        now - self.last_temp_announce_time > 5):
                        temp_announce = f"当前温度{self.last_temp:.1f}摄氏度"
                        print(f"播报温度: {temp_announce}")
                        self.last_temp_announce_time = now
                        threading.Thread(target=self._announce_temperature, args=(temp_announce,)).start()
                if self.last_temp is not None:
                    temp_text = f"温度: {self.last_temp:.2f}°C"
                    frame = self._put_text(frame, temp_text, (10, 280), (255, 0, 0))
        else:
            # 如果没有检测到手势或不在手势模式，重置上次播报的手势
            if not detected_gesture:
                self.last_announced_gesture = None

        # In voice mode, if motion mode is enabled, still run motion detection
        if self.motion_mode and not self.gesture_mode:
            frame = self.run_motion_detection(original_frame)

        # Display mode status
        control_mode = "手势控制" if self.gesture_mode else "语音控制"
        mode_text = f"控制模式: {control_mode}"
        frame = self._put_text(frame, mode_text, (10, 310), (255, 255, 0))
        
        # Display voice recording status in voice mode
        if self.voice_mode:
            voice_status = "录音中..." if self.is_voice_recording else "录音停止"
            voice_text = f"语音状态: {voice_status}"
            color = (0, 255, 0) if self.is_voice_recording else (255, 0, 0)
            frame = self._put_text(frame, voice_text, (400, 310), color)
        
        # Display control hints
        if self.gesture_mode:
            hint = "提示: 点击'模式'按钮切换到语音控制，或使用OK手势"
        else:
            hint = "提示: 点击'模式'按钮切换到手势控制"
        frame = self._put_text(frame, hint, (10, 340), (0, 255, 255))
        
        return frame

    def update_fps(self):
        current_time = time.time()
        if len(self.frame_times) > 0:
            frame_time = current_time - self.frame_times[-1]
            self.current_fps = 1.0 / frame_time if frame_time > 0 else 0
        self.frame_times.append(current_time)
        if len(self.frame_times) > 1:
            total_time = current_time - self.frame_times[0]
            self.avg_fps = len(self.frame_times) / total_time if total_time > 0 else 0

    def turn_on_camera(self):
        if not self.camera_on:
            self.cap = cv2.VideoCapture(0)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_FPS, 60)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 3)
            self.camera_on = True
            print("摄像头已开启")

    def turn_off_camera(self):
        if self.camera_on:
            self.cap.release()
            self.cap = None
            self.camera_on = False
            self.lights_off()
            print("摄像头已关闭")

    def run(self):
        self.running = True
        cv2.namedWindow("Gesture Recognition System", cv2.WINDOW_NORMAL)
        cv2.setMouseCallback("Gesture Recognition System", self.mouse_callback)
        
        print("=== 控制系统已启动 ===")
        print("UI控制:")
        print("  点击按钮控制系统")
        print("  ESC键: 退出程序")
        print("模式切换:")
        print("  点击'模式'按钮: 在手势模式和语音模式间切换")
        print("  切换到语音模式时会自动开始语音录制")
        print("手势控制:")
        print("  OK/竖拇指手势: 切换到语音控制模式并开始录音")
        print("  手势0-5: 控制不同的灯光效果（会语音播报操作结果）")
        print("  手势6: 显示温度并语音播报")
        print("语音指令示例:")
        print("  '开红灯', '关绿灯', '开灯', '关灯'（会语音播报操作结果）")
        print("  '语音模式', '手势模式', '运动模式'（会语音播报切换结果）")
        print("  '温度', '当前温度', '多少度' - 查询并播报温度")
        print("AI语音交互:")
        print("  点击'AI'按钮开启AI模式")
        print("  点击'AI语音输入'开始与AI对话")
        print("  AI会通过语音回答您的问题")

        while self.running:
            if self.camera_on:
                success, img = self.cap.read()
                if not success:
                    print("摄像头读取错误，正在重启...")
                    self.turn_off_camera()
                    time.sleep(1)
                    self.turn_on_camera()
                    continue

                img = cv2.resize(img, (720, 480))
                self.update_fps()

                fps_color = (0, 255, 0)
                if self.avg_fps < 20:
                    fps_color = (0, 0, 255)
                elif self.avg_fps < 30:
                    fps_color = (0, 255, 255)

                fps_text = f"FPS: {self.current_fps:.1f} (Avg: {self.avg_fps:.1f})"
                img = self._put_text(img, fps_text, (10, 370), fps_color)

                img = self.detect_gesture(img)
            else:
                img = np.zeros((720, 1280, 3), dtype=np.uint8)
                prompt_text = "摄像头已关闭 - 点击摄像头按钮开启"
                img = self._put_text(img, prompt_text, (400, 400), (255, 255, 255))
                self.frame_times.clear()

            # 绘制UI界面
            img = self.draw_ui(img)

            cv2.imshow("Gesture Recognition System", img)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC key
                self.running = False

        self.close()

    def close(self):
        """安全关闭系统"""
        self.running = False
        
        # 关闭摄像头
        try:
            if self.camera_on:
                self.turn_off_camera()
        except Exception as e:
            print(f"摄像头关闭错误: {e}")
        
        # 停止语音录制
        try:
            if self.is_voice_recording:
                self.stop_voice_recording()
        except Exception as e:
            print(f"语音录制停止错误: {e}")
        
        # 停止AI功能
        try:
            if self.ai_listening:
                self.stop_ai_listening()
            if self.ai_speaking:
                self.stop_ai_speaking()
        except Exception as e:
            print(f"AI功能停止错误: {e}")
        
        # 关闭pygame音频
        try:
            pygame.mixer.quit()
        except Exception as e:
            print(f"pygame音频关闭错误: {e}")
        
        # 关闭OpenCV窗口
        try:
            cv2.destroyAllWindows()
        except Exception as e:
            print(f"OpenCV窗口关闭错误: {e}")
        
        # 清理GPIO资源
        try:
            self.destroy_lights()
        except Exception as e:
            print(f"GPIO清理错误: {e}")
        
        # 清理临时文件
        try:
            temp_files = ['ai_temp_audio.wav', 'ai_response.mp3', 'temp_audio.wav', 'temp_announce.mp3', 'action_announce.mp3']
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
        except Exception as e:
            print(f"临时文件清理错误: {e}")
        
        print("系统安全关闭")

    # 语音识别相关方法
    def start_voice_recording(self):
        """开始语音录制"""
        if not self.is_voice_recording:
            self.is_voice_recording = True
            print("* 语音录制已开始")
            
            # 启动录音线程
            self.voice_record_thread = threading.Thread(target=self._voice_record)
            self.voice_record_thread.start()
            
            # 启动识别工作线程
            self.voice_recognition_thread = threading.Thread(target=self._voice_recognize_worker)
            self.voice_recognition_thread.start()
    
    def stop_voice_recording(self):
        """停止语音录制"""
        if self.is_voice_recording:
            self.is_voice_recording = False
            # 等待线程结束
            if self.voice_recognition_thread:
                self.voice_recognition_thread.join()
            if self.voice_record_thread:
                self.voice_record_thread.join()
            print("* 语音录制已停止")
    
    def _voice_record(self):
        """录音线程函数"""
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                           blocksize=CHUNK_SIZE, dtype=np.int16) as stream:
            while self.is_voice_recording:
                try:
                    # 读取音频块
                    audio_chunk, overflow = stream.read(CHUNK_SIZE)
                    
                    # 检查溢出
                    if overflow:
                        print("警告: 音频缓冲区溢出")
                    
                    # 将音频块添加到缓冲区
                    with self.buffer_lock:
                        self.audio_buffer = np.roll(self.audio_buffer, -CHUNK_SIZE)
                        self.audio_buffer[-CHUNK_SIZE:] = audio_chunk.flatten()
                    
                    # 检测是否有语音活动
                    if np.max(np.abs(audio_chunk)) > self.silence_threshold:
                        # 有语音活动，将当前缓冲区添加到识别队列
                        try:
                            self.audio_queue.put(self.audio_buffer.copy(), block=False)
                        except queue.Full:
                            # 队列满了，丢弃最老的数据
                            try:
                                self.audio_queue.get_nowait()
                                self.audio_queue.put(self.audio_buffer.copy(), block=False)
                            except queue.Empty:
                                pass
                except Exception as e:
                    print(f"录音错误: {e}")
    
    def _voice_recognize_worker(self):
        """识别工作线程"""
        last_recognition_time = 0
        recognition_interval = 0.5
        
        while self.is_voice_recording or not self.audio_queue.empty():
            try:
                # 获取最新的音频缓冲区
                audio_data = self.audio_queue.get(timeout=0.2)
                
                # 控制识别频率，避免API调用过于频繁
                current_time = time.time()
                if current_time - last_recognition_time < recognition_interval:
                    self.audio_queue.task_done()
                    continue
                
                # 保存为WAV文件并识别
                self._save_audio(TEMP_FILE, audio_data)
                result = self._recognize_audio(TEMP_FILE)
                if result and 'result' in result:
                    recognized_text = result['result'][0]
                    print(f"语音识别结果: {recognized_text}")
                    # 处理语音指令
                    command = match_command(recognized_text)
                    if command:
                        self._handle_voice_command(command)
                    last_recognition_time = current_time
                else:
                    print("无法识别语音")
                
                self.audio_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"识别线程错误: {e}")
    
    def _save_audio(self, filename, audio_data):
        """保存音频数据到文件"""
        write(filename, SAMPLE_RATE, audio_data)
    
    def _recognize_audio(self, filename):
        """调用百度API识别音频"""
        try:
            with open(filename, 'rb') as f:
                audio_data = f.read()
            
            result = self.speech_client.asr(audio_data, 'wav', SAMPLE_RATE, {
                'dev_pid': 1536,  # 中文识别
            })
            
            return result
        except Exception as e:
            print(f"识别错误: {e}")
            return None
    
    def _handle_voice_command(self, command):
        """处理语音指令"""
        current_time = time.time()
        
        # 检查是否是重复的语音指令（3秒内的相同指令不重复播报）
        should_announce = (self.last_announced_voice_command != command or 
                          current_time - self.last_voice_command_time > 3.0)
        
        if command == 'red_on':
            self.set_red_light()
            print("语音控制: 红灯已开启")
            if should_announce:
                threading.Thread(target=self._announce_action, args=("红灯已开启",)).start()
        elif command == 'red_off':
            self.lights_off()
            print("语音控制: 红灯已关闭")
            if should_announce:
                threading.Thread(target=self._announce_action, args=("红灯已关闭",)).start()
        elif command == 'green_on':
            self.set_green_light()
            print("语音控制: 绿灯已开启")
            if should_announce:
                threading.Thread(target=self._announce_action, args=("绿灯已开启",)).start()
        elif command == 'green_off':
            self.lights_off()
            print("语音控制: 绿灯已关闭")
            if should_announce:
                threading.Thread(target=self._announce_action, args=("绿灯已关闭",)).start()
        elif command == 'all_on':
            self.set_white_light(100)
            print("语音控制: 所有灯已开启")
            if should_announce:
                threading.Thread(target=self._announce_action, args=("所有灯已开启",)).start()
        elif command == 'all_off':
            self.lights_off()
            print("语音控制: 所有灯已关闭")
            if should_announce:
                threading.Thread(target=self._announce_action, args=("所有灯已关闭",)).start()
        elif command == 'voice_mode':
            self.voice_mode = True
            self.gesture_mode = False
            print("切换到语音控制模式")
            if should_announce:
                threading.Thread(target=self._announce_action, args=("已切换到语音控制模式",)).start()
        elif command == 'gesture_mode':
            self.gesture_mode = True
            self.voice_mode = False
            print("切换到手势控制模式")
            if should_announce:
                threading.Thread(target=self._announce_action, args=("已切换到手势控制模式",)).start()
        elif command == 'motion_mode_on':
            self.motion_mode = True
            print("语音控制: 运动模式已启用")
            if should_announce:
                threading.Thread(target=self._announce_action, args=("运动模式已启用",)).start()
        elif command == 'motion_mode_off':
            self.motion_mode = False
            print("语音控制: 运动模式已禁用")
            if should_announce:
                threading.Thread(target=self._announce_action, args=("运动模式已禁用",)).start()
        elif command == 'check_temperature':
            current_temp = self.get_temperature()
            if current_temp is not None:
                temp_announce = f"当前温度{current_temp:.1f}摄氏度"
                print(f"语音控制: 播报温度 - {temp_announce}")
                threading.Thread(target=self._announce_temperature, args=(temp_announce,)).start()
            else:
                error_announce = "温度传感器读取失败"
                print(f"语音控制: {error_announce}")
                threading.Thread(target=self._announce_temperature, args=(error_announce,)).start()
        
        # 更新上次播报的语音指令和时间
        if should_announce:
            self.last_announced_voice_command = command
            self.last_voice_command_time = current_time

    # AI语音交互核心方法
    def start_ai_listening(self):
        """开始AI语音输入"""
        if not self.ai_listening:
            self.ai_listening = True
            self.ai_response_text = ""
            print("* AI语音输入已开始")
            
            # 启动AI录音线程
            self.ai_record_thread = threading.Thread(target=self._ai_record_and_process)
            self.ai_record_thread.start()
    
    def stop_ai_listening(self):
        """停止AI语音输入"""
        if self.ai_listening:
            self.ai_listening = False
            print("* AI语音输入已停止")
    
    def _ai_record_and_process(self):
        """AI录音和处理线程"""
        try:
            # 录音
            print("开始录音，请说话...")
            duration = 5  # 录音5秒
            audio_data = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, 
                               channels=CHANNELS, dtype=np.int16)
            sd.wait()
            
            # 保存音频文件
            ai_temp_file = "ai_temp_audio.wav"
            write(ai_temp_file, SAMPLE_RATE, audio_data)
            
            # 语音识别
            print("正在识别语音...")
            result = self._recognize_audio(ai_temp_file)
            
            if result and 'result' in result:
                user_text = result['result'][0]
                print(f"用户说: {user_text}")
                
                # 调用大模型获取回答
                print("正在获取AI回答...")
                ai_response = self._get_ai_response(user_text)
                
                if ai_response:
                    print(f"AI回答: {ai_response}")
                    self.ai_response_text = ai_response
                    
                    # 语音合成并播放
                    print("正在合成语音...")
                    self._text_to_speech_and_play(ai_response)
                else:
                    print("AI回答获取失败")
            else:
                print("语音识别失败")
            
            # 清理临时文件
            if os.path.exists(ai_temp_file):
                os.remove(ai_temp_file)
                
        except Exception as e:
            print(f"AI语音处理错误: {e}")
        finally:
            self.ai_listening = False
    
    def _get_ai_response(self, user_text):
        """调用星火大模型获取回答"""
        try:
            url = SPARK_URL
            data = {
                "max_tokens": 1000,
                "top_k": 4,
                "temperature": 0.7,
                "messages": [
                    {
                        "role": "user",
                        "content": user_text
                    }
                ],
                "model": "lite",
                "stream": False  # 不使用流式，直接获取完整回答
            }
            
            header = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SPARK_TOKEN}"
            }
            
            response = requests.post(url, headers=header, json=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                return result['choices'][0]['message']['content']
            else:
                return None
                
        except Exception as e:
            print(f"大模型调用错误: {e}")
            return None
    
    def _text_to_speech_and_play(self, text):
        """文本转语音并播放"""
        try:
            self.ai_speaking = True
            
            # 创建WebSocket参数
            ws_param = self._create_tts_param(text)
            
            # 建立WebSocket连接
            requrl = XF_TTS_URL
            ws_url = self._assemble_ws_auth_url(requrl, "GET", XF_API_KEY, XF_API_SECRET)
            
            # 清除旧的音频文件
            if os.path.exists('./ai_response.mp3'):
                os.remove('./ai_response.mp3')
            
            # 创建WebSocket连接
            ws = websocket.WebSocketApp(ws_url, 
                                       on_message=self._on_tts_message, 
                                       on_error=self._on_tts_error, 
                                       on_close=self._on_tts_close)
            ws.on_open = lambda ws: self._on_tts_open(ws, ws_param)
            
            # 运行WebSocket
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            
            # 播放生成的音频文件
            if os.path.exists('./ai_response.mp3'):
                pygame.mixer.music.load('./ai_response.mp3')
                pygame.mixer.music.set_volume(1.0)  # 确保音量最大
                pygame.mixer.music.play()
                
                # 等待播放完成
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                    if not self.ai_speaking:  # 如果用户停止了播放
                        pygame.mixer.music.stop()
                        break
                
                print("AI语音播放完成")
            else:
                print("音频文件生成失败")
                
        except Exception as e:
            print(f"语音合成播放错误: {e}")
        finally:
            self.ai_speaking = False
    
    def stop_ai_speaking(self):
        """停止AI语音播放"""
        if self.ai_speaking:
            self.ai_speaking = False
            try:
                pygame.mixer.music.stop()
                print("AI语音播放已停止")
            except Exception as e:
                print(f"停止AI语音播放错误: {e}")
    
    def _create_tts_param(self, text):
        """创建TTS参数"""
        class TtsParam:
            def __init__(self, appid, api_key, api_secret, text):
                self.APPID = appid
                self.APIKey = api_key
                self.APISecret = api_secret
                self.Text = text
                
                self.CommonArgs = {"app_id": self.APPID, "status": 2}
                self.BusinessArgs = {
                    "tts": {
                        "vcn": "x4_lingxiaoxuan_oral",
                        "volume": 100,  # 调整音量到最大
                        "speed": 50,
                        "pitch": 50,
                        "audio": {
                            "encoding": "lame",
                            "sample_rate": 24000,
                            "channels": 1,
                            "bit_depth": 16,
                            "frame_size": 0
                        }
                    }
                }
                
                self.Data = {
                    "text": {
                        "encoding": "utf8",
                        "compress": "raw",
                        "format": "plain",
                        "status": 2,
                        "seq": 0,
                        "text": str(base64.b64encode(self.Text.encode('utf-8')), "UTF8")
                    }
                }
        
        return TtsParam(XF_APPID, XF_API_KEY, XF_API_SECRET, text)
    
    def _assemble_ws_auth_url(self, request_url, method="GET", api_key="", api_secret=""):
        """构建WebSocket认证URL"""
        try:
            # 解析URL
            stidx = request_url.index("://")
            host = request_url[stidx + 3:]
            schema = request_url[:stidx + 3]
            edidx = host.index("/")
            path = host[edidx:]
            host = host[:edidx]
            
            # 生成时间戳
            now = datetime.now()
            date = format_date_time(mktime(now.timetuple()))
            
            # 生成签名
            signature_origin = f"host: {host}\ndate: {date}\n{method} {path} HTTP/1.1"
            signature_sha = hmac.new(api_secret.encode('utf-8'), 
                                   signature_origin.encode('utf-8'),
                                   digestmod=hashlib.sha256).digest()
            signature_sha = base64.b64encode(signature_sha).decode(encoding='utf-8')
            
            authorization_origin = f'api_key="{api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha}"'
            authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')
            
            # 构建最终URL
            values = {
                "host": host,
                "date": date,
                "authorization": authorization
            }
            
            return request_url + "?" + urlencode(values)
            
        except Exception as e:
            print(f"WebSocket URL构建错误: {e}")
            return request_url
    
    def _on_tts_message(self, ws, message):
        """TTS WebSocket消息处理"""
        try:
            message = json.loads(message)
            code = message["header"]["code"]
            
            if code != 0:
                print(f"TTS错误: {message.get('message', '未知错误')}")
                ws.close()
                return
            
            if "payload" in message:
                audio = message["payload"]["audio"]["audio"]
                audio = base64.b64decode(audio)
                status = message["payload"]["audio"]["status"]
                
                with open('./ai_response.mp3', 'ab') as f:
                    f.write(audio)
                
                if status == 2:  # 最后一帧
                    print("TTS音频生成完成")
                    ws.close()
                    
        except Exception as e:
            print(f"TTS消息处理错误: {e}")
    
    def _on_tts_error(self, ws, error):
        """TTS WebSocket错误处理"""
        print(f"TTS WebSocket错误: {error}")
    
    def _on_tts_close(self, ws, close_status_code, close_msg):
        """TTS WebSocket关闭处理"""
        pass
    
    def _on_tts_open(self, ws, ws_param):
        """TTS WebSocket开启处理"""
        def run():
            try:
                d = {
                    "header": ws_param.CommonArgs,
                    "parameter": ws_param.BusinessArgs,
                    "payload": ws_param.Data,
                }
                data = json.dumps(d)
                ws.send(data)
                print("TTS请求已发送")
            except Exception as e:
                print(f"TTS请求发送错误: {e}")
        
        thread.start_new_thread(run, ())
    
    def _announce_action(self, action_text):
        """播报操作结果"""
        try:
            # 检查是否有其他语音正在播放
            if self.ai_speaking:
                print(f"AI正在说话，跳过操作播报: {action_text}")
                return
            
            print(f"播报操作: {action_text}")
            
            # 创建WebSocket参数
            ws_param = self._create_tts_param(action_text)
            
            # 建立WebSocket连接
            requrl = XF_TTS_URL
            ws_url = self._assemble_ws_auth_url(requrl, "GET", XF_API_KEY, XF_API_SECRET)
            
            # 清除旧的操作播报文件
            action_audio_file = './action_announce.mp3'
            if os.path.exists(action_audio_file):
                os.remove(action_audio_file)
            
            # 设置临时文件名
            self._action_announce_file = action_audio_file
            
            # 创建WebSocket连接
            ws = websocket.WebSocketApp(ws_url, 
                                       on_message=self._on_action_tts_message, 
                                       on_error=self._on_action_tts_error, 
                                       on_close=self._on_action_tts_close)
            ws.on_open = lambda ws: self._on_action_tts_open(ws, ws_param)
            
            # 运行WebSocket
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            
            # 播放生成的音频文件
            if os.path.exists(action_audio_file):
                # 等待一下确保文件完全写入
                time.sleep(0.1)
                pygame.mixer.music.load(action_audio_file)
                pygame.mixer.music.set_volume(1.0)  # 确保音量最大
                pygame.mixer.music.play()
                
                # 等待播放完成
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                
                print("操作播报完成")
                
                # 清理临时文件
                try:
                    os.remove(action_audio_file)
                except:
                    pass
            else:
                print("操作播报音频文件生成失败")
                
        except Exception as e:
            print(f"操作播报错误: {e}")
    
    def _on_action_tts_message(self, ws, message):
        """操作播报TTS WebSocket消息处理"""
        try:
            message = json.loads(message)
            code = message["header"]["code"]
            
            if code != 0:
                print(f"操作播报TTS错误: {message.get('message', '未知错误')}")
                ws.close()
                return
            
            if "payload" in message:
                audio = message["payload"]["audio"]["audio"]
                audio = base64.b64decode(audio)
                status = message["payload"]["audio"]["status"]
                
                with open(self._action_announce_file, 'ab') as f:
                    f.write(audio)
                
                if status == 2:  # 最后一帧
                    print("操作播报音频生成完成")
                    ws.close()
                    
        except Exception as e:
            print(f"操作播报TTS消息处理错误: {e}")
    
    def _on_action_tts_error(self, ws, error):
        """操作播报TTS WebSocket错误处理"""
        print(f"操作播报TTS WebSocket错误: {error}")
    
    def _on_action_tts_close(self, ws, close_status_code, close_msg):
        """操作播报TTS WebSocket关闭处理"""
        pass
    
    def _on_action_tts_open(self, ws, ws_param):
        """操作播报TTS WebSocket开启处理"""
        def run():
            try:
                d = {
                    "header": ws_param.CommonArgs,
                    "parameter": ws_param.BusinessArgs,
                    "payload": ws_param.Data,
                }
                data = json.dumps(d)
                ws.send(data)
                print("操作播报TTS请求已发送")
            except Exception as e:
                print(f"操作播报TTS请求发送错误: {e}")
        
        thread.start_new_thread(run, ())
    
    def _announce_temperature(self, temp_text):
        """播报温度"""
        try:
            # 检查是否有其他语音正在播放
            if self.ai_speaking:
                print("AI正在说话，跳过温度播报")
                return
            
            # 创建WebSocket参数
            ws_param = self._create_tts_param(temp_text)
            
            # 建立WebSocket连接
            requrl = XF_TTS_URL
            ws_url = self._assemble_ws_auth_url(requrl, "GET", XF_API_KEY, XF_API_SECRET)
            
            # 清除旧的温度播报文件
            temp_audio_file = './temp_announce.mp3'
            if os.path.exists(temp_audio_file):
                os.remove(temp_audio_file)
            
            # 设置临时文件名
            self._temp_announce_file = temp_audio_file
            
            # 创建WebSocket连接
            ws = websocket.WebSocketApp(ws_url, 
                                       on_message=self._on_temp_tts_message, 
                                       on_error=self._on_temp_tts_error, 
                                       on_close=self._on_temp_tts_close)
            ws.on_open = lambda ws: self._on_temp_tts_open(ws, ws_param)
            
            # 运行WebSocket
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            
            # 播放生成的音频文件
            if os.path.exists(temp_audio_file):
                # 等待一下确保文件完全写入
                time.sleep(0.1)
                pygame.mixer.music.load(temp_audio_file)
                pygame.mixer.music.set_volume(1.0)  # 确保音量最大
                pygame.mixer.music.play()
                
                # 等待播放完成
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                
                print("温度播报完成")
                
                # 清理临时文件
                try:
                    os.remove(temp_audio_file)
                except:
                    pass
            else:
                print("温度播报音频文件生成失败")
                
        except Exception as e:
            print(f"温度播报错误: {e}")
    
    def _on_temp_tts_message(self, ws, message):
        """温度播报TTS WebSocket消息处理"""
        try:
            message = json.loads(message)
            code = message["header"]["code"]
            
            if code != 0:
                print(f"温度播报TTS错误: {message.get('message', '未知错误')}")
                ws.close()
                return
            
            if "payload" in message:
                audio = message["payload"]["audio"]["audio"]
                audio = base64.b64decode(audio)
                status = message["payload"]["audio"]["status"]
                
                with open(self._temp_announce_file, 'ab') as f:
                    f.write(audio)
                
                if status == 2:  # 最后一帧
                    print("温度播报音频生成完成")
                    ws.close()
                    
        except Exception as e:
            print(f"温度播报TTS消息处理错误: {e}")
    
    def _on_temp_tts_error(self, ws, error):
        """温度播报TTS WebSocket错误处理"""
        print(f"温度播报TTS WebSocket错误: {error}")
    
    def _on_temp_tts_close(self, ws, close_status_code, close_msg):
        """温度播报TTS WebSocket关闭处理"""
        pass
    
    def _on_temp_tts_open(self, ws, ws_param):
        """温度播报TTS WebSocket开启处理"""
        def run():
            try:
                d = {
                    "header": ws_param.CommonArgs,
                    "parameter": ws_param.BusinessArgs,
                    "payload": ws_param.Data,
                }
                data = json.dumps(d)
                ws.send(data)
                print("温度播报TTS请求已发送")
            except Exception as e:
                print(f"温度播报TTS请求发送错误: {e}")
        
        thread.start_new_thread(run, ())


if __name__ == "__main__":
    detector = None
    try:
        detector = GestureDetector()
        detector.run()
    except Exception as e:
        print(f"程序运行错误: {e}")
    finally:
        if detector is not None:
            detector.close()