import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
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

# ================= 1. 系统级 DPI 适配 (解决高分屏偏移) =================
if platform.system() == "Windows":
    try:
        import ctypes
        # 设置进程具有全 DPI 感知能力，确保获取的是物理像素
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

# ================= 2. 强化版多尺度匹配算法 (适配不同分辨率) =================
def robust_match(template_path, region_type="center", confidence=0.75):
    """
    通过多尺度缩放搜索，适配不同显示器的 DPI
    """
    if not os.path.exists(template_path):
        return None
    
    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    sw, sh = pyautogui.size() # 获取当前显示器物理分辨率
    
    # 3. 动态感应区：基于屏幕百分比而非固定像素
    if region_type == "center":
        # 网页按钮搜索区：屏幕中心 60%
        roi = (int(sw*0.2), int(sh*0.2), int(sw*0.6), int(sh*0.6))
    elif region_type == "top":
        # 浏览器弹窗搜索区：屏幕顶部 40%
        roi = (int(sw*0.2), 0, int(sw*0.6), int(sh*0.4))
    else:
        roi = (0, 0, sw, sh)

    screenshot = pyautogui.screenshot(region=roi)
    screen_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    
    best_val = -1
    best_loc = None
    # 扩大缩放范围至 0.5-1.5 倍，步长设为 20，覆盖从笔记本到大屏的缩放差异
    for scale in np.linspace(0.5, 1.5, 20):
        w = int(template.shape[1] * scale)
        h = int(template.shape[0] * scale)
        if w > screen_cv.shape[1] or h > screen_cv.shape[0] or w < 10: continue
        
        resized = cv2.resize(template, (w, h))
        res = cv2.matchTemplate(screen_cv, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        
        if max_val > best_val:
            best_val = max_val
            best_loc = (max_loc[0] + w//2 + roi[0], max_loc[1] + h//2 + roi[1])

    if best_val >= confidence:
        return best_loc, best_val
    return None, best_val

# ================= 3. UI 与 业务逻辑 (保持原始布局) =================
DATA_FILE = "meetings_data.json"
APPLE_BLUE = "#0A84FF"; APPLE_BLUE_HOVER = "#0070DF"
APPLE_GREEN = "#32D74B"; APPLE_GREEN_HOVER = "#28B83D"
APPLE_RED = "#FF453A"; APPLE_RED_HOVER = "#D9362E"
BG_BLACK = "#000000"; CARD_GRAY = "#1C1C1E"; INPUT_GRAY = "#2C2C2E"; TEXT_MUTED = "#8E8E93"

ctk.set_appearance_mode("Dark")

class AutoMeetingApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Tencent Meeting Auto Join")
        self.geometry("820x680")
        self.minsize(780, 600)
        self.configure(fg_color=BG_BLACK)
        
        self.font_hero = ctk.CTkFont(family="Microsoft YaHei UI", size=28, weight="bold")
        self.font_title = ctk.CTkFont(family="Microsoft YaHei UI", size=16, weight="bold")
        self.font_normal = ctk.CTkFont(family="Microsoft YaHei UI", size=14)
        self.font_small = ctk.CTkFont(family="Microsoft YaHei UI", size=12)

        self.meetings = self.load_data()
        self.is_running = False
        self.setup_ui()
        self.refresh_list()

    def setup_ui(self):
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(35, 15))
        ctk.CTkLabel(header_frame, text="日程管理", font=self.font_hero, text_color="#FFFFFF").pack(side="left")

        input_frame = ctk.CTkFrame(self, corner_radius=18, fg_color=CARD_GRAY)
        input_frame.pack(fill="x", padx=25, pady=10)
        
        row1 = ctk.CTkFrame(input_frame, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=(20, 10))
        self.entry_name = ctk.CTkEntry(row1, width=200, height=40, font=self.font_normal, placeholder_text="会议名称", corner_radius=10, fg_color=INPUT_GRAY, border_width=0, text_color="#FFFFFF")
        self.entry_name.pack(side="left", padx=(0, 15))
        self.entry_url = ctk.CTkEntry(row1, height=40, font=self.font_normal, placeholder_text="https://meeting.tencent.com/dm/...", corner_radius=10, fg_color=INPUT_GRAY, border_width=0, text_color="#FFFFFF")
        self.entry_url.pack(side="left", fill="x", expand=True)

        row2 = ctk.CTkFrame(input_frame, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=(0, 20))
        self.combo_day = ctk.CTkComboBox(row2, width=110, height=40, font=self.font_normal, corner_radius=10, values=["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"], state="readonly", fg_color=INPUT_GRAY, border_width=0)
        self.combo_day.set("星期一"); self.combo_day.pack(side="left", padx=(0, 15))
        
        time_frame = ctk.CTkFrame(row2, fg_color="transparent")
        time_frame.pack(side="left", padx=(0, 15))
        self.combo_hour = ctk.CTkComboBox(time_frame, width=70, height=40, values=[f"{i:02d}" for i in range(24)], state="readonly", fg_color=INPUT_GRAY, border_width=0)
        self.combo_hour.set("08"); self.combo_hour.pack(side="left")
        ctk.CTkLabel(time_frame, text=":", font=self.font_title, text_color="#FFFFFF").pack(side="left", padx=5)
        self.combo_minute = ctk.CTkComboBox(time_frame, width=70, height=40, values=[f"{i:02d}" for i in range(60)], state="readonly", fg_color=INPUT_GRAY, border_width=0)
        self.combo_minute.set("30"); self.combo_minute.pack(side="left")
        
        btn_add = ctk.CTkButton(row2, text="添加日程", font=self.font_title, height=40, corner_radius=10, fg_color=APPLE_BLUE, hover_color=APPLE_BLUE_HOVER, command=self.add_meeting)
        btn_add.pack(side="right")

        self.scrollable_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scrollable_frame.pack(fill="both", expand=True, padx=20, pady=10)

        ctrl_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctrl_frame.pack(fill="x", padx=25, pady=(10, 30))
        self.log_text = ctk.CTkTextbox(ctrl_frame, height=90, font=self.font_small, fg_color=CARD_GRAY, text_color=TEXT_MUTED, state="disabled")
        self.log_text.pack(fill="x", pady=(0, 15))
        self.btn_toggle = ctk.CTkButton(ctrl_frame, text="启动自动入会", font=ctk.CTkFont(family="Microsoft YaHei UI", size=18, weight="bold"), fg_color=APPLE_GREEN, hover_color=APPLE_GREEN_HOVER, text_color="#000000", height=55, corner_radius=15, command=self.toggle_service)
        self.btn_toggle.pack(fill="x")

    def log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see("end"); self.log_text.configure(state="disabled")

    def execute_join_process(self, meeting):
        self.log(f"⏰ 正在唤起浏览器: {meeting['name']}")
        webbrowser.open(meeting['url'])
        
        # 强制窗口最大化，使布局归一化
        time.sleep(3) 
        self.log("🪟 强制最大化浏览器窗口以适配屏幕...")
        pyautogui.hotkey('win', 'up') 
        time.sleep(1)

        # 步骤 1: 扫描中心区网页按钮
        self.log("🔍 正在扫描网页加入按钮...")
        pos, val = robust_match("join_btn.png", region_type="center")
        if pos:
            self.log(f"✅ 找到网页按钮 (得分:{val:.2f})")
            pyautogui.click(pos[0], pos[1])
            
            # 步骤 2: 扫描顶部区弹窗按钮
            time.sleep(3)
            self.log("🔍 正在扫描弹窗确认按钮...")
            pos2, val2 = robust_match("open_btn.png", region_type="top")
            if pos2:
                self.log(f"✅ 找到确认按钮 (得分:{val2:.2f})")
                pyautogui.click(pos2[0], pos2[1])
                self.log("✨ 流程执行完毕")
            else:
                self.log("⚠️ 未能识别弹窗按钮，建议检查截图或手动确认")
        else:
            self.log("⚠️ 未发现网页“加入会议”按钮，请检查网页是否被正确加载")

    def scheduler_loop(self):
        days_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}
        triggered = set(); last_min = ""
        self.log("后台监控中...")
        while self.is_running:
            now = datetime.datetime.now()
            curr_day = days_map[now.weekday()]; curr_time = now.strftime("%H:%M")
            if curr_time != last_min: triggered.clear(); last_min = curr_time
            for m in self.meetings:
                if m["day"] == curr_day and m["time"] == curr_time:
                    uid = f"{m['name']}_{curr_time}"
                    if uid not in triggered:
                        triggered.add(uid); threading.Thread(target=self.execute_join_process, args=(m,), daemon=True).start()
            time.sleep(5)

    def toggle_service(self):
        if not self.is_running:
            self.is_running = True
            self.btn_toggle.configure(text="停止自动入会", fg_color=APPLE_RED, hover_color=APPLE_RED_HOVER, text_color="#FFFFFF")
            threading.Thread(target=self.scheduler_loop, daemon=True).start()
        else:
            self.is_running = False
            self.btn_toggle.configure(text="启动自动入会", fg_color=APPLE_GREEN, hover_color=APPLE_GREEN_HOVER, text_color="#000000")
            self.log("监控已停止")

    def load_data(self): return json.load(open(DATA_FILE, "r", encoding="utf-8")) if os.path.exists(DATA_FILE) else []
    def save_data(self): json.dump(self.meetings, open(DATA_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=4)
    def refresh_list(self):
        for w in self.scrollable_frame.winfo_children(): w.destroy()
        for m in self.meetings:
            card = ctk.CTkFrame(self.scrollable_frame, corner_radius=15, fg_color=CARD_GRAY)
            card.pack(fill="x", padx=5, pady=8)
            ctk.CTkLabel(card, text=f"{m['name']} | {m['day']} {m['time']}", font=self.font_title, text_color="#FFFFFF").pack(side="left", padx=20, pady=15)
            ctk.CTkButton(card, text="移除", width=70, fg_color="transparent", text_color=APPLE_RED, command=lambda m=m: self.delete_meeting(m)).pack(side="right", padx=15)
    def add_meeting(self):
        n, u = self.entry_name.get().strip(), self.entry_url.get().strip()
        if not n or not u: return
        self.meetings.append({"name": n, "url": u, "day": self.combo_day.get(), "time": f"{self.combo_hour.get()}:{self.combo_minute.get()}"})
        self.save_data(); self.refresh_list(); self.entry_name.delete(0, 'end'); self.entry_url.delete(0, 'end')
    def delete_meeting(self, m):
        self.meetings = [i for i in self.meetings if i != m]; self.save_data(); self.refresh_list()

if __name__ == "__main__":
    app = AutoMeetingApp(); app.mainloop()