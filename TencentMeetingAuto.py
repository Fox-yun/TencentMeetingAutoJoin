import customtkinter as ctk
import json
import os
import threading
import time
import datetime
import webbrowser
import cv2
import numpy as np
import pyautogui
import platform
from functools import partial
from typing import Optional, Tuple

# ================== 全局优化 ==================
# 解决 Windows 缩放导致截图不匹配的问题
if platform.system() == "Windows":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

# 全局缓存：模板图像、缩放倍率、屏幕区域
TEMPLATE_CACHE = {}          # path -> (image, width, height)
SCALE_CACHE = {}             # path -> scale
ROI_CACHE = {}               # region_type -> (x, y, w, h)

DATA_FILE = "meetings_data.json"

# 颜色常量
APPLE_BLUE = "#0A84FF"
APPLE_BLUE_HOVER = "#0070DF"
APPLE_GREEN = "#32D74B"
APPLE_GREEN_HOVER = "#28B83D"
APPLE_RED = "#FF453A"
APPLE_RED_HOVER = "#D9362E"
BG_BLACK = "#000000"
CARD_GRAY = "#1C1C1E"
INPUT_GRAY = "#2C2C2E"
TEXT_MUTED = "#8E8E93"

ctk.set_appearance_mode("Dark")


# ================== 辅助函数 ==================
def get_roi(region_type: str, screen_width: int, screen_height: int) -> Tuple[int, int, int, int]:
    """获取预先定义好的截图区域（缓存）"""
    key = (region_type, screen_width, screen_height)
    if key in ROI_CACHE:
        return ROI_CACHE[key]

    if region_type == "center":
        roi = (int(screen_width * 0.2), int(screen_height * 0.2),
               int(screen_width * 0.6), int(screen_height * 0.6))
    elif region_type == "top":
        roi = (int(screen_width * 0.2), 0,
               int(screen_width * 0.6), int(screen_height * 0.4))
    else:
        roi = (0, 0, screen_width, screen_height)

    ROI_CACHE[key] = roi
    return roi


def load_template(template_path: str):
    """加载模板图像并缓存"""
    if template_path in TEMPLATE_CACHE:
        return TEMPLATE_CACHE[template_path]

    if not os.path.exists(template_path):
        return None

    img = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    h, w = img.shape
    TEMPLATE_CACHE[template_path] = (img, w, h)
    return img, w, h


def robust_match(template_path: str, region_type: str = "center", confidence: float = 0.75) -> Tuple[Optional[Tuple[int, int]], float]:
    """尝试在屏幕上匹配指定模板，支持缩放与模板双重缓存"""
    template_data = load_template(template_path)
    if template_data is None:
        return None, 0.0

    template, tw, th = template_data
    screen_w, screen_h = pyautogui.size()
    roi = get_roi(region_type, screen_w, screen_h)

    # 截图并转换为灰度图
    screenshot = pyautogui.screenshot(region=roi)
    screen_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)

    best_val = -1.0
    best_loc = None
    best_scale = None

    if template_path in SCALE_CACHE:
        scales_to_check = [SCALE_CACHE[template_path]]
    else:
        # 优化：减少遍历步数，从 20 减到 10（步长 0.1）
        scales_to_check = np.linspace(0.5, 1.5, 10)

    for scale in scales_to_check:
        w = int(tw * scale)
        h = int(th * scale)
        if w > screen_cv.shape[1] or h > screen_cv.shape[0] or w < 10:
            continue

        resized = cv2.resize(template, (w, h))
        res = cv2.matchTemplate(screen_cv, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val > best_val:
            best_val = max_val
            best_loc = (max_loc[0] + w // 2 + roi[0], max_loc[1] + h // 2 + roi[1])
            best_scale = scale

    if template_path in SCALE_CACHE and best_val < confidence:
        SCALE_CACHE.pop(template_path, None)
        return robust_match(template_path, region_type, confidence)

    if best_val >= confidence:
        SCALE_CACHE[template_path] = best_scale
        return best_loc, best_val

    return None, best_val


# ================== 主应用类 ==================
class AutoMeetingApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Tencent Meeting Auto Join")
        self.geometry("820x680")
        self.minsize(780, 600)
        self.configure(fg_color=BG_BLACK)

        # 字体
        self.font_hero = ctk.CTkFont(family="Microsoft YaHei UI", size=28, weight="bold")
        self.font_title = ctk.CTkFont(family="Microsoft YaHei UI", size=16, weight="bold")
        self.font_normal = ctk.CTkFont(family="Microsoft YaHei UI", size=14)
        self.font_small = ctk.CTkFont(family="Microsoft YaHei UI", size=12)

        # 数据与状态
        self.meetings = self.load_data()
        self.meetings_lock = threading.Lock()      # 保护 meetings 列表的线程锁
        self.is_running = threading.Event()
        self.scheduler_thread = None

        self.setup_ui()
        self.refresh_list()
        
        # 检查模板文件是否存在
        self.check_templates()
        
        # 启动解耦的倒计时UI刷新循环 (每5秒刷新一次界面)
        self.start_countdown_loop()
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ------------------ 模板文件检查 ------------------
    def check_templates(self):
        for tpl in ["join_btn.png", "open_btn.png"]:
            if not os.path.exists(tpl):
                self.log(f"⚠️ 警告：模板文件 {tpl} 不存在，自动识别将失效")

   # ------------------ UI 构建 ------------------
    def setup_ui(self):
        # 1. 顶部标题区
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(35, 15))
        ctk.CTkLabel(header_frame, text="日程管理", font=self.font_hero, text_color="#FFFFFF").pack(side="left")

        # 2. 表单输入区
        input_frame = ctk.CTkFrame(self, corner_radius=18, fg_color=CARD_GRAY)
        input_frame.pack(fill="x", padx=25, pady=10)

        # 第一行：名称 + 链接
        row1 = ctk.CTkFrame(input_frame, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=(20, 10))
        self.entry_name = ctk.CTkEntry(row1, width=200, height=40, font=self.font_normal,
                                       placeholder_text="会议名称", corner_radius=10,
                                       fg_color=INPUT_GRAY, border_width=0, text_color="#FFFFFF")
        self.entry_name.pack(side="left", padx=(0, 15))
        self.entry_url = ctk.CTkEntry(row1, height=40, font=self.font_normal,
                                      placeholder_text="https://meeting.tencent.com/dm/...", corner_radius=10,
                                      fg_color=INPUT_GRAY, border_width=0, text_color="#FFFFFF")
        self.entry_url.pack(side="left", fill="x", expand=True)

        # 第二行：星期、时间、添加按钮
        row2 = ctk.CTkFrame(input_frame, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=(0, 20))
        self.combo_day = ctk.CTkComboBox(row2, width=110, height=40, font=self.font_normal,
                                         values=["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"],
                                         state="readonly", fg_color=INPUT_GRAY, border_width=0)
        self.combo_day.set("星期一")
        self.combo_day.pack(side="left", padx=(0, 15))

        time_frame = ctk.CTkFrame(row2, fg_color="transparent")
        time_frame.pack(side="left", padx=(0, 15))
        self.combo_hour = ctk.CTkComboBox(time_frame, width=70, height=40,
                                          values=[f"{i:02d}" for i in range(24)],
                                          state="readonly", fg_color=INPUT_GRAY, border_width=0)
        self.combo_hour.set("08")
        self.combo_hour.pack(side="left")
        ctk.CTkLabel(time_frame, text=":", font=self.font_title, text_color="#FFFFFF").pack(side="left", padx=5)
        self.combo_minute = ctk.CTkComboBox(time_frame, width=70, height=40,
                                            values=[f"{i:02d}" for i in range(0, 60, 5)],
                                            state="readonly", fg_color=INPUT_GRAY, border_width=0)
        self.combo_minute.set("30")
        self.combo_minute.pack(side="left")

        btn_add = ctk.CTkButton(row2, text="添加日程", font=self.font_title, height=40,
                                corner_radius=10, fg_color=APPLE_BLUE, hover_color=APPLE_BLUE_HOVER,
                                command=self.add_meeting)
        btn_add.pack(side="right")

        # ================= 核心修改点 =================
        # 3. 底部控制区（优先打包并锁定在窗口底部，防止被挤压）
        ctrl_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctrl_frame.pack(side="bottom", fill="x", padx=25, pady=(10, 30))

        self.log_text = ctk.CTkTextbox(ctrl_frame, height=90, font=self.font_small,
                                       fg_color=CARD_GRAY, text_color=TEXT_MUTED, state="disabled")
        self.log_text.pack(fill="x", pady=(0, 15))

        self.next_meeting_label = ctk.CTkLabel(ctrl_frame, text="⏰ 暂无日程", font=self.font_small, text_color=TEXT_MUTED)
        self.next_meeting_label.pack(pady=(0, 5))

        self.btn_toggle = ctk.CTkButton(ctrl_frame, text="启动自动入会",
                                        font=ctk.CTkFont(family="Microsoft YaHei UI", size=18, weight="bold"),
                                        fg_color=APPLE_GREEN, hover_color=APPLE_GREEN_HOVER,
                                        text_color="#000000", height=55, corner_radius=15,
                                        command=self.toggle_service)
        # 固定按钮大小，防止组件在水平方向意外变形
        self.btn_toggle.pack(fill="x", expand=False)

        # 4. 日程列表（最后打包，吸附在顶部并利用 expand=True 占据上下夹击后剩余的所有中间空间）
        self.scrollable_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scrollable_frame.pack(side="top", fill="both", expand=True, padx=20, pady=10)
        # ============================================

    # ------------------ 日志系统（线程安全 + 内存防溢出）------------------
    def log(self, msg: str):
        self.after(0, self._safe_log, msg)

    def _safe_log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        
        # 控制最大行数，防止挂机内存溢出卡死（保留最近80行）
        lines = int(self.log_text.index('end-1c').split('.')[0])
        if lines > 80:
            self.log_text.delete("1.0", f"{lines - 80}.0")
            
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ------------------ 点击辅助 ------------------
    def wait_and_click(self, template_path: str, region_type: str,
                       timeout: float = 15, interval: float = 0.5) -> Tuple[bool, float]:
        start = time.time()
        current_interval = interval
        while time.time() - start < timeout:
            pos, val = robust_match(template_path, region_type=region_type)
            if pos:
                try:
                    pyautogui.click(pos[0], pos[1])
                    return True, val
                except Exception as e:
                    self.log(f"点击失败: {e}")
                    return False, val
            time.sleep(current_interval)
            current_interval = min(1.0, current_interval * 1.2)
        return False, 0.0

    # ------------------ 自动入会流程 ------------------
    def execute_join_process(self, meeting: dict):
        self.log(f"正在唤起浏览器: {meeting['name']}")
        try:
            webbrowser.open(meeting['url'])
        except Exception as e:
            self.log(f"无法打开浏览器: {e}")
            return

        time.sleep(3.5)  # 给浏览器基础启动时间
        
        # 优化窗口最大化：先还原再最大化，确保焦点
        try:
            sw, sh = pyautogui.size()
            # 在屏幕上半部分安全点击一下激活窗口
            pyautogui.click(sw // 2, sh // 4)
            time.sleep(0.3)
            # 先还原窗口（Win+Down）再最大化（Win+Up），使窗口适应屏幕
            pyautogui.hotkey('win', 'down')
            time.sleep(0.2)
            self.log("尝试最大化浏览器窗口以适配屏幕...")
            pyautogui.hotkey('win', 'up')
        except Exception:
            self.log("窗口最大化操作异常，将尝试在当前视图中匹配")

        self.log("正在等待网页加载并扫描加入按钮...")
        success_web, val = self.wait_and_click("join_btn.png", region_type="center", timeout=15)
        if success_web:
            self.log(f"找到网页按钮并点击 (得分:{val:.2f})")
            self.log("正在扫描弹窗确认按钮...")
            success_popup, val2 = self.wait_and_click("open_btn.png", region_type="top", timeout=10)
            if success_popup:
                self.log(f"找到确认按钮并点击 (得分:{val2:.2f})")
                self.log("流程执行完毕")
            else:
                self.log("未能识别弹窗按钮，等待超时，请检查截图或手动确认")
        else:
            self.log("未能发现网页“加入会议”按钮，等待超时，请检查网页是否被正确加载")

    # ------------------ 后台调度线程 ------------------
    def scheduler_loop(self):
        days_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四",
                    4: "星期五", 5: "星期六", 6: "星期日"}
        triggered = set()
        last_min = ""
        self.log("后台监控已启动...")

        while self.is_running.is_set():
            now = datetime.datetime.now()
            curr_day = days_map[now.weekday()]
            curr_time = now.strftime("%H:%M")

            if curr_time != last_min:
                triggered.clear()
                last_min = curr_time

            # 线程安全地复制 meetings 列表
            with self.meetings_lock:
                meetings_copy = self.meetings.copy()

            for m in meetings_copy:
                if m["day"] == curr_day and m["time"] == curr_time:
                    uid = f"{m['name']}_{curr_time}"
                    if uid not in triggered:
                        triggered.add(uid)
                        threading.Thread(target=self.execute_join_process, args=(m,), daemon=True).start()

            # 使用 wait 替代 sleep，使得停止服务时能立即响应
            self.is_running.wait(5)

    # ------------------ UI 解耦倒计时系统 ------------------
    def start_countdown_loop(self):
        self.update_next_meeting_countdown()
        self.after(5000, self.start_countdown_loop)  # 每5秒刷新一次

    def update_next_meeting_countdown(self):
        with self.meetings_lock:
            if not self.meetings:
                self.next_meeting_label.configure(text="⏰ 暂无日程")
                return

        now = datetime.datetime.now()
        days_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四",
                    4: "星期五", 5: "星期六", 6: "星期日"}
        today_weekday = now.weekday()

        upcoming = []
        with self.meetings_lock:
            for m in self.meetings:
                target_weekday = list(days_map.values()).index(m["day"])
                hour, minute = map(int, m["time"].split(":"))
                target_time = datetime.time(hour, minute)

                days_ahead = target_weekday - today_weekday
                if days_ahead < 0:
                    days_ahead += 7
                if days_ahead == 0:
                    target_datetime = datetime.datetime.combine(now.date(), target_time)
                    if target_datetime <= now:
                        days_ahead = 7
                        
                target_date = now.date() + datetime.timedelta(days=days_ahead)
                target_datetime = datetime.datetime.combine(target_date, target_time)
                upcoming.append((target_datetime, m["name"]))

        if not upcoming:
            self.next_meeting_label.configure(text="⏰ 无有效日程")
            return

        next_time, name = min(upcoming, key=lambda x: x[0])
        delta = next_time - now
        
        if delta.total_seconds() <= 0:
            ui_text = f"⏰ 即将开始: {name}"
        else:
            hours, rem = divmod(delta.total_seconds(), 3600)
            minutes, _ = divmod(rem, 60)
            ui_text = f"⏰ 下一个日程: {name} 将于 {int(hours)}小时{int(minutes)}分钟后开始"
            
        self.next_meeting_label.configure(text=ui_text)

    # ------------------ 电源管理 ------------------
    def set_keep_awake(self, keep_awake: bool):
        if platform.system() != "Windows":
            return
        try:
            import ctypes
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            if keep_awake:
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            else:
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except Exception as e:
            self.log(f"设置电源状态失败: {e}")

    # ------------------ 启动/停止服务 ------------------
    def toggle_service(self):
        if not self.is_running.is_set():
            self.is_running.set()
            self.btn_toggle.configure(text="停止自动入会", fg_color=APPLE_RED,
                                      hover_color=APPLE_RED_HOVER, text_color="#FFFFFF")
            self.set_keep_awake(True)
            self.scheduler_thread = threading.Thread(target=self.scheduler_loop, daemon=False)
            self.scheduler_thread.start()
        else:
            self.is_running.clear()
            self.btn_toggle.configure(text="启动自动入会", fg_color=APPLE_GREEN,
                                      hover_color=APPLE_GREEN_HOVER, text_color="#000000")
            self.set_keep_awake(False)
            if self.scheduler_thread and self.scheduler_thread.is_alive():
                self.scheduler_thread.join(timeout=2.0)  # 等待线程结束最多2秒
            self.log("监控已停止")

    # ------------------ 数据持久化与界面交互 ------------------
    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.log(f"加载配置文件失败: {e}")
        return []

    def save_data(self):
        try:
            with self.meetings_lock:
                data = self.meetings.copy()
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.log(f"保存配置失败: {e}")

    def refresh_list(self):
        # 清除旧列表
        for w in self.scrollable_frame.winfo_children():
            w.destroy()
        
        with self.meetings_lock:
            meetings_copy = self.meetings.copy()

        for m in meetings_copy:
            card = ctk.CTkFrame(self.scrollable_frame, corner_radius=15, fg_color=CARD_GRAY)
            card.pack(fill="x", padx=5, pady=8)
            ctk.CTkLabel(card, text=f"{m['name']} | {m['day']} {m['time']}",
                         font=self.font_title, text_color="#FFFFFF").pack(side="left", padx=20, pady=15)
            ctk.CTkButton(card, text="移除", width=70, fg_color="transparent",
                          text_color=APPLE_RED, command=partial(self.delete_meeting, m)).pack(side="right", padx=15)

    def add_meeting(self):
        name = self.entry_name.get().strip()
        url = self.entry_url.get().strip()
        if not name or not url:
            self.log("请填写会议名称和链接")
            return
        new_meeting = {
            "name": name,
            "url": url,
            "day": self.combo_day.get(),
            "time": f"{self.combo_hour.get()}:{self.combo_minute.get()}"
        }
        with self.meetings_lock:
            self.meetings.append(new_meeting)
        self.save_data()
        self.refresh_list()
        self.entry_name.delete(0, 'end')
        self.entry_url.delete(0, 'end')
        self.log(f"已添加日程: {name}")

    def delete_meeting(self, meeting):
        with self.meetings_lock:
            self.meetings = [m for m in self.meetings if m != meeting]
        self.save_data()
        self.refresh_list()
        self.log(f"已移除日程: {meeting['name']}")

    # ------------------ 程序退出清理 ------------------
    def on_closing(self):
        if self.is_running.is_set():
            self.toggle_service()   # 停止监控并等待线程结束
        self.set_keep_awake(False)
        self.destroy()

if __name__ == "__main__":
    app = AutoMeetingApp()
    app.mainloop()