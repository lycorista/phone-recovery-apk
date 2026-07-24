#!/usr/bin/env python3
"""
手机数据恢复引擎 - PhoneRecovery
支持照片和音频文件的扫描与恢复
技术: 文件雕刻(File Carving) + 缩略图缓存扫描

兼容:
  - Termux (Android Linux 环境)
  - Linux / macOS
  - Root 和非 Root 模式
"""

import os
import re
import sys
import time
import struct
import hashlib
import threading
import queue
from pathlib import Path
from datetime import datetime
from collections import namedtuple

# ─── 文件签名定义 ───────────────────────────────────────────────

# 格式: (扩展名, 描述, 文件头签名(字节), 文件尾签名(字节, 可选))
FILE_SIGNATURES = {
    # ── 图片格式 ──
    "jpeg": {
        "ext": ".jpg",
        "desc": "JPEG 图片",
        "headers": [b"\xff\xd8\xff"],  # FF D8 FF
        "footers": [b"\xff\xd9"],       # FF D9
        "category": "photo",
    },
    "png": {
        "ext": ".png",
        "desc": "PNG 图片",
        "headers": [b"\x89PNG\r\n\x1a\n"],
        "footers": [b"IEND\xae\x42\x60\x82"],
        "category": "photo",
    },
    "gif": {
        "ext": ".gif",
        "desc": "GIF 图片",
        "headers": [b"GIF89a", b"GIF87a"],
        "footers": [b"\x00\x3b"],  # GIF 结尾较简单
        "category": "photo",
    },
    "bmp": {
        "ext": ".bmp",
        "desc": "BMP 图片",
        "headers": [b"BM"],
        "footers": None,  # BMP 无固定尾部, 用文件头中的大小字段判断
        "category": "photo",
    },
    "webp": {
        "ext": ".webp",
        "desc": "WebP 图片",
        "headers": [b"RIFF"],
        "footers": None,
        "category": "photo",
    },
    "heic": {
        "ext": ".heic",
        "desc": "HEIC 图片",
        "headers": [b"ftypheic", b"ftypheix", b"ftyphevc", b"ftypheim"],
        "footers": None,
        "category": "photo",
    },

    # ── 音频格式 ──
    "mp3": {
        "ext": ".mp3",
        "desc": "MP3 音频",
        "headers": [b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xfa",
                    b"ID3"],
        "footers": None,
        "category": "audio",
    },
    "wav": {
        "ext": ".wav",
        "desc": "WAV 音频",
        "headers": [b"RIFF"],
        "footers": None,
        "category": "audio",
    },
    "aac": {
        "ext": ".aac",
        "desc": "AAC 音频",
        "headers": [b"\xff\xf1", b"\xff\xf9"],
        "footers": None,
        "category": "audio",
    },
    "flac": {
        "ext": ".flac",
        "desc": "FLAC 无损音频",
        "headers": [b"fLaC"],
        "footers": None,
        "category": "audio",
    },
    "ogg": {
        "ext": ".ogg",
        "desc": "OGG 音频",
        "headers": [b"OggS"],
        "footers": None,
        "category": "audio",
    },
    "wma": {
        "ext": ".wma",
        "desc": "WMA 音频",
        "headers": [b"\x30\x26\xb2\x75\x8e\x66\xcf\x11"],
        "footers": None,
        "category": "audio",
    },
    "m4a": {
        "ext": ".m4a",
        "desc": "M4A 音频",
        "headers": [b"ftypM4A", b"ftypmp42"],
        "footers": None,
        "category": "audio",
    },
    "amr": {
        "ext": ".amr",
        "desc": "AMR 音频",
        "headers": [b"#!AMR"],
        "footers": None,
        "category": "audio",
    },

    # ── 视频格式 (有时含音频轨) ──
    "mp4": {
        "ext": ".mp4",
        "desc": "MP4 视频",
        "headers": [b"ftypmp4", b"ftypavc", b"ftypisom"],
        "footers": None,
        "category": "video",
    },
    "3gp": {
        "ext": ".3gp",
        "desc": "3GP 视频",
        "headers": [b"ftyp3gp"],
        "footers": None,
        "category": "video",
    },
}

# 最大文件大小限制 (防止恢复异常大文件)
MAX_FILE_SIZE = {
    "photo": 50 * 1024 * 1024,   # 50MB
    "audio": 100 * 1024 * 1024,  # 100MB
    "video": 200 * 1024 * 1024,  # 200MB
}

# 最小文件大小限制
MIN_FILE_SIZE = {
    "photo": 1024,       # 1KB
    "audio": 2048,       # 2KB
    "video": 10240,      # 10KB
}

# Android 缩略图缓存路径
ANDROID_THUMBNAIL_PATHS = [
    "DCIM/.thumbnails",
    "Pictures/.thumbnails",
    "Android/data/com.google.android.apps.photos/files",
    "Android/data/com.android.gallery3d",
]

# Android 常用扫描路径
ANDROID_SCAN_PATHS = [
    "DCIM",
    "Pictures",
    "Download",
    "Music",
    "Audio",
    "Recordings",
    "Movies",
    "Android/data",
    "tencent/MicroMsg",
    "Media",
]

# ─── 数据结构 ───────────────────────────────────────────────────

RecoveredFile = namedtuple("RecoveredFile", [
    "id", "path", "name", "size", "format", "category",
    "recover_time", "source", "md5", "preview_possible"
])

ScanProgress = namedtuple("ScanProgress", [
    "total_bytes", "scanned_bytes", "files_found", "status"
])

# ─── 核心恢复引擎 ──────────────────────────────────────────────

class RecoveryEngine:
    """手机数据恢复引擎"""

    def __init__(self, output_dir=None, progress_callback=None):
        """
        Args:
            output_dir: 恢复文件输出目录
            progress_callback: 进度回调函数 callback(ScanProgress)
        """
        self.output_dir = Path(output_dir) if output_dir else Path.home() / "RecoveredFiles"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.progress_callback = progress_callback
        self.found_files = []
        self._scan_lock = threading.Lock()
        self._stop_flag = threading.Event()
        self._file_counter = 0

    # ── 文件雕刻 (File Carving) ──────────────────────────────

    def carve_from_data(self, data: bytes, source_name: str = "unknown",
                        base_offset: int = 0) -> list:
        """
        从二进制数据中雕刻出文件

        Args:
            data: 原始二进制数据
            source_name: 数据来源名称
            base_offset: 起始偏移量

        Returns:
            恢复的文件路径列表
        """
        recovered = []
        data_len = len(data)

        for fmt_name, sig in FILE_SIGNATURES.items():
            if self._stop_flag.is_set():
                break

            for header in sig["headers"]:
                search_start = 0
                while search_start < data_len:
                    if self._stop_flag.is_set():
                        break

                    # 搜索文件头
                    pos = data.find(header, search_start)
                    if pos == -1:
                        break

                    # 确定文件数据范围
                    footer = sig["footers"][0] if sig["footers"] else None
                    max_size = MAX_FILE_SIZE.get(sig["category"], 50 * 1024 * 1024)
                    min_size = MIN_FILE_SIZE.get(sig["category"], 1024)

                    if footer:
                        # 有尾部签名: 搜索匹配的尾部
                        footer_search_start = pos + len(header)
                        footer_pos = data.find(footer, footer_search_start,
                                               footer_search_start + max_size)
                        if footer_pos != -1:
                            file_data = data[pos:footer_pos + len(footer)]
                            search_start = footer_pos + len(footer)
                        else:
                            # 未找到尾部，尝试用最大大小截断
                            end = min(pos + max_size, data_len)
                            file_data = data[pos:end]
                            search_start = end
                    else:
                        # 无尾部签名: 保守策略
                        # 对于 BMP: 从文件头读取大小
                        if fmt_name == "bmp" and pos + 6 <= data_len:
                            try:
                                bmp_size = struct.unpack_from("<I", data, pos + 2)[0]
                                end = min(pos + bmp_size, data_len, pos + max_size)
                            except Exception:
                                end = min(pos + max_size, data_len)
                        else:
                            # 搜索下一个文件头作为边界
                            next_pos = data_len
                            for other_fmt, other_sig in FILE_SIGNATURES.items():
                                if other_fmt == fmt_name:
                                    continue
                                for other_hdr in other_sig["headers"]:
                                    p = data.find(other_hdr, pos + len(header))
                                    if p != -1 and p < next_pos:
                                        next_pos = p
                            end = min(next_pos, pos + max_size)

                        file_data = data[pos:end]
                        search_start = end

                    # 验证大小
                    if min_size <= len(file_data) <= max_size:
                        # 额外验证
                        if self._validate_file_data(fmt_name, file_data):
                            recovered_path = self._save_recovered_file(
                                file_data, fmt_name, sig["ext"],
                                sig["category"], source_name,
                                base_offset + pos
                            )
                            if recovered_path:
                                recovered.append(recovered_path)
                    else:
                        search_start = pos + len(header)

        return recovered

    def _validate_file_data(self, fmt_name: str, data: bytes) -> bool:
        """验证恢复的文件数据是否有效"""
        if len(data) < MIN_FILE_SIZE.get(FILE_SIGNATURES[fmt_name]["category"], 1024):
            return False

        # JPEG 额外验证
        if fmt_name == "jpeg":
            # 检查是否以有效 JPEG 标记开头
            if data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9":
                # 检查是否有 SOS 标记
                if b"\xff\xda" in data:
                    return True
                return False
            return True  # 即使没有标准结尾也尝试恢复

        # PNG 额外验证
        if fmt_name == "png":
            if data[:8] == b"\x89PNG\r\n\x1a\n" and b"IHDR" in data[:100]:
                return True
            return False

        # MP3 额外验证
        if fmt_name == "mp3":
            # ID3v2 标签开头也有效
            if data[:3] == b"ID3":
                return True
            # 检查帧同步
            if data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
                return True

        return True

    def _save_recovered_file(self, data: bytes, fmt_name: str, ext: str,
                             category: str, source: str, offset: int) -> str:
        """保存恢复的文件"""
        with self._scan_lock:
            self._file_counter += 1
            file_id = self._file_counter

        # 生成唯一文件名
        file_hash = hashlib.md5(data[:1024] + str(offset).encode()).hexdigest()[:12]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recovered_{category}_{fmt_name}_{timestamp}_{file_hash}{ext}"

        # 按类别分目录
        category_dir = self.output_dir / category
        category_dir.mkdir(exist_ok=True)

        filepath = category_dir / filename

        try:
            filepath.write_bytes(data)
        except OSError as e:
            print(f"[ERROR] 保存文件失败: {filepath} - {e}")
            return ""

        # 判断是否可预览
        preview_possible = fmt_name in ("jpeg", "png", "gif", "bmp", "webp")

        rf = RecoveredFile(
            id=file_id,
            path=str(filepath),
            name=filename,
            size=len(data),
            format=fmt_name,
            category=category,
            recover_time=timestamp,
            source=source,
            md5=file_hash,
            preview_possible=preview_possible,
        )

        with self._scan_lock:
            self.found_files.append(rf)

        return str(filepath)

    # ── 文件级扫描 (非 Root 模式) ────────────────────────────

    def scan_file(self, filepath: Path) -> list:
        """扫描单个文件，尝试从中恢复嵌入的图片/音频"""
        recovered = []
        try:
            size = filepath.stat().st_size
            # 跳过过大文件
            if size > 512 * 1024 * 1024:  # 512MB
                return recovered

            # 以块方式读取，避免内存溢出
            block_size = 10 * 1024 * 1024  # 10MB 块
            with open(filepath, "rb") as f:
                offset = 0
                while True:
                    block = f.read(block_size)
                    if not block:
                        break
                    result = self.carve_from_data(
                        block,
                        source_name=f"file:{filepath.name}",
                        base_offset=offset
                    )
                    recovered.extend(result)
                    offset += len(block)

                    if self._stop_flag.is_set():
                        break

        except (PermissionError, OSError) as e:
            pass  # 无权限读取的文件跳过

        return recovered

    def scan_directory(self, directory: Path, recursive: bool = True) -> list:
        """扫描目录下所有文件"""
        recovered = []
        files_to_scan = []

        # 收集文件列表
        try:
            if recursive:
                for root, dirs, files in os.walk(directory):
                    # 跳过隐藏目录和系统目录
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for f in files:
                        files_to_scan.append(Path(root) / f)
            else:
                for f in directory.iterdir():
                    if f.is_file() and not f.name.startswith("."):
                        files_to_scan.append(f)
        except (PermissionError, OSError):
            pass

        total = len(files_to_scan)
        for i, filepath in enumerate(files_to_scan):
            if self._stop_flag.is_set():
                break

            if self.progress_callback:
                self.progress_callback(ScanProgress(
                    total_bytes=total,
                    scanned_bytes=i + 1,
                    files_found=len(self.found_files),
                    status=f"扫描文件中... ({i+1}/{total})"
                ))

            result = self.scan_file(filepath)
            recovered.extend(result)

        return recovered

    # ── 原始数据扫描 (Root 模式) ──────────────────────────────

    def scan_raw_device(self, device_path: str, block_size: int = 10 * 1024 * 1024) -> list:
        """
        扫描原始块设备 (需要 root 权限)
        典型设备路径: /dev/block/mmcblk0, /dev/block/sda 等
        """
        recovered = []
        try:
            total_size = os.path.getsize(device_path)
        except OSError:
            total_size = 0

        scanned = 0
        try:
            with open(device_path, "rb") as f:
                while not self._stop_flag.is_set():
                    block = f.read(block_size)
                    if not block:
                        break

                    result = self.carve_from_data(
                        block,
                        source_name=f"device:{Path(device_path).name}",
                        base_offset=scanned
                    )
                    recovered.extend(result)
                    scanned += len(block)

                    if self.progress_callback:
                        self.progress_callback(ScanProgress(
                            total_bytes=total_size,
                            scanned_bytes=scanned,
                            files_found=len(self.found_files),
                            status=f"扫描设备... {self._format_size(scanned)}"
                        ))

        except (PermissionError, OSError) as e:
            print(f"[ERROR] 无法访问设备 {device_path}: {e}")

        return recovered

    # ── 缩略图缓存扫描 ────────────────────────────────────────

    def scan_thumbnails(self, base_path: str) -> list:
        """扫描 Android 缩略图缓存目录"""
        recovered = []
        base = Path(base_path)

        for rel_path in ANDROID_THUMBNAIL_PATHS:
            thumb_dir = base / rel_path
            if thumb_dir.exists():
                for f in thumb_dir.glob("*"):
                    if f.is_file():
                        result = self.scan_file(f)
                        recovered.extend(result)

        # 扫描 .thumbdata 文件
        for thumbdata in base.rglob(".thumbdata*"):
            if thumbdata.is_file():
                result = self.carve_from_data(
                    thumbdata.read_bytes()[:50*1024*1024],
                    source_name=f"thumbnail:{thumbdata.name}"
                )
                recovered.extend(result)

        return recovered

    # ── 全盘扫描 (综合模式) ──────────────────────────────────

    def full_scan(self, base_path: str = "/sdcard",
                  scan_raw: bool = False,
                  device_path: str = None,
                  scan_thumbnails: bool = True,
                  categories: list = None) -> dict:
        """
        执行全面扫描

        Args:
            base_path: 存储根路径 (Termux 中通常为 /sdcard 或 ~/storage/shared)
            scan_raw: 是否扫描原始块设备 (需要 root)
            device_path: 块设备路径
            scan_thumbnails: 是否扫描缩略图缓存
            categories: 限定恢复类别 ["photo", "audio", "video"]

        Returns:
            { "recovered_files": [...], "stats": {...} }
        """
        self._stop_flag.clear()
        self.found_files = []
        self._file_counter = 0

        all_recovered = []

        base = Path(base_path)

        # 1. 扫描缩略图缓存
        if scan_thumbnails:
            if self.progress_callback:
                self.progress_callback(ScanProgress(0, 0, 0, "扫描缩略图缓存..."))
            thumbs = self.scan_thumbnails(str(base))
            all_recovered.extend(thumbs)

        # 2. 扫描常用目录
        for rel_path in ANDROID_SCAN_PATHS:
            if self._stop_flag.is_set():
                break
            target = base / rel_path
            if target.exists():
                result = self.scan_directory(target, recursive=True)
                all_recovered.extend(result)

        # 3. Root 模式: 扫描原始设备
        if scan_raw and device_path:
            if self.progress_callback:
                self.progress_callback(ScanProgress(0, 0, 0, "扫描原始设备 (需要 root)..."))
            result = self.scan_raw_device(device_path)
            all_recovered.extend(result)

        # 统计
        stats = {
            "total": len(self.found_files),
            "photo": sum(1 for f in self.found_files if f.category == "photo"),
            "audio": sum(1 for f in self.found_files if f.category == "audio"),
            "video": sum(1 for f in self.found_files if f.category == "video"),
            "total_size": sum(f.size for f in self.found_files),
            "output_dir": str(self.output_dir),
        }

        return {
            "recovered_files": self.found_files,
            "stats": stats,
        }

    def stop_scan(self):
        """停止扫描"""
        self._stop_flag.set()

    # ── 工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    def get_file_preview_data(self, file_id: int) -> bytes:
        """获取文件预览数据 (仅图片)"""
        for f in self.found_files:
            if f.id == file_id:
                if f.preview_possible:
                    try:
                        return Path(f.path).read_bytes()
                    except OSError:
                        pass
        return None

    def check_environment(self) -> dict:
        """检查运行环境"""
        info = {
            "is_android": False,
            "is_termux": False,
            "is_root": False,
            "storage_paths": [],
            "available_space": "",
        }

        # 检测 Android / Termux
        if os.path.exists("/system/build.prop"):
            info["is_android"] = True
        if "ANDROID_ROOT" in os.environ or "PREFIX" in os.environ:
            info["is_termux"] = True

        # 检测 root
        try:
            result = os.system("which su > /dev/null 2>&1")
            info["is_root"] = os.path.exists("/system/bin/su") or os.path.exists("/system/xbin/su")
        except Exception:
            pass

        # 检测可访问的存储路径
        possible_paths = [
            "/sdcard",
            "/storage/emulated/0",
            str(Path.home() / "storage/shared"),
            str(Path.home() / "storage/external-1"),
        ]
        for p in possible_paths:
            if os.path.exists(p):
                info["storage_paths"].append(p)

        # 可用空间
        try:
            import shutil
            usage = shutil.disk_usage(self.output_dir)
            info["available_space"] = self._format_size(usage.free)
        except Exception:
            pass

        return info

    def list_found_files(self, category: str = None) -> list:
        """列出已找到的文件"""
        files = self.found_files
        if category:
            files = [f for f in files if f.category == category]
        return files


# ─── 单文件恢复工具函数 ─────────────────────────────────────────

def quick_recover_file(filepath: str, output_dir: str = None) -> list:
    """快速恢复单个文件中的嵌入内容"""
    engine = RecoveryEngine(output_dir=output_dir)
    return engine.scan_file(Path(filepath))


def quick_recover_directory(dirpath: str, output_dir: str = None) -> list:
    """快速恢复目录中的文件"""
    engine = RecoveryEngine(output_dir=output_dir)
    return engine.scan_directory(Path(dirpath))


# ─── 命令行入口 ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="手机数据恢复工具 - 恢复已删除的照片和音频文件"
    )
    parser.add_argument("--path", "-p", default="/sdcard",
                        help="扫描路径 (默认: /sdcard)")
    parser.add_argument("--output", "-o", default=None,
                        help="恢复文件输出目录")
    parser.add_argument("--device", "-d", default=None,
                        help="块设备路径 (Root 模式)")
    parser.add_argument("--root", action="store_true",
                        help="启用 Root 模式扫描原始设备")
    parser.add_argument("--no-thumbnails", action="store_true",
                        help="跳过缩略图缓存扫描")
    parser.add_argument("--category", "-c", choices=["photo", "audio", "video"],
                        default=None, help="限定恢复类别")
    parser.add_argument("--check", action="store_true",
                        help="仅检查运行环境")

    args = parser.parse_args()

    engine = RecoveryEngine(output_dir=args.output)

    if args.check:
        env = engine.check_environment()
        print("=" * 50)
        print("  手机数据恢复工具 - 环境检查")
        print("=" * 50)
        print(f"  Android 系统:  {'是' if env['is_android'] else '否'}")
        print(f"  Termux 环境:   {'是' if env['is_termux'] else '否'}")
        print(f"  Root 权限:     {'是' if env['is_root'] else '否'}")
        print(f"  可用空间:      {env['available_space']}")
        print(f"  可访问存储:")
        for p in env["storage_paths"]:
            print(f"    - {p}")
        print("=" * 50)
        sys.exit(0)

    def progress(p):
        pct = (p.scanned_bytes / max(p.total_bytes, 1)) * 100
        bar_len = 30
        filled = int(bar_len * min(pct / 100, 1))
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"\r[{bar}] {pct:.1f}% | 找到 {p.files_found} 个文件 | {p.status}", end="")

    engine.progress_callback = progress

    print("\n开始扫描...")
    print(f"  路径: {args.path}")
    print(f"  输出: {engine.output_dir}")
    if args.root:
        print(f"  模式: Root (设备: {args.device})")

    result = engine.full_scan(
        base_path=args.path,
        scan_raw=args.root,
        device_path=args.device,
        scan_thumbnails=not args.no_thumbnails,
    )

    print("\n\n扫描完成!")
    stats = result["stats"]
    print(f"  共恢复 {stats['total']} 个文件")
    print(f"    图片: {stats['photo']}")
    print(f"    音频: {stats['audio']}")
    print(f"    视频: {stats['video']}")
    print(f"  总大小: {engine._format_size(stats['total_size'])}")
    print(f"  保存目录: {stats['output_dir']}")
