#!/usr/bin/env python3
"""
手机数据恢复 — 独立 APK 版
基于 Kivy 框架，打包为 Android APK 直接安装运行
无需 Termux，无需任何依赖
"""

import os
import sys
import threading
from pathlib import Path
from datetime import datetime
from functools import partial

# ─── Kivy 配置 ──────────────────────────────────────────
from kivy.config import Config
Config.set("graphics", "width", "400")
Config.set("graphics", "height", "720")
Config.set("kivy", "window_icon", "icon.png")

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.image import Image as KivyImage
from kivy.uix.popup import Popup
from kivy.uix.switch import Switch
from kivy.uix.checkbox import CheckBox
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.behaviors import ButtonBehavior
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.utils import platform

# ─── 导入恢复引擎 ──────────────────────────────────────
from recovery_engine import RecoveryEngine, ScanProgress

# ─── 颜色主题 ──────────────────────────────────────────
COLORS = {
    "bg": (0.04, 0.04, 0.08, 1),
    "card": (0.08, 0.08, 0.14, 1),
    "card2": (0.10, 0.10, 0.18, 1),
    "border": (0.14, 0.14, 0.25, 1),
    "text": (0.88, 0.88, 0.93, 1),
    "text_dim": (0.50, 0.50, 0.60, 1),
    "accent": (0.31, 0.56, 1.0, 1),
    "accent_dark": (0.20, 0.40, 0.85, 1),
    "danger": (1.0, 0.28, 0.34, 1),
    "success": (0.18, 0.83, 0.45, 1),
    "warning": (1.0, 0.65, 0.0, 1),
    "white": (1, 1, 1, 1),
}

# ─── 辅助组件 ──────────────────────────────────────────

class RoundedButton(Button):
    """圆角按钮"""
    def __init__(self, color=None, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_color = (0, 0, 0, 0)
        self.color = COLORS["white"]
        self.font_size = sp(14)
        self.bold = True
        self.btn_color = color or COLORS["accent"]
        self.bind(pos=self._update, size=self._update)

    def _update(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*self.btn_color)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(8)])

    def on_press(self):
        self.btn_color = tuple(c * 0.85 for c in self.btn_color[:3]) + (1,)

    def on_release(self):
        self.btn_color = COLORS.get("accent", (0.31, 0.56, 1.0, 1))


class Card(BoxLayout):
    """卡片容器"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.padding = dp(12)
        self.spacing = dp(8)
        self.size_hint_y = None
        self.bind(minimum_height=self.setter("height"))
        with self.canvas.before:
            Color(*COLORS["card"])
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
        self.bind(pos=self._update_rect, size=self._update_rect)

    def _update_rect(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size


class StatItem(BoxLayout):
    """统计数字"""
    def __init__(self, value="0", label="", color=None, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.size_hint_x = 1
        self.val_label = Label(
            text=str(value), font_size=sp(28), bold=True,
            color=color or COLORS["text"], size_hint_y=None, height=dp(36)
        )
        self.desc_label = Label(
            text=label, font_size=sp(11),
            color=COLORS["text_dim"], size_hint_y=None, height=dp(18)
        )
        self.add_widget(self.val_label)
        self.add_widget(self.desc_label)

    def set_value(self, value):
        self.val_label.text = str(value)


class FileListItem(BoxLayout):
    """文件列表项"""
    def __init__(self, file_info, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(56)
        self.padding = dp(8)
        self.spacing = dp(10)
        self.file_info = file_info
        self.app = app_ref

        # 类别图标
        icons = {"photo": "🖼", "audio": "🎵", "video": "🎬"}
        icon = Label(
            text=icons.get(file_info.category, "📄"),
            font_size=sp(20), size_hint_x=None, width=dp(40),
            color=COLORS["text"]
        )
        self.add_widget(icon)

        # 文件信息
        info_box = BoxLayout(orientation="vertical", size_hint_x=1)
        info_box.add_widget(Label(
            text=file_info.name[:30], font_size=sp(12), bold=True,
            color=COLORS["text"], halign="left",
            text_size=(dp(180), None), shorten=True, shorten_from="right",
            size_hint_y=None, height=dp(18)
        ))
        info_box.add_widget(Label(
            text=f"{self._format_size(file_info.size)} · {file_info.format.upper()}",
            font_size=sp(10), color=COLORS["text_dim"],
            halign="left", size_hint_y=None, height=dp(16)
        ))
        self.add_widget(info_box)

        # 操作按钮
        if file_info.preview_possible:
            btn = Button(text="👁", font_size=sp(16), size_hint_x=None, width=dp(36),
                         background_normal="", background_color=(0,0,0,0),
                         color=COLORS["accent"])
            btn.bind(on_release=lambda x: self._preview())
            self.add_widget(btn)

        btn2 = Button(text="⬇", font_size=sp(16), size_hint_x=None, width=dp(36),
                      background_normal="", background_color=(0,0,0,0),
                      color=COLORS["success"])
        btn2.bind(on_release=lambda x: self._save())
        self.add_widget(btn2)

    def _format_size(self, size_bytes):
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    def _preview(self):
        try:
            data = open(self.file_info.path, "rb").read()
            self.app.show_preview(data, self.file_info.format)
        except Exception:
            self.app.show_toast("无法预览此文件")

    def _save(self):
        # 复制到 Download 目录
        try:
            import shutil
            download_dir = "/sdcard/Download/RecoveredFiles"
            os.makedirs(download_dir, exist_ok=True)
            dst = os.path.join(download_dir, self.file_info.name)
            shutil.copy2(self.file_info.path, dst)
            self.app.show_toast(f"已保存到 Download/RecoveredFiles")
        except Exception as e:
            self.app.show_toast(f"保存失败: {e}")


# ─── 界面屏幕 ──────────────────────────────────────────

class WelcomeScreen(Screen):
    """欢迎页"""
    pass


class ScanScreen(Screen):
    """扫描页"""
    pass


class ResultsScreen(Screen):
    """结果页"""
    pass


# ─── 主应用 ────────────────────────────────────────────

class RecoveryApp(App):
    """手机数据恢复 App"""

    title = "手机数据恢复"
    icon = "icon.png"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.engine = None
        self.scan_thread = None
        self._stop_flag = threading.Event()
        self.found_files = []
        self.output_dir = "/sdcard/RecoveredFiles"

    def build(self):
        Window.clearcolor = COLORS["bg"]
        self.root = self._build_ui()
        Clock.schedule_once(self._check_permissions, 0.5)
        return self.root

    def _build_ui(self):
        """构建主界面"""
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))

        # ── 顶部标题栏 ──
        header = BoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(80),
            padding=[0, dp(8)]
        )
        header.add_widget(Label(
            text="📱 手机数据恢复",
            font_size=sp(22), bold=True,
            color=COLORS["accent"], size_hint_y=None, height=dp(32)
        ))
        header.add_widget(Label(
            text="恢复已删除的照片 · 音频 · 视频",
            font_size=sp(12), color=COLORS["text_dim"],
            size_hint_y=None, height=dp(20)
        ))
        self._status_label = Label(
            text="准备就绪", font_size=sp(11),
            color=COLORS["success"], size_hint_y=None, height=dp(18)
        )
        header.add_widget(self._status_label)
        root.add_widget(header)

        # ── 权限状态卡片 ──
        self._perm_card = Card(size_hint_y=None, height=dp(70))
        perm_layout = BoxLayout(orientation="horizontal", spacing=dp(10))
        self._perm_icon = Label(
            text="⚠", font_size=sp(20), size_hint_x=None, width=dp(30),
            color=COLORS["warning"]
        )
        self._perm_text = Label(
            text="检查存储权限...", font_size=sp(12),
            color=COLORS["text_dim"], halign="left",
            size_hint_x=1, text_size=(dp(250), None)
        )
        perm_layout.add_widget(self._perm_icon)
        perm_layout.add_widget(self._perm_text)
        self._perm_card.add_widget(perm_layout)
        root.add_widget(self._perm_card)

        # ── 扫描设置卡片 ──
        settings_card = Card(size_hint_y=None, height=dp(160))
        settings_card.add_widget(Label(
            text="扫描设置", font_size=sp(14), bold=True,
            color=COLORS["text"], size_hint_y=None, height=dp(24)
        ))

        # 类别选择
        cat_layout = BoxLayout(
            orientation="horizontal", spacing=dp(8),
            size_hint_y=None, height=dp(40)
        )
        self._cat_photo = self._make_category_btn("📷 照片", True)
        self._cat_audio = self._make_category_btn("🎵 音频", True)
        self._cat_video = self._make_category_btn("🎬 视频", False)
        cat_layout.add_widget(self._cat_photo)
        cat_layout.add_widget(self._cat_audio)
        cat_layout.add_widget(self._cat_video)
        settings_card.add_widget(cat_layout)

        # 选项开关
        opt_layout = BoxLayout(
            orientation="horizontal", spacing=dp(12),
            size_hint_y=None, height=dp(36)
        )
        thumb_label = Label(
            text="扫描缩略图缓存", font_size=sp(12),
            color=COLORS["text_dim"], size_hint_x=1, halign="left",
            text_size=(dp(180), None)
        )
        self._thumb_switch = Switch(active=True)
        opt_layout.add_widget(thumb_label)
        opt_layout.add_widget(self._thumb_switch)
        settings_card.add_widget(opt_layout)

        root.add_widget(settings_card)

        # ── 扫描按钮 ──
        self._scan_btn = RoundedButton(
            text="🚀 开始扫描", color=COLORS["accent"],
            size_hint_y=None, height=dp(48)
        )
        self._scan_btn.bind(on_release=self._start_scan)
        root.add_widget(self._scan_btn)

        # ── 进度区 ──
        self._progress_card = Card(size_hint_y=None, height=dp(80))
        self._progress_card.opacity = 0
        self._progress_bar = ProgressBar(
            max=100, value=0, size_hint_y=None, height=dp(8)
        )
        self._progress_text = Label(
            text="准备扫描...", font_size=sp(11),
            color=COLORS["text_dim"], size_hint_y=None, height=dp(18)
        )
        self._found_label = Label(
            text="已找到: 0 个文件", font_size=sp(12),
            color=COLORS["success"], size_hint_y=None, height=dp(18)
        )
        self._progress_card.add_widget(self._progress_text)
        self._progress_card.add_widget(self._progress_bar)
        self._progress_card.add_widget(self._found_label)
        root.add_widget(self._progress_card)

        # ── 统计区 ──
        self._stats_card = Card(size_hint_y=None, height=dp(80))
        self._stats_card.opacity = 0
        stats_layout = BoxLayout(orientation="horizontal", spacing=dp(8))
        self._stat_photo = StatItem(value="0", label="📷 照片", color=(1, 0.42, 0.50, 1))
        self._stat_audio = StatItem(value="0", label="🎵 音频", color=(0.18, 0.83, 0.45, 1))
        self._stat_video = StatItem(value="0", label="🎬 视频", color=(0.31, 0.56, 1.0, 1))
        stats_layout.add_widget(self._stat_photo)
        stats_layout.add_widget(self._stat_audio)
        stats_layout.add_widget(self._stat_video)
        self._stats_card.add_widget(stats_layout)
        root.add_widget(self._stats_card)

        # ── 文件列表 ──
        list_header = Label(
            text="已恢复文件", font_size=sp(14), bold=True,
            color=COLORS["text"], size_hint_y=None, height=dp(24)
        )
        root.add_widget(list_header)

        self._file_scroll = ScrollView(size_hint=(1, 1))
        self._file_list = GridLayout(
            cols=1, spacing=dp(2), size_hint_y=None
        )
        self._file_list.bind(minimum_height=self._file_list.setter("height"))
        self._file_scroll.add_widget(self._file_list)
        root.add_widget(self._file_scroll)

        # ── 底部操作栏 ──
        bottom = BoxLayout(
            orientation="horizontal", spacing=dp(8),
            size_hint_y=None, height=dp(44)
        )
        self._stop_btn = RoundedButton(
            text="⏹ 停止", color=COLORS["danger"],
            size_hint_x=1
        )
        self._stop_btn.bind(on_release=self._stop_scan)
        self._stop_btn.disabled = True
        self._clean_btn = Button(
            text="🗑 清理全部", font_size=sp(12), size_hint_x=1,
            background_normal="", background_color=(0,0,0,0),
            color=COLORS["danger"]
        )
        self._clean_btn.bind(on_release=self._cleanup)
        bottom.add_widget(self._stop_btn)
        bottom.add_widget(self._clean_btn)
        root.add_widget(bottom)

        self._toast_label = Label(
            text="", font_size=sp(12), color=COLORS["white"],
            size_hint_y=None, height=dp(28), opacity=0
        )
        root.add_widget(self._toast_label)

        return root

    def _make_category_btn(self, text, active):
        btn = Button(
            text=text, font_size=sp(11), size_hint_x=1,
            background_normal="", background_color=COLORS["accent"] if active else COLORS["card2"],
            color=COLORS["white"] if active else COLORS["text_dim"],
            bold=active
        )
        btn.active = active
        btn.bind(on_release=lambda x: self._toggle_category(x))
        return btn

    def _toggle_category(self, btn):
        btn.active = not btn.active
        btn.background_color = COLORS["accent"] if btn.active else COLORS["card2"]
        btn.color = COLORS["white"] if btn.active else COLORS["text_dim"]
        btn.bold = btn.active

    # ── 权限处理 ────────────────────────────────────
    @mainthread
    def _check_permissions(self, dt):
        if platform == "android":
            from android.permissions import request_permissions, check_permission, Permission
            perms = [Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE]
            missing = []
            for p in perms:
                if not check_permission(p):
                    missing.append(p)
            if missing:
                request_permissions(missing, self._on_permissions_result)
            else:
                self._on_permissions_result(missing, [])
        else:
            # 桌面端无需权限
            self._perm_icon.text = "✓"
            self._perm_icon.color = COLORS["success"]
            self._perm_text.text = "桌面模式 - 无需权限 (编译为APK后自动请求)"
            self._status_label.text = "就绪"

    def _on_permissions_result(self, permissions, grants):
        all_granted = all(grants) if grants else True
        if all_granted:
            self._perm_icon.text = "✓"
            self._perm_icon.color = COLORS["success"]
            self._perm_text.text = "存储权限已授权 ✓"
            self._status_label.text = "就绪"
        else:
            self._perm_icon.text = "⚠"
            self._perm_icon.color = COLORS["danger"]
            self._perm_text.text = "存储权限被拒绝！请在系统设置中授权"
            self._status_label.text = "需要权限"

    # ── 扫描控制 ────────────────────────────────────
    def _start_scan(self, instance):
        self._stop_flag.clear()
        self._scan_btn.disabled = True
        self._stop_btn.disabled = False
        self._progress_card.opacity = 1
        self._stats_card.opacity = 1
        self._progress_text.text = "准备扫描..."
        self._progress_bar.value = 0
        self._found_label.text = "已找到: 0 个文件"
        self._status_label.text = "扫描中..."

        # 清空旧结果
        self._file_list.clear_widgets()

        # 确定类别
        categories = []
        if self._cat_photo.active:
            categories.append("photo")
        if self._cat_audio.active:
            categories.append("audio")
        if self._cat_video.active:
            categories.append("video")

        # 在后台线程启动引擎
        self.engine = RecoveryEngine(output_dir=self.output_dir)
        self.engine.progress_callback = self._on_progress
        self.found_files = []

        self.scan_thread = threading.Thread(
            target=self._run_scan,
            args=(categories,),
            daemon=True
        )
        self.scan_thread.start()

    def _run_scan(self, categories):
        try:
            scan_path = "/sdcard"
            if os.path.exists("/storage/emulated/0"):
                scan_path = "/storage/emulated/0"

            result = self.engine.full_scan(
                base_path=scan_path,
                scan_raw=False,
                scan_thumbnails=self._thumb_switch.active,
                categories=categories if categories else None,
            )
            self.found_files = self.engine.found_files
            Clock.schedule_once(lambda dt: self._on_scan_complete(result), 0)
        except Exception as e:
            Clock.schedule_once(lambda dt: self._on_scan_error(str(e)), 0)

    @mainthread
    def _on_progress(self, progress: ScanProgress):
        pct = min(int(progress.scanned_bytes / max(progress.total_bytes, 1) * 100), 99)
        self._progress_bar.value = pct
        self._progress_text.text = progress.status
        self._found_label.text = f"已找到: {progress.files_found} 个文件"

    @mainthread
    def _on_scan_complete(self, result):
        self._progress_bar.value = 100
        self._progress_text.text = "��描完成!"
        self._scan_btn.disabled = False
        self._stop_btn.disabled = True
        self._status_label.text = f"扫描完成 - 共恢复 {result['stats']['total']} 个文件"

        # 更新统计
        stats = result["stats"]
        self._stat_photo.set_value(stats["photo"])
        self._stat_audio.set_value(stats["audio"])
        self._stat_video.set_value(stats["video"])

        # 填充文件列表
        self._file_list.clear_widgets()
        if not self.found_files:
            self._file_list.add_widget(Label(
                text="\n未找到可恢复的文件\n\n请确认:\n• 文件删除后未覆盖\n• 选择了正确的类别\n• 存储路径可访问",
                font_size=sp(12), color=COLORS["text_dim"],
                size_hint_y=None, height=dp(120), halign="center"
            ))
        else:
            for f in self.found_files[:200]:  # 限制显示数量
                item = FileListItem(f, self, size_hint_y=None, height=dp(56))
                self._file_list.add_widget(item)

        self._found_label.text = f"已找��: {len(self.found_files)} 个文件"
        self.show_toast(f"扫描完成！共恢复 {stats['total']} 个文件")

    @mainthread
    def _on_scan_error(self, error_msg):
        self._progress_text.text = f"错误: {error_msg}"
        self._scan_btn.disabled = False
        self._stop_btn.disabled = True
        self._status_label.text = "扫描出错"
        self.show_toast(f"扫描失败: {error_msg}")

    def _stop_scan(self, instance):
        self._stop_flag.set()
        if self.engine:
            self.engine.stop_scan()
        self._scan_btn.disabled = False
        self._stop_btn.disabled = True
        self._status_label.text = "扫描已停止"
        self._progress_text.text = "已停止"
        self.show_toast("扫描已停止")

    # ── 预览 ──────────────────────────────────────
    def show_preview(self, data, fmt):
        """显示图片预览弹窗"""
        try:
            # 保存临时文件用于预览
            tmp_path = "/sdcard/__preview_tmp__." + fmt
            with open(tmp_path, "wb") as f:
                f.write(data)

            content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
            img = KivyImage(source=tmp_path, size_hint=(1, 1))
            content.add_widget(img)

            close_btn = Button(
                text="关闭", size_hint_y=None, height=dp(40),
                background_color=COLORS["accent"], color=COLORS["white"]
            )
            content.add_widget(close_btn)

            popup = Popup(
                title="预览",
                content=content,
                size_hint=(0.9, 0.8),
                background_color=COLORS["bg"]
            )
            close_btn.bind(on_release=popup.dismiss)
            popup.open()
        except Exception as e:
            self.show_toast(f"预览失败: {e}")

    # ── 清理 ──────────────────────────────────────
    def _cleanup(self, instance):
        try:
            import shutil
            if os.path.exists(self.output_dir):
                shutil.rmtree(self.output_dir)
            self.found_files = []
            self._file_list.clear_widgets()
            self._stat_photo.set_value("0")
            self._stat_audio.set_value("0")
            self._stat_video.set_value("0")
            self._stats_card.opacity = 0
            self.show_toast("已清理所有恢复文件")
        except Exception as e:
            self.show_toast(f"清理失败: {e}")

    # ── Toast ─────────────────────────────────────
    @mainthread
    def show_toast(self, msg):
        self._toast_label.text = msg
        self._toast_label.opacity = 1
        Clock.schedule_once(lambda dt: setattr(self._toast_label, "opacity", 0), 2.5)


# ─── 桌面端调试入口 ──────────────────────────────────────
if __name__ == "__main__":
    # 如果是桌面端运行，加载引擎路径
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    RecoveryApp().run()
