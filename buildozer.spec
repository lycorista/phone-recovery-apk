[app]

# 应用基本信息
title = 手机数据恢复
package.name = phonerecovery
package.domain = com.tool
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0.0
requirements = python3,kivy==2.2.1,android
orientation = portrait
osx.python_version = 3
osx.kivy_version = 2.2.1

# 完整屏模式
fullscreen = 0

# 图标 & 启动画面
icon.filename = icon.png
presplash.filename = icon.png

# ─── Android 配置 ──────────────────────────────
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE,ACCESS_MEDIA_LOCATION

# Android API 目标
android.api = 33
android.minapi = 26

android.sdk = 34

# 架构 (arm64-v8a 覆盖绝大多数现代手机)
android.arch = arm64-v8a
# android.arch = armeabi-v7a  # 老手机用这个

# Java 兼容
android.accept_sdk_license = True

# 日志级别
android.logcat_filters = *:S python:D

# 复制模式
android.allow_backup = True

# 允许应用写入外部存储 (Android 10+)
android.add_src = 

# Gradle 依赖 (如需 Material Design)
# android.gradle_dependencies = com.google.android.material:material:1.9.0

# ─── 打包选项 ──────────────────────────────────
# 不包含这些文件减小 APK 体积
source.exclude_dirs = __pycache__,.git,.workbuddy,tests
source.exclude_patterns = *.pyc,*.pyo,.DS_Store

# 启用 P4A 的 Kivy 引导
p4a.branch = master

# Android 主题
android.presplash_color = #0A0A14
android.statusbar_color = #0A0A14

# ─── Buildozer 自身配置 ────────────────────────
[buildozer]
log_level = 2
warn_on_root = 1
