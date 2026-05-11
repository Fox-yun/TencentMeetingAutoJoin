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

if platform.system() == "Windows":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

def multi_scale_match(screenshot, template, min_scale=0.5, max_scale=2.0, steps=20, confidence=0.8):
    gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    
    best_max_val = -1
    best_loc = None
    best_w, best_h = 0, 0
    
    for scale in np.linspace(min_scale, max_scale, steps):
        w = int(gray_template.shape[1] * scale)
        h = int(gray_template.shape[0] * scale)
        if w > gray_screen.shape[1] or h > gray_screen.shape[0] or w == 0 or h == 0: continue
        resized_template = cv2.resize(gray_template, (w, h))
        res = cv2.matchTemplate(gray_screen, resized_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_max_val:
            best_max_val = max_val
            best_loc = max_loc
            best_w, best_h = w, h

    if best_max_val >= confidence:
        center_x = best_loc[0] + best_w // 2
        center_y = best_loc[1] + best_h // 2
        return True, (center_x, center_y), best_max_val
    return False, None, best_max_val

def wait_and_click(template_path, timeout=15, interval=1.0, confidence=0.8, log_callback=print):
    log_callback(f"正在寻找: {template_path} ...")
    if not os.path.exists(template_path):
        log_callback(f" 找不到图片: {template_path}")
        return False
        
    template_img = cv2.imread(template_path)
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        screen_img = pyautogui.screenshot()
        screen_img = cv2.cvtColor(np.array(screen_img), cv2.COLOR_RGB2BGR)
        found, center_pos, val = multi_scale_match(screen_img, template_img, confidence=confidence)
        
        if found:
            log_callback(f" 匹配成功！")
            pyautogui.click(center_pos[0], center_pos[1])
            return True
        time.sleep(interval)
        
    log_callback(f"超时未找到: {template_path}")
    return False

DATA_FILE = "meetings_data.json"

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
        self.scheduler_thread = None
        
        self.setup_ui()
        self.refresh_list()

    def setup_ui(self):
        # --- 顶部大标题 ---
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(35, 15))
        ctk.CTkLabel(header_frame, text="日程管理", font=self.font_hero, text_color="#FFFFFF").pack(side="left")

        # --- 输入区卡片 ---
        input_frame = ctk.CTkFrame(self, corner_radius=18, fg_color=CARD_GRAY)
        input_frame.pack(fill="x", padx=25, pady=10)
        
        # 第一排输入 (名称与链接)
        row1 = ctk.CTkFrame(input_frame, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=(20, 10))
        
        self.entry_name = ctk.CTkEntry(row1, width=200, height=40, font=self.font_normal, 
                                       placeholder_text="会议名称", corner_radius=10, 
                                       fg_color=INPUT_GRAY, border_width=0, text_color="#FFFFFF")
        self.entry_name.pack(side="left", padx=(0, 15))
        
        self.entry_url = ctk.CTkEntry(row1, height=40, font=self.font_normal, 
                                      placeholder_text="https://meeting.tencent.com/dm/...", 
                                      corner_radius=10, fg_color=INPUT_GRAY, border_width=0, text_color="#FFFFFF")
        self.entry_url.pack(side="left", fill="x", expand=True)

        row2 = ctk.CTkFrame(input_frame, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=(0, 20))
        
        self.combo_day = ctk.CTkComboBox(row2, width=110, height=40, font=self.font_normal, corner_radius=10,
                                         values=["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"],
                                         state="readonly", fg_color=INPUT_GRAY, border_width=0, 
                                         button_color=INPUT_GRAY, button_hover_color=CARD_GRAY, dropdown_fg_color=CARD_GRAY)
        self.combo_day.set("星期一")
        self.combo_day.pack(side="left", padx=(0, 15))
        
        time_frame = ctk.CTkFrame(row2, fg_color="transparent")
        time_frame.pack(side="left", padx=(0, 15))
        
        hours = [f"{i:02d}" for i in range(24)]
        self.combo_hour = ctk.CTkComboBox(time_frame, width=70, height=40, font=self.font_normal, corner_radius=10,
                                         values=hours, state="readonly", fg_color=INPUT_GRAY, border_width=0, 
                                         button_color=INPUT_GRAY, button_hover_color=CARD_GRAY, dropdown_fg_color=CARD_GRAY)
        self.combo_hour.set("08")
        self.combo_hour.pack(side="left")
        
        ctk.CTkLabel(time_frame, text=":", font=self.font_title, text_color="#FFFFFF").pack(side="left", padx=5)
        
        minutes = [f"{i:02d}" for i in range(0, 60, 5)]
        self.combo_minute = ctk.CTkComboBox(time_frame, width=70, height=40, font=self.font_normal, corner_radius=10,
                                         values=minutes, state="readonly", fg_color=INPUT_GRAY, border_width=0, 
                                         button_color=INPUT_GRAY, button_hover_color=CARD_GRAY, dropdown_fg_color=CARD_GRAY)
        self.combo_minute.set("30")
        self.combo_minute.pack(side="left")
        # ----------------------------------
        
        btn_add = ctk.CTkButton(row2, text="添加日程", font=self.font_title, height=40, corner_radius=10,
                                fg_color=APPLE_BLUE, hover_color=APPLE_BLUE_HOVER, text_color="#FFFFFF", command=self.add_meeting)
        btn_add.pack(side="right")

        self.scrollable_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.scrollable_frame.pack(fill="both", expand=True, padx=20, pady=10)

        ctrl_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctrl_frame.pack(fill="x", padx=25, pady=(10, 30))
        
        self.log_text = ctk.CTkTextbox(ctrl_frame, height=90, font=self.font_small, 
                                       fg_color=CARD_GRAY, text_color=TEXT_MUTED, corner_radius=12, state="disabled")
        self.log_text.pack(fill="x", pady=(0, 15))
        
        self.btn_toggle = ctk.CTkButton(
            ctrl_frame, text="启动自动入会", font=ctk.CTkFont(family="Microsoft YaHei UI", size=18, weight="bold"),
            fg_color=APPLE_GREEN, hover_color=APPLE_GREEN_HOVER, text_color="#000000",
            height=55, corner_radius=15, command=self.toggle_service
        )
        self.btn_toggle.pack(fill="x")

    def log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def load_data(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def save_data(self):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.meetings, f, ensure_ascii=False, indent=4)

    def refresh_list(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
            
        for m in self.meetings:
            card = ctk.CTkFrame(self.scrollable_frame, corner_radius=15, fg_color=CARD_GRAY)
            card.pack(fill="x", padx=5, pady=8)
            
            info_frame = ctk.CTkFrame(card, fg_color="transparent")
            info_frame.pack(side="left", fill="both", expand=True, padx=20, pady=15)
            
            title_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
            title_frame.pack(fill="x")
            ctk.CTkLabel(title_frame, text=m['name'], font=self.font_title, text_color="#FFFFFF").pack(side="left", padx=(0, 15))
            ctk.CTkLabel(title_frame, text=f"{m['day']} {m['time']}", font=self.font_normal, text_color=APPLE_BLUE).pack(side="left")
            
            ctk.CTkLabel(info_frame, text=m['url'], font=self.font_small, text_color=TEXT_MUTED).pack(anchor="w", pady=(4, 0))
            
            del_btn = ctk.CTkButton(card, text="移除", width=70, height=35, corner_radius=8,
                                    fg_color="transparent", hover_color=INPUT_GRAY, 
                                    text_color=APPLE_RED, font=self.font_normal,
                                    command=lambda meeting=m: self.delete_meeting(meeting))
            del_btn.pack(side="right", padx=15)

    def add_meeting(self):
        name = self.entry_name.get().strip()
        url = self.entry_url.get().strip()
        day = self.combo_day.get().strip()
        
        m_time = f"{self.combo_hour.get()}:{self.combo_minute.get()}"
        
        if not name or not url:
            tk.messagebox.showwarning("提示", "请填写会议名称和链接！")
            return
            
        self.meetings.append({"name": name, "url": url, "day": day, "time": m_time})
        self.save_data()
        self.refresh_list()
        
        self.entry_name.delete(0, 'end')
        self.entry_url.delete(0, 'end')
        self.combo_hour.set("08")
        self.combo_minute.set("30")

    def delete_meeting(self, meeting_to_del):
        self.meetings = [m for m in self.meetings if m != meeting_to_del]
        self.save_data()
        self.refresh_list()

    def execute_join_process(self, meeting):
        self.log(f"正在拉起会议: {meeting['name']}")
        webbrowser.open(meeting['url'])
        
        if wait_and_click("join_btn.png", timeout=20, log_callback=self.log):
            if wait_and_click("open_btn.png", timeout=10, log_callback=self.log):
                self.log("成功进入会议")
            else:
                self.log(" 弹窗确认失败。")
        else:
            self.log(" 网页加载超时或截图不匹配。")

    def scheduler_loop(self):
        days_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}
        triggered_today = set() 
        last_checked_minute = ""

        self.log("监控中...")
        while self.is_running:
            now = datetime.datetime.now()
            current_day = days_map[now.weekday()]
            current_time = now.strftime("%H:%M")
            
            if current_time != last_checked_minute:
                triggered_today.clear()
                last_checked_minute = current_time

            for m in self.meetings:
                if m["day"] == current_day and m["time"] == current_time:
                    uid = f"{m['name']}_{current_time}"
                    if uid not in triggered_today:
                        triggered_today.add(uid)
                        threading.Thread(target=self.execute_join_process, args=(m,), daemon=True).start()
            
            time.sleep(5)

    def toggle_service(self):
        if not self.is_running:
            self.is_running = True
            self.btn_toggle.configure(text="停止自动入会", fg_color=APPLE_RED, hover_color=APPLE_RED_HOVER, text_color="#FFFFFF")
            self.scheduler_thread = threading.Thread(target=self.scheduler_loop, daemon=True)
            self.scheduler_thread.start()
        else:
            self.is_running = False
            self.btn_toggle.configure(text="启动自动入会", fg_color=APPLE_GREEN, hover_color=APPLE_GREEN_HOVER, text_color="#000000")
            self.log("已停止监控。")

if __name__ == "__main__":
    app = AutoMeetingApp()
    app.mainloop()