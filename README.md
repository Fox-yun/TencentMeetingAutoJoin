腾讯会议自动入会管家

一个基于 Python 的定时入会辅助工具，支持图像识别自动点击。
1. 核心功能
定时唤起：根据预设的星期和时间自动打开会议链接。
模拟点击：利用 OpenCV 自动识别并点击网页按钮及浏览器弹窗。
本地日程：日程信息以 JSON 格式存储于本地，不上传云端。
2. 快速开始
安装依赖：
Bash
pip install pyautogui opencv-python numpy customtkinter
运行程序：
Bash
python TencentMeetingAuto.py
3. 图片准备
必须在程序同级目录下放置以下截图：
join_btn.png：网页中间蓝色的“加入会议”按钮。
open_chrome.png（或 open_edge.png）：浏览器顶部的“打开腾讯会议”弹窗按钮。
4. 打包 EXE
Bash
pyinstaller -F -w TencentMeetingAuto.py
注：打包后的 .exe 必须与 .png 截图文件放在同一个文件夹内才能正常工作。
5. 注意事项
电源设置：运行期间电脑需保持开机，不能进入“睡眠”或“休眠”状态。
缩放比例：截图时的系统 DPI 缩放需与运行脚本时保持一致，否则图像识别可能会失效。
