import sys
import os
import json
import math
import time
import random
import shutil
import requests
import subprocess
from ai_sub import (
    generate_subtitles,
    parse_srt_file_to_segments,
    separate_audio_To_beat_or_vocal,
)

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

if os.name == 'nt':
    os.add_dll_directory(os.path.dirname(os.path.abspath(__file__)))
if getattr(sys, 'frozen', False):
    GLOBAL_BASE_DIR = os.path.dirname(sys.executable)
else:
    GLOBAL_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BIN_DIR = os.path.join(GLOBAL_BASE_DIR, 'bin')
MUSIC_DIR = os.path.join(GLOBAL_BASE_DIR, 'music')
os.makedirs(MUSIC_DIR, exist_ok=True)
PLAYLIST_JSON_PATH = os.path.join(MUSIC_DIR, 'playlist.json')

os.environ["PATH"] += os.pathsep + BIN_DIR

import mpv
from PyQt6.QtWidgets import QApplication, QMessageBox, QListWidgetItem, QDialog, QFileDialog
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from gui import ModernUI, AspectRatioDialog
import yt_dlp
from yt_dlp.utils import download_range_func

AUDIO_EXTENSIONS = ('.mp3', '.m4a', '.wav', '.flac', '.ogg', '.aac', '.opus')

PLAYLIST_LYRIC_ADVANCE_SEC = 0.15


def time_to_seconds(time_str):
    if not time_str or not time_str.strip():
        return 0
    parts = [int(p) for p in time_str.strip().split(':')]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return int(time_str)


def create_concat_file(files, list_path):
    with open(list_path, 'w', encoding='utf-8') as f:
        for p in files:
            safe_path = p.replace('\\', '/')
            f.write(f"file '{safe_path}'\n")


def get_audio_mode_from_quality(quality_str: str) -> str:
    q = (quality_str or "").lower()
    if "beat (tách lời" in q or "chỉ có beat" in q:
        return "beat_only"
    if "giọng hát (chỉ lời" in q or "chỉ là giọng hát" in q:
        return "vocal_only"
    if "âm thanh" in q:
        return "full_audio"
    return None


def get_direct_sub_url_if_eligible(tasks: list) -> str:
    if len(tasks) != 1:
        return None
    t = tasks[0]
    start_sec = time_to_seconds(t.get('start', ''))
    end_sec = time_to_seconds(t.get('end', ''))
    if start_sec > 0 or end_sec > 0:
        return None
    url = t.get('url', '').strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def process_and_move_audio_by_mode(input_path: str, ffmpeg_dir: str, audio_mode: str = "full_audio",
                                   progress_callback=None) -> tuple:
    if not input_path or not os.path.exists(input_path):
        return input_path, input_path

    os.makedirs(MUSIC_DIR, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    if base_name.endswith("_part0"):
        base_name = base_name[:-6]

    if audio_mode == "beat_only":
        suffix = "_Beat"
    elif audio_mode == "vocal_only":
        suffix = "_Vocal"
    else:
        suffix = ""

    target_mp3 = os.path.join(MUSIC_DIR, f"{base_name}{suffix}.mp3")
    ffmpeg_exe = os.path.join(ffmpeg_dir, 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    creationflags = 0x08000000 if os.name == 'nt' else 0

    if audio_mode == "beat_only":
        separate_audio_To_beat_or_vocal(
            input_path=input_path,
            mode="beat",
            output_path=target_mp3,
            ffmpeg_dir=ffmpeg_dir,
            progress_callback=progress_callback
        )
        return target_mp3, input_path

    elif audio_mode == "vocal_only":
        separate_audio_To_beat_or_vocal(
            input_path=input_path,
            mode="vocal",
            output_path=target_mp3,
            ffmpeg_dir=ffmpeg_dir,
            progress_callback=progress_callback
        )
        if os.path.exists(target_mp3) and os.path.abspath(input_path) != os.path.abspath(target_mp3):
            try:
                os.remove(input_path)
            except Exception:
                pass
        return target_mp3, target_mp3

    else:
        if os.path.abspath(input_path) == os.path.abspath(target_mp3):
            return target_mp3, target_mp3

        if os.path.exists(ffmpeg_exe):
            cmd = [
                ffmpeg_exe, '-y',
                '-i', input_path,
                '-vn',
                '-acodec', 'libmp3lame',
                '-q:a', '2',
                target_mp3
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)
            if res.returncode == 0 and os.path.exists(target_mp3):
                try:
                    os.remove(input_path)
                except Exception:
                    pass
                return target_mp3, target_mp3

        fallback_dest = os.path.join(MUSIC_DIR, os.path.basename(input_path))
        try:
            if os.path.exists(fallback_dest):
                os.remove(fallback_dest)
            os.rename(input_path, fallback_dest)
            return fallback_dest, fallback_dest
        except Exception:
            return input_path, input_path


def find_matching_srt_for_track(track_path: str) -> str:
    if not track_path:
        return None

    track_dir = os.path.dirname(os.path.abspath(track_path))
    base_name = os.path.splitext(os.path.basename(track_path))[0]

    base_variants = [base_name]
    for suf in ("_part0", "_Beat", "_Vocal", "_beat", "_vocal"):
        if base_name.endswith(suf):
            stripped = base_name[:-len(suf)]
            if stripped and stripped not in base_variants:
                base_variants.append(stripped)
                base_variants.append(stripped + "_Vocal")
                base_variants.append(stripped + "_part0")

    for v in list(base_variants):
        if f"{v}_Vocal" not in base_variants:
            base_variants.append(f"{v}_Vocal")
        if f"{v}_Beat" not in base_variants:
            base_variants.append(f"{v}_Beat")

    search_dirs = [track_dir, MUSIC_DIR, GLOBAL_BASE_DIR, os.getcwd()]
    seen_dirs = set()

    for d in search_dirs:
        if not d or not os.path.isdir(d):
            continue
        abs_d = os.path.abspath(d)
        if abs_d in seen_dirs:
            continue
        seen_dirs.add(abs_d)

        for variant in base_variants:
            candidate = os.path.join(abs_d, variant + ".srt")
            if os.path.exists(candidate) and os.path.getsize(candidate) > 5:
                return candidate

        try:
            lower_variants = {v.lower() + ".srt" for v in base_variants}
            for fname in os.listdir(abs_d):
                if fname.lower() in lower_variants:
                    candidate = os.path.join(abs_d, fname)
                    if os.path.getsize(candidate) > 5:
                        return candidate
        except Exception:
            pass

    return None


class PreviewLoadThread(QThread):
    success_signal = pyqtSignal(str, str, list)
    error_signal = pyqtSignal(str)

    def __init__(self, url: str, platform_name: str):
        super().__init__()
        self.url = url
        self.platform_name = platform_name

    def run(self):
        try:
            if self.platform_name == "TikTok" or "tiktok.com" in self.url.lower():
                try:
                    api_url = "https://www.tikwm.com/api/"
                    resp = requests.post(api_url, data={"url": self.url, "hd": 1}, timeout=12).json()
                    if resp.get("code") == 0:
                        data = resp.get("data", {})
                        play_url = data.get("play") or data.get("hdplay")
                        if play_url:
                            self.success_signal.emit(play_url, "", [])
                            return
                except Exception:
                    pass

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            }
            lower_url = self.url.lower()
            if "facebook.com" in lower_url or "fb.watch" in lower_url or self.platform_name == "Facebook":
                headers['Referer'] = 'https://www.facebook.com/'
            elif "instagram.com" in lower_url or self.platform_name == "Instagram":
                headers['Referer'] = 'https://www.instagram.com/'

            ydl_opts = {
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'http_headers': headers,
                'format': (
                    'best[ext=mp4][vcodec^=avc][acodec!=none]/'
                    'best[ext=mp4][vcodec!=none][acodec!=none]/'
                    'best[vcodec!=none][acodec!=none]/'
                    'bestvideo[vcodec^=avc][height<=1080]+bestaudio/'
                    'bestvideo[ext=mp4]+bestaudio/'
                    'bestvideo+bestaudio/best'
                ),
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                if 'entries' in info and info['entries']:
                    info = info['entries'][0]

                video_url = ""
                audio_url = ""
                final_headers = dict(headers)
                if info.get('http_headers'):
                    final_headers.update(info['http_headers'])

                formats = info.get('formats') or []

                progressive_avc = [
                    f for f in formats
                    if f.get('url')
                    and f.get('vcodec') not in (None, 'none')
                    and f.get('acodec') not in (None, 'none')
                    and str(f.get('vcodec', '')).startswith(('avc', 'h264'))
                ]
                progressive_any = [
                    f for f in formats
                    if f.get('url')
                    and f.get('vcodec') not in (None, 'none')
                    and f.get('acodec') not in (None, 'none')
                ]

                if progressive_avc:
                    chosen = progressive_avc[-1]
                    video_url = chosen['url']
                    if chosen.get('http_headers'):
                        final_headers.update(chosen['http_headers'])
                elif progressive_any:
                    chosen = progressive_any[-1]
                    video_url = chosen['url']
                    if chosen.get('http_headers'):
                        final_headers.update(chosen['http_headers'])
                elif info.get('requested_formats') and len(info['requested_formats']) >= 2:
                    req_v = info['requested_formats'][0]
                    req_a = info['requested_formats'][1]
                    video_url = req_v.get('url', '')
                    audio_url = req_a.get('url', '')
                    if req_v.get('http_headers'):
                        final_headers.update(req_v['http_headers'])
                elif info.get('url'):
                    video_url = info['url']

                if not progressive_avc and not progressive_any and formats:
                    video_only_avc = [
                        f for f in formats
                        if f.get('url')
                        and f.get('vcodec') not in (None, 'none')
                        and str(f.get('vcodec', '')).startswith(('avc', 'h264', 'vp9', 'vp09', 'hev', 'hvc'))
                    ]
                    audio_only = [
                        f for f in formats
                        if f.get('url')
                        and f.get('acodec') not in (None, 'none')
                        and f.get('vcodec') in (None, 'none')
                    ]
                    if video_only_avc:
                        video_url = video_only_avc[-1]['url']
                        if audio_only and not audio_url:
                            audio_url = audio_only[-1]['url']

                if not video_url:
                    raise Exception("Không tìm thấy luồng phát hợp lệ từ đường dẫn này.")

                header_list = [f"{k}: {v}" for k, v in final_headers.items() if k and v]
                self.success_signal.emit(video_url, audio_url, header_list)

        except Exception as e:
            self.error_signal.emit(str(e))


class YoutubeDownloadThread(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str, list)

    def __init__(self, tasks, quality, generate_subs, sub_lang="auto", sub_model="standard", target_w=1920, target_h=1080):
        super().__init__()
        self.tasks = tasks
        self.quality = quality
        self.generate_subs = generate_subs
        self.sub_lang = sub_lang
        self.sub_model = sub_model
        self.target_w = target_w
        self.target_h = target_h

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            p_str = d.get('_percent_str', '0%').strip()
            try:
                val = int(float(p_str.replace('%', '').strip()))
            except Exception:
                val = 0
            scaled = int(val * 0.5) if self.generate_subs else val
            self.progress_signal.emit(scaled, f"Đang tải dữ liệu: {p_str}")

    def run(self):
        raw_temp_for_srt = None
        try:
            ffmpeg_dir = BIN_DIR
            if not os.path.exists(os.path.join(ffmpeg_dir, 'ffmpeg.exe')):
                self.finished_signal.emit(False, "LỖI: Không tìm thấy thư mục FFmpeg!", [])
                return

            audio_mode = get_audio_mode_from_quality(self.quality)
            is_audio_only = (audio_mode is not None)

            if self.quality == "2160p (4K)":
                vid_format = 'bestvideo[height<=2160]+bestaudio/best'
            elif self.quality == "1440p (2K)":
                vid_format = 'bestvideo[height<=1440]+bestaudio/best'
            elif self.quality == "1080p (FHD)":
                vid_format = 'bestvideo[ext=mp4][height<=1080][vcodec^=avc]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            elif self.quality == "720p (HD)":
                vid_format = 'bestvideo[ext=mp4][height<=720][vcodec^=avc]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            elif self.quality == "480p (SD)":
                vid_format = 'bestvideo[ext=mp4][height<=480][vcodec^=avc]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            else:
                vid_format = 'bestaudio[ext=m4a]/bestaudio/best'

            downloaded_files = []
            saved_audio_files = []

            for idx, task in enumerate(self.tasks):
                url = task['url']
                start_sec = time_to_seconds(task['start'])
                end_sec = time_to_seconds(task['end'])

                self.progress_signal.emit(0, f"Đang xử lý phần {idx + 1}/{len(self.tasks)}...")
                out_dir = MUSIC_DIR if is_audio_only else os.getcwd()
                download_path = os.path.join(out_dir, f'%(title).70s_%(id)s_part{idx}.%(ext)s')

                ydl_opts = {
                    'format': vid_format,
                    'noplaylist': True,
                    'outtmpl': download_path,
                    'progress_hooks': [self.progress_hook],
                    'ffmpeg_location': ffmpeg_dir,
                    'windowsfilenames': True,
                    'merge_output_format': None if is_audio_only else 'mp4',
                    'extractor_args': {'youtube': ['player_client=android,ios', 'player_skip=web,mweb']}
                }

                is_cutting = end_sec > 0
                if is_cutting:
                    ydl_opts['download_ranges'] = download_range_func(None, [(start_sec, end_sec)])
                    ydl_opts['force_keyframes_at_cuts'] = True

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    actual_file = info.get('requested_downloads', [{}])[0].get('filepath')
                    if not actual_file:
                        actual_file = ydl.prepare_filename(info)
                        if not is_audio_only and not is_cutting:
                            actual_file = os.path.splitext(actual_file)[0] + ".mp4"

                    if is_audio_only:
                        def _sep_cb(pct, msg):
                            self.progress_signal.emit(pct, msg)
                        processed_mp3, srt_audio_src = process_and_move_audio_by_mode(
                            actual_file, ffmpeg_dir, audio_mode=audio_mode, progress_callback=_sep_cb
                        )
                        if srt_audio_src != processed_mp3:
                            raw_temp_for_srt = srt_audio_src
                        actual_file = processed_mp3
                        saved_audio_files.append(actual_file)

                    downloaded_files.append(actual_file)

            final_file = downloaded_files[0] if downloaded_files else ""

            if len(downloaded_files) > 1 and not is_audio_only:
                self.progress_signal.emit(50, "Đang tiến hành gộp các video...")
                ext = os.path.splitext(downloaded_files[0])[1]
                merged_file = os.path.join(os.getcwd(), f"Merged_YT_{int(time.time())}{ext}")

                fps = 60
                creationflags = 0x08000000 if os.name == 'nt' else 0
                cmd = [os.path.join(ffmpeg_dir, 'ffmpeg.exe'), '-y']

                for f in downloaded_files:
                    cmd.extend(['-i', f])

                filter_str = ""
                concat_inputs = ""
                for i in range(len(downloaded_files)):
                    filter_str += f"[{i}:v]scale={self.target_w}:{self.target_h}:force_original_aspect_ratio=decrease,pad={self.target_w}:{self.target_h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,setsar=1[v{i}];"
                    filter_str += f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a{i}];"
                    concat_inputs += f"[v{i}][a{i}]"

                filter_str += f"{concat_inputs}concat=n={len(downloaded_files)}:v=1:a=1[outv][outa]"
                cmd.extend([
                    '-filter_complex', filter_str,
                    '-map', '[outv]',
                    '-map', '[outa]',
                    '-c:v', 'libx264',
                    '-preset', 'fast',
                    '-c:a', 'aac',
                    merged_file
                ])
                process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         creationflags=creationflags)
                if process.returncode != 0:
                    error_msg = process.stderr.decode('utf-8', errors='ignore')
                    raise Exception(f"Lỗi FFmpeg khi gộp:\n{error_msg}")

                final_file = merged_file
                try:
                    for f in downloaded_files:
                        if os.path.exists(f):
                            os.remove(f)
                except Exception:
                    pass

            if self.generate_subs and final_file:
                def sub_cb(pct, msg):
                    self.progress_signal.emit(pct, msg)
                direct_url = get_direct_sub_url_if_eligible(self.tasks)
                pre_vocal = final_file if audio_mode == "vocal_only" else None
                source_for_sub = raw_temp_for_srt if (audio_mode == "beat_only" and raw_temp_for_srt and os.path.exists(raw_temp_for_srt)) else final_file

                srt_out = generate_subtitles(
                    source_for_sub,
                    progress_callback=sub_cb,
                    ffmpeg_dir=BIN_DIR,
                    language=self.sub_lang,
                    model_size=self.sub_model,
                    source_url=direct_url,
                    pre_isolated_vocal_path=pre_vocal
                )
                if audio_mode == "beat_only" and srt_out and os.path.exists(srt_out):
                    expected_beat_srt = os.path.splitext(final_file)[0] + ".srt"
                    if os.path.abspath(srt_out) != os.path.abspath(expected_beat_srt):
                        try:
                            shutil.move(srt_out, expected_beat_srt)
                            srt_out = expected_beat_srt
                        except Exception:
                            pass

                if srt_out and os.path.exists(srt_out) and not is_audio_only:
                    try:
                        shutil.copy2(srt_out, os.path.join(MUSIC_DIR, os.path.basename(srt_out)))
                    except Exception:
                        pass

            self.progress_signal.emit(100, "Hoàn tất tải và xử lý!")
            save_loc = MUSIC_DIR if is_audio_only else os.getcwd()
            self.finished_signal.emit(True, f"Thành công! Đã lưu tại:\n{save_loc}", saved_audio_files)
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi hệ thống:\n{str(e)}", [])
        finally:
            if raw_temp_for_srt and os.path.exists(raw_temp_for_srt):
                try:
                    os.remove(raw_temp_for_srt)
                except Exception:
                    pass


class FacebookDownloadThread(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str, list)

    def __init__(self, tasks, quality, generate_subs, sub_lang="auto", sub_model="standard", target_w=1920, target_h=1080):
        super().__init__()
        self.tasks = tasks
        self.quality = quality
        self.generate_subs = generate_subs
        self.sub_lang = sub_lang
        self.sub_model = sub_model
        self.target_w = target_w
        self.target_h = target_h

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            p_str = d.get('_percent_str', '0%').strip()
            try:
                val = int(float(p_str.replace('%', '').strip()))
            except Exception:
                val = 0
            scaled = int(val * 0.5) if self.generate_subs else val
            self.progress_signal.emit(scaled, f"Đang tải dữ liệu: {p_str}")

    def run(self):
        raw_temp_for_srt = None
        try:
            ffmpeg_dir = BIN_DIR
            if not os.path.exists(os.path.join(ffmpeg_dir, 'ffmpeg.exe')):
                self.finished_signal.emit(False, "LỖI: Không tìm thấy thư mục FFmpeg!", [])
                return

            audio_mode = get_audio_mode_from_quality(self.quality)
            is_audio_only = (audio_mode is not None)
            downloaded_files = []
            saved_audio_files = []

            for idx, task in enumerate(self.tasks):
                url = task['url']
                clean_url = url.strip()
                if not clean_url.startswith(('http://', 'https://')):
                    clean_url = 'https://' + clean_url

                start_sec = time_to_seconds(task['start'])
                end_sec = time_to_seconds(task['end'])

                self.progress_signal.emit(0, f"Đang xử lý phần {idx + 1}/{len(self.tasks)}...")
                out_dir = MUSIC_DIR if is_audio_only else os.getcwd()
                download_path = os.path.join(out_dir, f'%(title).70s_%(id)s_part{idx}.%(ext)s')

                ydl_opts = {
                    'noplaylist': True,
                    'outtmpl': download_path,
                    'progress_hooks': [self.progress_hook],
                    'ffmpeg_location': ffmpeg_dir,
                    'windowsfilenames': True,
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Referer': 'https://www.facebook.com/'
                    }
                }

                if is_audio_only:
                    ydl_opts['format'] = 'bestaudio/best'
                    ydl_opts['merge_output_format'] = None
                else:
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                    ydl_opts['merge_output_format'] = 'mp4'

                is_cutting = end_sec > 0
                if is_cutting:
                    ydl_opts['download_ranges'] = download_range_func(None, [(start_sec, end_sec)])
                    ydl_opts['force_keyframes_at_cuts'] = True

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(clean_url, download=True)
                    actual_file = info.get('requested_downloads', [{}])[0].get('filepath')
                    if not actual_file:
                        actual_file = ydl.prepare_filename(info)

                    if not is_audio_only:
                        mp4_candidate = os.path.splitext(actual_file)[0] + ".mp4"
                        if os.path.exists(mp4_candidate):
                            actual_file = mp4_candidate
                    else:
                        def _sep_cb(pct, msg):
                            self.progress_signal.emit(pct, msg)
                        processed_mp3, srt_audio_src = process_and_move_audio_by_mode(
                            actual_file, ffmpeg_dir, audio_mode=audio_mode, progress_callback=_sep_cb
                        )
                        if srt_audio_src != processed_mp3:
                            raw_temp_for_srt = srt_audio_src
                        actual_file = processed_mp3
                        saved_audio_files.append(actual_file)

                    downloaded_files.append(actual_file)

            final_file = downloaded_files[0] if downloaded_files else ""

            if len(downloaded_files) > 1 and not is_audio_only:
                self.progress_signal.emit(50, "Đang tiến hành gộp các video...")
                ext = os.path.splitext(downloaded_files[0])[1]
                merged_file = os.path.join(os.getcwd(), f"Merged_FB_{int(time.time())}{ext}")

                fps = 60
                creationflags = 0x08000000 if os.name == 'nt' else 0
                cmd = [os.path.join(ffmpeg_dir, 'ffmpeg.exe'), '-y']

                for f in downloaded_files:
                    cmd.extend(['-i', f])

                filter_str = ""
                concat_inputs = ""
                for i in range(len(downloaded_files)):
                    filter_str += f"[{i}:v]scale={self.target_w}:{self.target_h}:force_original_aspect_ratio=decrease,pad={self.target_w}:{self.target_h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,setsar=1[v{i}];"
                    filter_str += f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a{i}];"
                    concat_inputs += f"[v{i}][a{i}]"

                filter_str += f"{concat_inputs}concat=n={len(downloaded_files)}:v=1:a=1[outv][outa]"
                cmd.extend([
                    '-filter_complex', filter_str,
                    '-map', '[outv]',
                    '-map', '[outa]',
                    '-c:v', 'libx264',
                    '-preset', 'fast',
                    '-c:a', 'aac',
                    merged_file
                ])

                process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         creationflags=creationflags)
                if process.returncode != 0:
                    error_msg = process.stderr.decode('utf-8', errors='ignore')
                    raise Exception(f"Lỗi FFmpeg khi gộp:\n{error_msg}")

                final_file = merged_file
                try:
                    for f in downloaded_files:
                        if os.path.exists(f):
                            os.remove(f)
                except Exception:
                    pass

            if self.generate_subs and final_file:
                def sub_cb(pct, msg):
                    self.progress_signal.emit(pct, msg)
                direct_url = get_direct_sub_url_if_eligible(self.tasks)
                pre_vocal = final_file if audio_mode == "vocal_only" else None
                source_for_sub = raw_temp_for_srt if (audio_mode == "beat_only" and raw_temp_for_srt and os.path.exists(raw_temp_for_srt)) else final_file

                srt_out = generate_subtitles(
                    source_for_sub,
                    progress_callback=sub_cb,
                    ffmpeg_dir=BIN_DIR,
                    language=self.sub_lang,
                    model_size=self.sub_model,
                    source_url=direct_url,
                    pre_isolated_vocal_path=pre_vocal
                )
                if audio_mode == "beat_only" and srt_out and os.path.exists(srt_out):
                    expected_beat_srt = os.path.splitext(final_file)[0] + ".srt"
                    if os.path.abspath(srt_out) != os.path.abspath(expected_beat_srt):
                        try:
                            shutil.move(srt_out, expected_beat_srt)
                            srt_out = expected_beat_srt
                        except Exception:
                            pass

                if srt_out and os.path.exists(srt_out) and not is_audio_only:
                    try:
                        shutil.copy2(srt_out, os.path.join(MUSIC_DIR, os.path.basename(srt_out)))
                    except Exception:
                        pass

            self.progress_signal.emit(100, "Hoàn tất tải và xử lý!")
            save_loc = MUSIC_DIR if is_audio_only else os.getcwd()
            self.finished_signal.emit(True, f"Thành công! Đã lưu tại:\n{save_loc}", saved_audio_files)
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi hệ thống:\n{str(e)}", [])
        finally:
            if raw_temp_for_srt and os.path.exists(raw_temp_for_srt):
                try:
                    os.remove(raw_temp_for_srt)
                except Exception:
                    pass


class TikTokDownloadThread(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str, list)

    def __init__(self, tasks, quality, generate_subs, sub_lang="auto", sub_model="standard", target_w=1080, target_h=1920):
        super().__init__()
        self.tasks = tasks
        self.quality = quality
        self.generate_subs = generate_subs
        self.sub_lang = sub_lang
        self.sub_model = sub_model
        self.target_w = target_w
        self.target_h = target_h

    def run(self):
        raw_temp_for_srt = None
        try:
            ffmpeg_dir = BIN_DIR
            ffmpeg_exe = os.path.join(ffmpeg_dir, 'ffmpeg.exe')
            if not os.path.exists(ffmpeg_exe):
                self.finished_signal.emit(False, "LỖI: Không tìm thấy thư mục FFmpeg!", [])
                return

            audio_mode = get_audio_mode_from_quality(self.quality)
            is_audio_only = (audio_mode is not None)
            downloaded_files = []
            saved_audio_files = []

            for idx, task in enumerate(self.tasks):
                url = task['url']
                start_sec = time_to_seconds(task['start'])
                end_sec = time_to_seconds(task['end'])

                self.progress_signal.emit(0, f"Đang xử lý phần {idx + 1}/{len(self.tasks)}...")

                api_url = "https://www.tikwm.com/api/"
                data = {"url": url, "hd": 1}
                response = requests.post(api_url, data=data, timeout=15).json()

                if response.get("code") == 0:
                    video_info = response.get("data", {})
                    title = video_info.get("title", f"TikTok_Video_{idx}")
                    safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
                    if not safe_title:
                        safe_title = f"TikTok_{int(time.time())}_{idx}"

                    if is_audio_only:
                        if self.generate_subs or audio_mode in ("beat_only", "vocal_only"):
                            media_url = video_info.get("play") or video_info.get("music")
                        else:
                            media_url = video_info.get("music") or video_info.get("play")
                        ext = "mp3"
                        out_dir = MUSIC_DIR
                    else:
                        media_url = video_info.get("hdplay") or video_info.get("play")
                        ext = "mp4"
                        out_dir = os.getcwd()

                    raw_download_path = os.path.join(out_dir, f"{safe_title[:50]}_raw_{idx}.{ext}")
                    final_path = os.path.join(out_dir, f"{safe_title[:50]}_part{idx}.{ext}")

                    req = requests.get(media_url, stream=True)
                    total_length = req.headers.get('content-length')

                    with open(raw_download_path, "wb") as f:
                        if total_length is None:
                            f.write(req.content)
                        else:
                            dl = 0
                            total_length = int(total_length)
                            for data_chunk in req.iter_content(chunk_size=4096):
                                dl += len(data_chunk)
                                f.write(data_chunk)
                                done = int(100 * dl / total_length)
                                scaled = int(done * 0.5) if self.generate_subs else done
                                self.progress_signal.emit(scaled, f"Đang tải TikTok: {done}%")

                    creationflags = 0x08000000 if os.name == 'nt' else 0

                    if not is_audio_only:
                        self.progress_signal.emit(25, "Đang chuẩn hóa video...")
                        cmd = [ffmpeg_exe, '-y', '-i', raw_download_path]

                        is_cutting = end_sec > 0
                        if is_cutting:
                            cmd.extend(['-ss', str(start_sec), '-to', str(end_sec)])

                        cmd.extend([
                            '-c:v', 'libx264',
                            '-preset', 'fast',
                            '-r', '60',
                            '-c:a', 'aac',
                            '-ac', '2',
                            '-ar', '44100',
                            final_path
                        ])
                        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=creationflags)
                        try:
                            os.remove(raw_download_path)
                        except Exception:
                            pass
                        downloaded_files.append(final_path)
                    else:
                        if os.path.exists(final_path):
                            try:
                                os.remove(final_path)
                            except Exception:
                                pass
                        os.rename(raw_download_path, final_path)
                        def _sep_cb(pct, msg):
                            self.progress_signal.emit(pct, msg)
                        processed_mp3, srt_audio_src = process_and_move_audio_by_mode(
                            final_path, ffmpeg_dir, audio_mode=audio_mode, progress_callback=_sep_cb
                        )
                        if srt_audio_src != processed_mp3:
                            raw_temp_for_srt = srt_audio_src
                        final_path = processed_mp3
                        saved_audio_files.append(final_path)
                        downloaded_files.append(final_path)
                else:
                    raise Exception(f"API TikWM phản hồi lỗi: {response.get('msg', 'Không lấy được video')}")

            final_file = downloaded_files[0] if downloaded_files else ""

            if len(downloaded_files) > 1 and not is_audio_only:
                self.progress_signal.emit(50, "Đang tiến hành gộp các video...")

                ext = os.path.splitext(downloaded_files[0])[1]
                merged_file = os.path.join(os.getcwd(), f"Merged_TT_{int(time.time())}{ext}")

                fps = 60
                creationflags = 0x08000000 if os.name == 'nt' else 0
                cmd = [os.path.join(ffmpeg_dir, 'ffmpeg.exe'), '-y']
                for f in downloaded_files:
                    cmd.extend(['-i', f])

                filter_str = ""
                concat_inputs = ""
                for i in range(len(downloaded_files)):
                    filter_str += f"[{i}:v]scale={self.target_w}:{self.target_h}:force_original_aspect_ratio=decrease,pad={self.target_w}:{self.target_h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,setsar=1[v{i}];"
                    filter_str += f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a{i}];"
                    concat_inputs += f"[v{i}][a{i}]"

                filter_str += f"{concat_inputs}concat=n={len(downloaded_files)}:v=1:a=1[outv][outa]"
                cmd.extend([
                    '-filter_complex', filter_str,
                    '-map', '[outv]',
                    '-map', '[outa]',
                    '-c:v', 'libx264',
                    '-preset', 'fast',
                    '-c:a', 'aac',
                    merged_file
                ])

                process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         creationflags=creationflags)

                if process.returncode != 0:
                    error_msg = process.stderr.decode('utf-8', errors='ignore')
                    raise Exception(f"Lỗi FFmpeg khi gộp:\n{error_msg}")

                final_file = merged_file
                for f in downloaded_files:
                    if os.path.exists(f):
                        os.remove(f)

            if self.generate_subs and final_file:
                def sub_cb(pct, msg):
                    self.progress_signal.emit(pct, msg)
                direct_url = get_direct_sub_url_if_eligible(self.tasks)
                pre_vocal = final_file if audio_mode == "vocal_only" else None
                source_for_sub = raw_temp_for_srt if (audio_mode == "beat_only" and raw_temp_for_srt and os.path.exists(raw_temp_for_srt)) else final_file

                srt_out = generate_subtitles(
                    source_for_sub,
                    progress_callback=sub_cb,
                    ffmpeg_dir=BIN_DIR,
                    language=self.sub_lang,
                    model_size=self.sub_model,
                    source_url=direct_url,
                    pre_isolated_vocal_path=pre_vocal
                )
                if audio_mode == "beat_only" and srt_out and os.path.exists(srt_out):
                    expected_beat_srt = os.path.splitext(final_file)[0] + ".srt"
                    if os.path.abspath(srt_out) != os.path.abspath(expected_beat_srt):
                        try:
                            shutil.move(srt_out, expected_beat_srt)
                            srt_out = expected_beat_srt
                        except Exception:
                            pass

                if srt_out and os.path.exists(srt_out) and not is_audio_only:
                    try:
                        shutil.copy2(srt_out, os.path.join(MUSIC_DIR, os.path.basename(srt_out)))
                    except Exception:
                        pass

            self.progress_signal.emit(100, "Hoàn tất tải và xử lý TikTok!")
            save_loc = MUSIC_DIR if is_audio_only else os.getcwd()
            self.finished_signal.emit(True, f"Thành công! Đã lưu tại:\n{save_loc}", saved_audio_files)
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi hệ thống:\n{str(e)}", [])
        finally:
            if raw_temp_for_srt and os.path.exists(raw_temp_for_srt):
                try:
                    os.remove(raw_temp_for_srt)
                except Exception:
                    pass


class InstagramDownloadThread(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str, list)

    def __init__(self, tasks, quality, generate_subs, sub_lang="auto", sub_model="standard", target_w=1080, target_h=1920):
        super().__init__()
        self.tasks = tasks
        self.quality = quality
        self.generate_subs = generate_subs
        self.sub_lang = sub_lang
        self.sub_model = sub_model
        self.target_w = target_w
        self.target_h = target_h

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            p_str = d.get('_percent_str', '0%').strip()
            try:
                val = int(float(p_str.replace('%', '').strip()))
            except Exception:
                val = 0
            scaled = int(val * 0.5) if self.generate_subs else val
            self.progress_signal.emit(scaled, f"Đang tải dữ liệu: {p_str}")

    def run(self):
        raw_temp_for_srt = None
        try:
            ffmpeg_dir = BIN_DIR
            if not os.path.exists(os.path.join(ffmpeg_dir, 'ffmpeg.exe')):
                self.finished_signal.emit(False, "LỖI: Không tìm thấy thư mục FFmpeg!", [])
                return

            audio_mode = get_audio_mode_from_quality(self.quality)
            is_audio_only = (audio_mode is not None)
            downloaded_files = []
            saved_audio_files = []

            for idx, task in enumerate(self.tasks):
                url = task['url']
                clean_url = url.strip()
                if not clean_url.startswith(('http://', 'https://')):
                    clean_url = 'https://' + clean_url

                start_sec = time_to_seconds(task['start'])
                end_sec = time_to_seconds(task['end'])

                self.progress_signal.emit(0, f"Đang xử lý phần {idx + 1}/{len(self.tasks)}...")
                out_dir = MUSIC_DIR if is_audio_only else os.getcwd()
                download_path = os.path.join(out_dir, f'%(title).70s_%(id)s_part{idx}.%(ext)s')

                ydl_opts = {
                    'noplaylist': True,
                    'outtmpl': download_path,
                    'progress_hooks': [self.progress_hook],
                    'ffmpeg_location': ffmpeg_dir,
                    'windowsfilenames': True,
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Referer': 'https://www.instagram.com/'
                    }
                }

                if is_audio_only:
                    ydl_opts['format'] = 'bestaudio/best'
                    ydl_opts['merge_output_format'] = None
                else:
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                    ydl_opts['merge_output_format'] = 'mp4'

                is_cutting = end_sec > 0
                if is_cutting:
                    ydl_opts['download_ranges'] = download_range_func(None, [(start_sec, end_sec)])
                    ydl_opts['force_keyframes_at_cuts'] = True

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(clean_url, download=True)
                    actual_file = info.get('requested_downloads', [{}])[0].get('filepath')
                    if not actual_file:
                        actual_file = ydl.prepare_filename(info)

                    if not is_audio_only:
                        mp4_candidate = os.path.splitext(actual_file)[0] + ".mp4"
                        if os.path.exists(mp4_candidate):
                            actual_file = mp4_candidate
                    else:
                        def _sep_cb(pct, msg):
                            self.progress_signal.emit(pct, msg)
                        processed_mp3, srt_audio_src = process_and_move_audio_by_mode(
                            actual_file, ffmpeg_dir, audio_mode=audio_mode, progress_callback=_sep_cb
                        )
                        if srt_audio_src != processed_mp3:
                            raw_temp_for_srt = srt_audio_src
                        actual_file = processed_mp3
                        saved_audio_files.append(actual_file)

                    downloaded_files.append(actual_file)

            final_file = downloaded_files[0] if downloaded_files else ""

            if len(downloaded_files) > 1 and not is_audio_only:
                self.progress_signal.emit(50, "Đang tiến hành gộp các video...")
                ext = os.path.splitext(downloaded_files[0])[1]
                merged_file = os.path.join(os.getcwd(), f"Merged_IG_{int(time.time())}{ext}")

                fps = 60
                creationflags = 0x08000000 if os.name == 'nt' else 0
                cmd = [os.path.join(ffmpeg_dir, 'ffmpeg.exe'), '-y']

                for f in downloaded_files:
                    cmd.extend(['-i', f])

                filter_str = ""
                concat_inputs = ""
                for i in range(len(downloaded_files)):
                    filter_str += f"[{i}:v]scale={self.target_w}:{self.target_h}:force_original_aspect_ratio=decrease,pad={self.target_w}:{self.target_h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,setsar=1[v{i}];"
                    filter_str += f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a{i}];"
                    concat_inputs += f"[v{i}][a{i}]"

                filter_str += f"{concat_inputs}concat=n={len(downloaded_files)}:v=1:a=1[outv][outa]"
                cmd.extend([
                    '-filter_complex', filter_str,
                    '-map', '[outv]',
                    '-map', '[outa]',
                    '-c:v', 'libx264',
                    '-preset', 'fast',
                    '-c:a', 'aac',
                    merged_file
                ])

                process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)
                if process.returncode != 0:
                    raise Exception(f"Lỗi FFmpeg khi gộp:\n{process.stderr.decode('utf-8', errors='ignore')}")

                final_file = merged_file
                for f in downloaded_files:
                    if os.path.exists(f):
                        os.remove(f)

            if self.generate_subs and final_file:
                def sub_cb(pct, msg):
                    self.progress_signal.emit(pct, msg)
                direct_url = get_direct_sub_url_if_eligible(self.tasks)
                pre_vocal = final_file if audio_mode == "vocal_only" else None
                source_for_sub = raw_temp_for_srt if (audio_mode == "beat_only" and raw_temp_for_srt and os.path.exists(raw_temp_for_srt)) else final_file

                srt_out = generate_subtitles(
                    source_for_sub,
                    progress_callback=sub_cb,
                    ffmpeg_dir=BIN_DIR,
                    language=self.sub_lang,
                    model_size=self.sub_model,
                    source_url=direct_url,
                    pre_isolated_vocal_path=pre_vocal
                )
                if audio_mode == "beat_only" and srt_out and os.path.exists(srt_out):
                    expected_beat_srt = os.path.splitext(final_file)[0] + ".srt"
                    if os.path.abspath(srt_out) != os.path.abspath(expected_beat_srt):
                        try:
                            shutil.move(srt_out, expected_beat_srt)
                            srt_out = expected_beat_srt
                        except Exception:
                            pass

                if srt_out and os.path.exists(srt_out) and not is_audio_only:
                    try:
                        shutil.copy2(srt_out, os.path.join(MUSIC_DIR, os.path.basename(srt_out)))
                    except Exception:
                        pass

            self.progress_signal.emit(100, "Hoàn tất tải và xử lý!")
            save_loc = MUSIC_DIR if is_audio_only else os.getcwd()
            self.finished_signal.emit(True, f"Thành công! Đã lưu tại:\n{save_loc}", saved_audio_files)
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi hệ thống:\n{str(e)}", [])
        finally:
            if raw_temp_for_srt and os.path.exists(raw_temp_for_srt):
                try:
                    os.remove(raw_temp_for_srt)
                except Exception:
                    pass


class PinterestDownloadThread(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str, list)

    def __init__(self, tasks, quality, generate_subs, sub_lang="auto", sub_model="standard", target_w=1920, target_h=1080):
        super().__init__()
        self.tasks = tasks
        self.quality = quality
        self.generate_subs = generate_subs
        self.sub_lang = sub_lang
        self.sub_model = sub_model
        self.target_w = target_w
        self.target_h = target_h

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            p_str = d.get('_percent_str', '0%').strip()
            try:
                val = int(float(p_str.replace('%', '').strip()))
            except Exception:
                val = 0
            scaled = int(val * 0.5) if self.generate_subs else val
            self.progress_signal.emit(scaled, f"Đang tải dữ liệu: {p_str}")

    def run(self):
        raw_temp_for_srt = None
        try:
            ffmpeg_dir = BIN_DIR
            if not os.path.exists(os.path.join(ffmpeg_dir, 'ffmpeg.exe')):
                self.finished_signal.emit(False, "LỖI: Không tìm thấy thư mục FFmpeg!", [])
                return

            audio_mode = get_audio_mode_from_quality(self.quality)
            is_audio_only = (audio_mode is not None)
            downloaded_files = []
            saved_audio_files = []

            for idx, task in enumerate(self.tasks):
                url = task['url']
                clean_url = url.strip()
                if not clean_url.startswith(('http://', 'https://')):
                    clean_url = 'https://' + clean_url

                start_sec = time_to_seconds(task['start'])
                end_sec = time_to_seconds(task['end'])

                self.progress_signal.emit(0, f"Đang xử lý phần {idx + 1}/{len(self.tasks)}...")
                out_dir = MUSIC_DIR if is_audio_only else os.getcwd()
                download_path = os.path.join(out_dir, f'%(title).70s_%(id)s_part{idx}.%(ext)s')

                ydl_opts = {
                    'noplaylist': True,
                    'outtmpl': download_path,
                    'progress_hooks': [self.progress_hook],
                    'ffmpeg_location': ffmpeg_dir,
                    'windowsfilenames': True,
                }

                if is_audio_only:
                    ydl_opts['format'] = 'bestaudio/best'
                    ydl_opts['merge_output_format'] = None
                else:
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                    ydl_opts['merge_output_format'] = 'mp4'

                is_cutting = end_sec > 0
                if is_cutting:
                    ydl_opts['download_ranges'] = download_range_func(None, [(start_sec, end_sec)])
                    ydl_opts['force_keyframes_at_cuts'] = True

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(clean_url, download=True)
                    actual_file = info.get('requested_downloads', [{}])[0].get('filepath')
                    if not actual_file:
                        actual_file = ydl.prepare_filename(info)

                    if is_audio_only:
                        def _sep_cb(pct, msg):
                            self.progress_signal.emit(pct, msg)
                        processed_mp3, srt_audio_src = process_and_move_audio_by_mode(
                            actual_file, ffmpeg_dir, audio_mode=audio_mode, progress_callback=_sep_cb
                        )
                        if srt_audio_src != processed_mp3:
                            raw_temp_for_srt = srt_audio_src
                        actual_file = processed_mp3
                        saved_audio_files.append(actual_file)

                    downloaded_files.append(actual_file)

            final_file = downloaded_files[0] if downloaded_files else ""

            if len(downloaded_files) > 1 and not is_audio_only:
                self.progress_signal.emit(50, "Đang tiến hành gộp các video...")
                ext = os.path.splitext(downloaded_files[0])[1]
                merged_file = os.path.join(os.getcwd(), f"Merged_Pin_{int(time.time())}{ext}")

                fps = 60
                creationflags = 0x08000000 if os.name == 'nt' else 0
                cmd = [os.path.join(ffmpeg_dir, 'ffmpeg.exe'), '-y']

                for f in downloaded_files:
                    cmd.extend(['-i', f])

                filter_str = ""
                concat_inputs = ""
                for i in range(len(downloaded_files)):
                    filter_str += f"[{i}:v]scale={self.target_w}:{self.target_h}:force_original_aspect_ratio=decrease,pad={self.target_w}:{self.target_h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,setsar=1[v{i}];"
                    filter_str += f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a{i}];"
                    concat_inputs += f"[v{i}][a{i}]"

                filter_str += f"{concat_inputs}concat=n={len(downloaded_files)}:v=1:a=1[outv][outa]"
                cmd.extend([
                    '-filter_complex', filter_str,
                    '-map', '[outv]',
                    '-map', '[outa]',
                    '-c:v', 'libx264',
                    '-preset', 'fast',
                    '-c:a', 'aac',
                    merged_file
                ])

                process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)
                if process.returncode != 0:
                    raise Exception(f"Lỗi FFmpeg khi gộp:\n{process.stderr.decode('utf-8', errors='ignore')}")

                final_file = merged_file
                for f in downloaded_files:
                    if os.path.exists(f):
                        os.remove(f)

            if self.generate_subs and final_file:
                def sub_cb(pct, msg):
                    self.progress_signal.emit(pct, msg)
                direct_url = get_direct_sub_url_if_eligible(self.tasks)
                pre_vocal = final_file if audio_mode == "vocal_only" else None
                source_for_sub = raw_temp_for_srt if (audio_mode == "beat_only" and raw_temp_for_srt and os.path.exists(raw_temp_for_srt)) else final_file

                srt_out = generate_subtitles(
                    source_for_sub,
                    progress_callback=sub_cb,
                    ffmpeg_dir=BIN_DIR,
                    language=self.sub_lang,
                    model_size=self.sub_model,
                    source_url=direct_url,
                    pre_isolated_vocal_path=pre_vocal
                )
                if audio_mode == "beat_only" and srt_out and os.path.exists(srt_out):
                    expected_beat_srt = os.path.splitext(final_file)[0] + ".srt"
                    if os.path.abspath(srt_out) != os.path.abspath(expected_beat_srt):
                        try:
                            shutil.move(srt_out, expected_beat_srt)
                            srt_out = expected_beat_srt
                        except Exception:
                            pass

                if srt_out and os.path.exists(srt_out) and not is_audio_only:
                    try:
                        shutil.copy2(srt_out, os.path.join(MUSIC_DIR, os.path.basename(srt_out)))
                    except Exception:
                        pass

            self.progress_signal.emit(100, "Hoàn tất tải và xử lý!")
            save_loc = MUSIC_DIR if is_audio_only else os.getcwd()
            self.finished_signal.emit(True, f"Thành công! Đã lưu tại:\n{save_loc}", saved_audio_files)
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi hệ thống:\n{str(e)}", [])
        finally:
            if raw_temp_for_srt and os.path.exists(raw_temp_for_srt):
                try:
                    os.remove(raw_temp_for_srt)
                except Exception:
                    pass


class MainApp(ModernUI):
    def __init__(self):
        super().__init__()
        self.is_downloading = False
        self.player = None
        self.preview_thread = None

        self.audio_player = None
        self.playlist_tracks = []
        self.current_track_index = -1
        self.is_shuffle = False
        self.is_loop_one = False
        self.shuffle_history = []
        self.shuffle_bag = []
        self.audio_started_flag = False

        self.current_track_lyrics = []
        self.last_lyric_active_idx = -999

        self.download_tabs = [
            self.youtube_tab,
            self.facebook_tab,
            self.tiktok_tab,
            self.instagram_tab,
            self.pinterest_tab
        ]
        self.platform_names = [
            "YouTube",
            "Facebook",
            "TikTok",
            "Instagram",
            "Pinterest"
        ]

        for tab, name in zip(self.download_tabs, self.platform_names):
            tab.load_btn.clicked.connect(lambda checked=False, t=tab, n=name: self.load_preview(t, n))
            tab.add_btn.clicked.connect(lambda checked=False, t=tab: self.add_link_to_list(t))
            tab.remove_btn.clicked.connect(lambda checked=False, t=tab: self.remove_link_from_list(t))
            tab.volume_slider.valueChanged.connect(self.set_volume)
            tab.time_slider.sliderMoved.connect(self.set_position)

            tab.add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tab.remove_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tab.download_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tab.load_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tab.time_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tab.volume_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.youtube_tab.download_btn.clicked.connect(self.start_download_youtube)
        self.facebook_tab.download_btn.clicked.connect(self.start_download_facebook)
        self.tiktok_tab.download_btn.clicked.connect(self.start_download_tiktok)
        self.instagram_tab.download_btn.clicked.connect(self.start_download_instagram)
        self.pinterest_tab.download_btn.clicked.connect(self.start_download_pinterest)

        pt = self.playlist_tab
        pt.refresh_btn.clicked.connect(self.refresh_playlist_directory)
        pt.add_files_btn.clicked.connect(self.add_external_audio_files)
        pt.remove_track_btn.clicked.connect(self.remove_selected_playlist_track)
        pt.play_pause_btn.clicked.connect(self.toggle_playlist_play_pause)
        pt.prev_btn.clicked.connect(self.play_previous_track)
        pt.next_btn.clicked.connect(lambda: self.play_next_track(auto_ended=False))
        pt.loop_btn.clicked.connect(self.toggle_playlist_loop)
        pt.mode_btn.clicked.connect(self.toggle_playlist_mode)
        pt.playlist_widget.itemDoubleClicked.connect(self.on_playlist_item_double_clicked)
        pt.time_slider.sliderMoved.connect(self.set_playlist_position)
        pt.volume_slider.valueChanged.connect(self.set_playlist_volume)

        for widget in [pt.refresh_btn, pt.add_files_btn, pt.remove_track_btn,
                       pt.play_pause_btn, pt.prev_btn, pt.next_btn,
                       pt.loop_btn, pt.mode_btn, pt.time_slider, pt.volume_slider,
                       pt.playlist_widget]:
            widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.load_saved_playlist()
        self.refresh_playlist_directory()

        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.on_tab_changed(0)

        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start()

    def _ensure_audio_player(self):
        if self.audio_player is None:
            self.audio_player = mpv.MPV(
                vid='no',
                vo='null',
                ytdl=False,
                keep_open='no',
                log_handler=lambda level, prefix, text: None
            )
            self.audio_player.volume = self.playlist_tab.volume_slider.value()

    def _destroy_audio_player(self):
        if self.audio_player is not None:
            try:
                self.audio_player.stop()
            except Exception:
                pass
            try:
                self.audio_player.terminate()
            except Exception:
                pass
            self.audio_player = None
        self.audio_started_flag = False

    def _load_lyrics_for_current_track(self, track_path: str):
        self.current_track_lyrics = []
        self.last_lyric_active_idx = -999

        srt_file = find_matching_srt_for_track(track_path)
        if srt_file:
            self.current_track_lyrics = parse_srt_file_to_segments(srt_file)

        if self.current_track_lyrics:
            self._update_scrolling_lyrics_display(0.0)
        else:
            self.playlist_tab.set_track_title_fallback(os.path.basename(track_path))

    def _update_scrolling_lyrics_display(self, current_sec: float):
        if not self.current_track_lyrics:
            return

        effective_time = current_sec + PLAYLIST_LYRIC_ADVANCE_SEC
        n = len(self.current_track_lyrics)

        active_idx = -1
        for i in range(n):
            seg_start = self.current_track_lyrics[i]['start']
            seg_end = self.current_track_lyrics[i]['end']
            next_start = self.current_track_lyrics[i + 1]['start'] if (i + 1 < n) else float('inf')

            if seg_start <= effective_time < next_start:
                # Nếu câu hiện tại đã kết thúc quá lâu (> 4.0s) và đang trong đoạn nhạc dạo giữa bài,
                # giữ ở câu vừa hát nhưng không nhảy sớm sang câu tiếp theo
                active_idx = i
                break

        if active_idx == -1:
            window_lines = [
                (-2, ""),
                (-1, ""),
                (0, "♪ ... ♪"),
                (1, self.current_track_lyrics[0]['text'] if n > 0 else ""),
                (2, self.current_track_lyrics[1]['text'] if n > 1 else ""),
            ]
            if self.last_lyric_active_idx != -1:
                self.last_lyric_active_idx = -1
                self.playlist_tab.render_scrolling_lyrics(window_lines)
            return

        if active_idx == self.last_lyric_active_idx:
            return

        self.last_lyric_active_idx = active_idx
        window_lines = []
        for offset in (-2, -1, 0, 1, 2):
            idx = active_idx + offset
            if 0 <= idx < n:
                window_lines.append((offset, self.current_track_lyrics[idx]['text']))
            else:
                window_lines.append((offset, ""))

        self.playlist_tab.render_scrolling_lyrics(window_lines)

    def load_saved_playlist(self):
        if os.path.exists(PLAYLIST_JSON_PATH):
            try:
                with open(PLAYLIST_JSON_PATH, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                self.playlist_tracks = [p for p in saved if isinstance(p, str) and os.path.exists(p)]
            except Exception:
                self.playlist_tracks = []

    def save_playlist_to_disk(self):
        try:
            with open(PLAYLIST_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.playlist_tracks, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def refresh_playlist_directory(self):
        scan_dirs = [MUSIC_DIR, os.getcwd()]
        existing_set = {os.path.abspath(p) for p in self.playlist_tracks if os.path.exists(p)}
        self.playlist_tracks = [p for p in self.playlist_tracks if os.path.exists(p)]

        for d in scan_dirs:
            if not os.path.isdir(d):
                continue
            for fname in sorted(os.listdir(d)):
                if fname.lower().endswith(AUDIO_EXTENSIONS) and not (
                    fname.endswith("_temp_processed.wav")
                    or fname.endswith("_temp_vocal_for_srt.wav")
                    or fname.endswith("_probe30s.wav")
                    or "_slice_" in fname
                    or "_tmp_demucs_" in fname
                ):
                    full_p = os.path.abspath(os.path.join(d, fname))
                    if full_p not in existing_set:
                        self.playlist_tracks.append(full_p)
                        existing_set.add(full_p)

        self.save_playlist_to_disk()
        self._render_playlist_widget()

    def _render_playlist_widget(self):
        pt = self.playlist_tab
        pt.playlist_widget.clear()
        for idx, path in enumerate(self.playlist_tracks):
            name = os.path.basename(path)
            prefix = "▶  " if idx == self.current_track_index else f"{idx + 1:02d}.  "
            item = QListWidgetItem(f"{prefix}{name}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            pt.playlist_widget.addItem(item)

        if 0 <= self.current_track_index < pt.playlist_widget.count():
            pt.playlist_widget.setCurrentRow(self.current_track_index)

        pt.count_label.setText(f"Tổng số bài: {len(self.playlist_tracks)}")

    def add_downloaded_audio_to_playlist(self, audio_paths: list):
        if not audio_paths:
            return
        existing_set = {os.path.abspath(p) for p in self.playlist_tracks}
        added = False
        for p in audio_paths:
            if p and os.path.exists(p):
                abs_p = os.path.abspath(p)
                if abs_p not in existing_set:
                    self.playlist_tracks.append(abs_p)
                    existing_set.add(abs_p)
                    added = True
        if added:
            self.save_playlist_to_disk()
            self._render_playlist_widget()

    def add_external_audio_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Chọn file âm thanh thêm vào Playlist",
            MUSIC_DIR,
            "Audio Files (*.mp3 *.m4a *.wav *.flac *.ogg *.aac *.opus)"
        )
        if files:
            self.add_downloaded_audio_to_playlist(files)
            self.setFocus()

    def remove_selected_playlist_track(self):
        pt = self.playlist_tab
        row = pt.playlist_widget.currentRow()
        if row < 0 or row >= len(self.playlist_tracks):
            return

        if row == self.current_track_index:
            self.stop_playlist_playback()
            self.current_track_index = -1
        elif row < self.current_track_index:
            self.current_track_index -= 1

        self.playlist_tracks.pop(row)
        self.shuffle_bag = [i for i in self.shuffle_bag if i < len(self.playlist_tracks)]
        self.save_playlist_to_disk()
        self._render_playlist_widget()
        self.setFocus()

    def toggle_playlist_loop(self):
        self.is_loop_one = not self.is_loop_one
        if self.is_loop_one:
            self.playlist_tab.loop_btn.setText("🔂 Lặp 1 bài: Bật")
        else:
            self.playlist_tab.loop_btn.setText("🔂 Lặp 1 bài: Tắt")
        self.setFocus()

    def toggle_playlist_mode(self):
        self.is_shuffle = not self.is_shuffle
        self.shuffle_bag.clear()
        if self.is_shuffle:
            self.playlist_tab.mode_btn.setText("🔀 Chế độ: Nghe trộn")
        else:
            self.playlist_tab.mode_btn.setText("🔁 Chế độ: Theo thứ tự")
        self.setFocus()

    def play_track_at_index(self, index: int, record_history: bool = True):
        if not self.playlist_tracks:
            QMessageBox.information(self, "Playlist trống", "Chưa có file âm thanh nào trong Playlist!")
            return

        index = index % len(self.playlist_tracks)
        track_path = self.playlist_tracks[index]
        if not os.path.exists(track_path):
            self.refresh_playlist_directory()
            return

        self._destroy_player()

        if record_history and self.current_track_index != -1 and self.current_track_index != index:
            self.shuffle_history.append(self.current_track_index)

        self.current_track_index = index
        self._ensure_audio_player()
        self.audio_started_flag = False

        try:
            self._load_lyrics_for_current_track(track_path)
            self.audio_player.play(track_path)
            self.audio_player.pause = False
            self.playlist_tab.play_pause_btn.setText("⏸ Tạm dừng")
            self.playlist_tab.status_label.setText("Trạng thái: Đang phát nhạc trong Playlist")
            self._render_playlist_widget()
            self.setFocus()
        except Exception as e:
            QMessageBox.critical(self, "Lỗi phát nhạc", f"Không thể phát file:\n{e}")

    def on_playlist_item_double_clicked(self, item):
        row = self.playlist_tab.playlist_widget.row(item)
        if row >= 0:
            self.play_track_at_index(row)

    def toggle_playlist_play_pause(self):
        if not self.playlist_tracks:
            self.refresh_playlist_directory()
            if not self.playlist_tracks:
                QMessageBox.information(self, "Playlist trống", "Hãy tải âm thanh từ các tab hoặc thêm file nhạc vào Playlist!")
                return

        if self.audio_player is None or self.current_track_index == -1:
            selected_row = self.playlist_tab.playlist_widget.currentRow()
            start_idx = selected_row if selected_row >= 0 else (random.randrange(len(self.playlist_tracks)) if self.is_shuffle else 0)
            self.play_track_at_index(start_idx)
            return

        try:
            if self.audio_player.core_idle and not self.audio_player.pause and self.audio_started_flag:
                self.play_track_at_index(self.current_track_index)
                return

            self.audio_player.pause = not self.audio_player.pause
            if self.audio_player.pause:
                self.playlist_tab.play_pause_btn.setText("▶ Tiếp tục")
                self.playlist_tab.status_label.setText("Trạng thái: Đang tạm dừng")
            else:
                self.playlist_tab.play_pause_btn.setText("⏸ Tạm dừng")
                self.playlist_tab.status_label.setText("Trạng thái: Đang phát nhạc trong Playlist")
            self.setFocus()
        except Exception:
            pass

    def stop_playlist_playback(self):
        if self.audio_player is not None:
            try:
                self.audio_player.stop()
            except Exception:
                pass
        self.audio_started_flag = False
        self.current_track_lyrics = []
        self.last_lyric_active_idx = -999
        self.playlist_tab.play_pause_btn.setText("▶ Phát")
        self.playlist_tab.time_slider.setRange(0, 0)
        self.playlist_tab.time_slider.setValue(0)
        self.playlist_tab.time_slider.setDisabled(True)
        self.playlist_tab.time_label.setText("00:00 / 00:00")
        self.playlist_tab.status_label.setText("Trạng thái: Sẵn sàng phát nhạc")

    def play_next_track(self, auto_ended: bool = False):
        if not self.playlist_tracks:
            return

        if auto_ended and self.is_loop_one and self.current_track_index != -1:
            self.play_track_at_index(self.current_track_index, record_history=False)
            return

        n = len(self.playlist_tracks)
        if n == 1:
            self.play_track_at_index(0, record_history=False)
            return

        if self.is_shuffle:
            if not self.shuffle_bag:
                self.shuffle_bag = [i for i in range(n) if i != self.current_track_index]
                random.shuffle(self.shuffle_bag)
            next_idx = self.shuffle_bag.pop(0) if self.shuffle_bag else 0
        else:
            next_idx = (self.current_track_index + 1) % n

        self.play_track_at_index(next_idx)

    def play_previous_track(self):
        if not self.playlist_tracks:
            return
        if self.is_shuffle and self.shuffle_history:
            prev_idx = self.shuffle_history.pop()
            self.play_track_at_index(prev_idx, record_history=False)
        else:
            prev_idx = (self.current_track_index - 1) % len(self.playlist_tracks)
            self.play_track_at_index(prev_idx, record_history=False)

    def set_playlist_position(self, position):
        if self.audio_player is not None and self.audio_player.duration is not None:
            try:
                self.audio_player.time_pos = position
                if self.current_track_lyrics:
                    self.last_lyric_active_idx = -999
                    self._update_scrolling_lyrics_display(float(position))
            except Exception:
                pass
        self.setFocus()

    def set_playlist_volume(self, value):
        if self.audio_player is not None:
            try:
                self.audio_player.volume = value
            except Exception:
                pass
        if self.playlist_tab.volume_slider.value() != value:
            self.playlist_tab.volume_slider.setValue(value)

    def _destroy_player(self):
        if self.player is not None:
            try:
                self.player.stop()
            except Exception:
                pass
            try:
                self.player.terminate()
            except Exception:
                pass
            self.player = None

    def _init_player_for_tab(self, tab):
        self.stop_playlist_playback()
        self._destroy_player()
        tab.show_preview()
        QApplication.processEvents()

        target_wid = int(tab.video_widget.winId())
        self.player = mpv.MPV(
            wid=str(target_wid),
            ytdl=True,
            vo='gpu,direct3d',
            hwdec='auto-safe',
            cache='yes',
            demuxer_max_bytes='150M',
            demuxer_max_back_bytes='50M',
            keep_open='yes',
            log_handler=lambda level, prefix, text: None
        )
        self.player.volume = tab.volume_slider.value()
        self.player.pause = False

    def get_current_tab(self):
        idx = self.tabs.currentIndex()
        if 0 <= idx < len(self.download_tabs):
            return self.download_tabs[idx]
        return self.playlist_tab

    def on_tab_changed(self, index):
        self.update_tab_color(index)
        if self.preview_thread and self.preview_thread.isRunning():
            try:
                self.preview_thread.success_signal.disconnect()
                self.preview_thread.error_signal.disconnect()
            except Exception:
                pass
        self._destroy_player()

        for tab in self.download_tabs:
            tab.show_info()
            tab.url_input.clear()
            tab.load_btn.setDisabled(False)
            tab.time_slider.setRange(0, 0)
            tab.time_slider.setValue(0)
            tab.time_slider.setDisabled(True)
            tab.time_label.setText("00:00 / 00:00")
            tab.status_label.setText("Trạng thái: Sẵn sàng")

        if index == 5:
            self.refresh_playlist_directory()
            if 0 <= self.current_track_index < len(self.playlist_tracks):
                self._load_lyrics_for_current_track(self.playlist_tracks[self.current_track_index])
            self.setFocus()

    def update_tab_color(self, index):
        colors = ["#e62117", "#1877F2", "#000000", "#833AB4", "#E60023", "#000000"]
        color = colors[index] if index < len(colors) else "#000000"
        self.tabs.setStyleSheet(
            f"QTabBar::tab {{ font-size: 14px; font-weight: bold; padding: 10px 18px; margin-right: 2px; }} QTabBar::tab:selected {{ background-color: #e0e0e0; border-top: 3px solid {color}; }}")

    def add_link_to_list(self, tab):
        url = tab.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Lỗi", "Vui lòng nhập link video!")
            return

        start = tab.start_input.text().strip()
        end = tab.end_input.text().strip()

        display_text = f"[{start or '00:00'} -> {end or 'Cuối'}] {url}"
        item = QListWidgetItem(display_text)

        item.setData(Qt.ItemDataRole.UserRole, {'url': url, 'start': start, 'end': end})

        tab.list_widget.addItem(item)
        tab.url_input.clear()
        tab.start_input.clear()
        tab.end_input.clear()

    def remove_link_from_list(self, tab):
        for item in tab.list_widget.selectedItems():
            tab.list_widget.takeItem(tab.list_widget.row(item))

    def set_volume(self, value):
        if self.player is not None:
            try:
                self.player.volume = value
            except Exception:
                pass
        tab = self.get_current_tab()
        if hasattr(tab, 'volume_slider') and tab.volume_slider.value() != value:
            tab.volume_slider.setValue(value)

    def format_time(self, seconds):
        if seconds is None:
            return "00:00"
        secs = int(seconds)
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    def update_ui(self):
        try:
            if self.audio_player is not None and self.current_track_index != -1:
                a_dur = self.audio_player.duration
                a_pos = self.audio_player.time_pos
                pt = self.playlist_tab

                if a_dur is not None and a_pos is not None:
                    self.audio_started_flag = True
                    pt.time_slider.setDisabled(False)
                    if not pt.time_slider.isSliderDown():
                        pt.time_slider.setRange(0, int(a_dur))
                        pt.time_slider.setValue(int(a_pos))
                    pt.time_label.setText(f"{self.format_time(a_pos)} / {self.format_time(a_dur)}")

                    if self.current_track_lyrics:
                        self._update_scrolling_lyrics_display(float(a_pos))

                    if self.audio_player.pause:
                        pt.play_pause_btn.setText("▶ Tiếp tục")
                        pt.status_label.setText("Trạng thái: Đang tạm dừng")
                    else:
                        pt.play_pause_btn.setText("⏸ Tạm dừng")
                        loop_txt = " • Đang bật Lặp 1 bài" if self.is_loop_one else ""
                        lyric_txt = " • Đang hiện Lyrics (.srt)" if self.current_track_lyrics else ""
                        pt.status_label.setText(f"Trạng thái: Đang phát nhạc{loop_txt}{lyric_txt}")
                elif self.audio_started_flag and self.audio_player.core_idle and not self.audio_player.pause:
                    self.audio_started_flag = False
                    self.play_next_track(auto_ended=True)
        except Exception:
            pass

        try:
            if self.player is None:
                return
            tab = self.get_current_tab()
            if hasattr(tab, 'preview_container') and tab.preview_container.isVisible():
                duration = self.player.duration
                time_pos = self.player.time_pos

                if duration is not None and time_pos is not None:
                    tab.time_slider.setDisabled(False)
                    if not tab.time_slider.isSliderDown():
                        tab.time_slider.setRange(0, int(duration))
                        tab.time_slider.setValue(int(time_pos))

                    curr = self.format_time(time_pos)
                    tot = self.format_time(duration)
                    tab.time_label.setText(f"{curr} / {tot}")

                if not self.is_downloading:
                    if self.player.core_idle and not self.player.pause:
                        tab.status_label.setText("Trạng thái: Đang tải dữ liệu...")
                    elif not self.player.pause:
                        tab.status_label.setText("Trạng thái: Đang phát Preview")
                    else:
                        tab.status_label.setText("Trạng thái: Đang Tạm Dừng.")
        except Exception:
            pass

    def set_position(self, position):
        if self.player is not None and self.player.duration is not None:
            try:
                self.player.time_pos = position
            except Exception:
                pass

    def load_preview(self, tab=None, platform_name=None):
        if tab is None:
            tab = self.get_current_tab()
        if platform_name is None:
            idx = self.tabs.currentIndex()
            platform_name = self.platform_names[idx] if 0 <= idx < len(self.platform_names) else "nền tảng"

        url = tab.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Lỗi", "Vui lòng nhập link video!")
            return

        clean_url = url
        if not clean_url.startswith(('http://', 'https://')):
            clean_url = 'https://' + clean_url

        tab.show_preview()
        tab.time_slider.setRange(0, 0)
        tab.time_slider.setValue(0)
        tab.time_slider.setDisabled(True)
        tab.time_label.setText("00:00 / 00:00")
        tab.status_label.setText(f"Trạng thái: Đang kết nối với {platform_name}...")
        tab.load_btn.setDisabled(True)

        self._destroy_player()

        if self.preview_thread and self.preview_thread.isRunning():
            try:
                self.preview_thread.success_signal.disconnect()
                self.preview_thread.error_signal.disconnect()
            except Exception:
                pass

        self.preview_thread = PreviewLoadThread(clean_url, platform_name)
        self.preview_thread.success_signal.connect(
            lambda v_url, a_url, hdrs, t=tab: self._on_preview_stream_ready(t, v_url, a_url, hdrs)
        )
        self.preview_thread.error_signal.connect(
            lambda err_msg, t=tab, u=clean_url: self._on_preview_stream_error(t, u, err_msg)
        )
        self.preview_thread.start()

    def _on_preview_stream_ready(self, tab, video_url, audio_url, header_list):
        if tab != self.get_current_tab():
            tab.load_btn.setDisabled(False)
            return

        try:
            self._init_player_for_tab(tab)
            if header_list:
                try:
                    self.player['http-header-fields'] = header_list
                except Exception:
                    pass
            if audio_url:
                try:
                    self.player['audio-files'] = [audio_url]
                except Exception:
                    pass

            self.player.play(video_url)
            self.player.pause = False
            tab.load_btn.setDisabled(False)
            self.setFocus()
            tab.status_label.setText("Trạng thái: Đang tải dữ liệu...")
        except Exception as e:
            tab.load_btn.setDisabled(False)
            tab.status_label.setText("Trạng thái: Lỗi kết nối")
            QMessageBox.critical(self, "Lỗi Preview", f"Không thể phát:\n{e}")

    def _on_preview_stream_error(self, tab, fallback_url, err_msg):
        if tab != self.get_current_tab():
            tab.load_btn.setDisabled(False)
            return

        try:
            self._init_player_for_tab(tab)
            self.player.play(fallback_url)
            self.player.pause = False
            tab.load_btn.setDisabled(False)
            self.setFocus()
            tab.status_label.setText("Trạng thái: Đang tải dữ liệu...")
        except Exception:
            tab.load_btn.setDisabled(False)
            tab.status_label.setText("Trạng thái: Lỗi kết nối")
            QMessageBox.critical(self, "Lỗi Preview", f"Không thể phát:\n{err_msg}")

    def update_progress(self, tab, percent, msg):
        tab.progress_bar.setValue(percent)
        tab.status_label.setText(f"Trạng thái: {msg}")

    def start_download_youtube(self):
        tasks = [self.youtube_tab.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.youtube_tab.list_widget.count())]

        if not tasks:
            QMessageBox.warning(self, "Lỗi", "Danh sách tải trống! Vui lòng thêm link.")
            return

        quality = self.youtube_tab.quality_combo.currentText()
        target_w, target_h = 1920, 1080
        if len(tasks) > 1 and get_audio_mode_from_quality(quality) is None:
            dialog = AspectRatioDialog("#e62117", self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                target_w, target_h = dialog.get_resolution()
            else:
                return

        self._destroy_player()
        self.is_downloading = True
        self.youtube_tab.download_btn.setDisabled(True)
        self.youtube_tab.progress_bar.setValue(0)

        subs = self.youtube_tab.sub_checkbox.isChecked()
        sub_lang = self.youtube_tab.sub_lang_combo.currentData()
        sub_model = self.youtube_tab.sub_model_combo.currentData()

        self.yt_thread = YoutubeDownloadThread(tasks, quality, subs, sub_lang, sub_model, target_w, target_h)
        self.yt_thread.progress_signal.connect(lambda pct, msg: self.update_progress(self.youtube_tab, pct, msg))
        self.yt_thread.finished_signal.connect(self.download_finished_youtube)
        self.yt_thread.start()

    def download_finished_youtube(self, success, message, audio_files):
        self.is_downloading = False
        self.youtube_tab.download_btn.setDisabled(False)
        self.youtube_tab.progress_bar.setValue(100 if success else 0)
        self.youtube_tab.show_info()
        if success:
            self.add_downloaded_audio_to_playlist(audio_files)
            QMessageBox.information(self, "Hoàn tất", message)
            self.youtube_tab.list_widget.clear()
        else:
            QMessageBox.critical(self, "Lỗi", message)

    def start_download_facebook(self):
        tasks = [self.facebook_tab.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.facebook_tab.list_widget.count())]

        if not tasks:
            QMessageBox.warning(self, "Lỗi", "Danh sách tải trống! Vui lòng thêm link.")
            return

        quality = self.facebook_tab.quality_combo.currentText()
        target_w, target_h = 1920, 1080
        if len(tasks) > 1 and get_audio_mode_from_quality(quality) is None:
            dialog = AspectRatioDialog("#1877F2", self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                target_w, target_h = dialog.get_resolution()
            else:
                return

        self._destroy_player()
        self.is_downloading = True
        self.facebook_tab.download_btn.setDisabled(True)
        self.facebook_tab.progress_bar.setValue(0)

        subs = self.facebook_tab.sub_checkbox.isChecked()
        sub_lang = self.facebook_tab.sub_lang_combo.currentData()
        sub_model = self.facebook_tab.sub_model_combo.currentData()

        self.fb_thread = FacebookDownloadThread(tasks, quality, subs, sub_lang, sub_model, target_w, target_h)
        self.fb_thread.progress_signal.connect(lambda pct, msg: self.update_progress(self.facebook_tab, pct, msg))
        self.fb_thread.finished_signal.connect(self.download_finished_fb)
        self.fb_thread.start()

    def download_finished_fb(self, success, message, audio_files):
        self.is_downloading = False
        self.facebook_tab.download_btn.setDisabled(False)
        self.facebook_tab.progress_bar.setValue(100 if success else 0)
        self.facebook_tab.show_info()
        if success:
            self.add_downloaded_audio_to_playlist(audio_files)
            QMessageBox.information(self, "Hoàn tất", message)
            self.facebook_tab.list_widget.clear()
        else:
            QMessageBox.critical(self, "Lỗi", message)

    def start_download_tiktok(self):
        tasks = [self.tiktok_tab.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.tiktok_tab.list_widget.count())]

        if not tasks:
            QMessageBox.warning(self, "Lỗi", "Danh sách tải trống! Vui lòng thêm link.")
            return

        quality = self.tiktok_tab.quality_combo.currentText()
        target_w, target_h = 1080, 1920
        if len(tasks) > 1 and get_audio_mode_from_quality(quality) is None:
            dialog = AspectRatioDialog("#000000", self)
            dialog.rb_vertical.setChecked(True)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                target_w, target_h = dialog.get_resolution()
            else:
                return

        self._destroy_player()
        self.is_downloading = True
        self.tiktok_tab.download_btn.setDisabled(True)
        self.tiktok_tab.progress_bar.setValue(0)

        subs = self.tiktok_tab.sub_checkbox.isChecked()
        sub_lang = self.tiktok_tab.sub_lang_combo.currentData()
        sub_model = self.tiktok_tab.sub_model_combo.currentData()

        self.tt_thread = TikTokDownloadThread(tasks, quality, subs, sub_lang, sub_model, target_w, target_h)
        self.tt_thread.progress_signal.connect(lambda pct, msg: self.update_progress(self.tiktok_tab, pct, msg))
        self.tt_thread.finished_signal.connect(self.download_finished_tiktok)
        self.tt_thread.start()

    def download_finished_tiktok(self, success, message, audio_files):
        self.is_downloading = False
        self.tiktok_tab.download_btn.setDisabled(False)
        self.tiktok_tab.progress_bar.setValue(100 if success else 0)
        self.tiktok_tab.show_info()
        if success:
            self.add_downloaded_audio_to_playlist(audio_files)
            QMessageBox.information(self, "Hoàn tất", message)
            self.tiktok_tab.list_widget.clear()
        else:
            QMessageBox.critical(self, "Lỗi", message)

    def start_download_instagram(self):
        tasks = [self.instagram_tab.list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in
                 range(self.instagram_tab.list_widget.count())]
        if not tasks:
            return QMessageBox.warning(self, "Lỗi", "Danh sách tải trống!")

        quality = self.instagram_tab.quality_combo.currentText()
        target_w, target_h = 1080, 1920
        if len(tasks) > 1 and get_audio_mode_from_quality(quality) is None:
            dialog = AspectRatioDialog("#833AB4", self)
            dialog.rb_vertical.setChecked(True)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                target_w, target_h = dialog.get_resolution()
            else:
                return

        self._destroy_player()
        self.is_downloading = True
        self.instagram_tab.download_btn.setDisabled(True)
        self.instagram_tab.progress_bar.setValue(0)

        subs = self.instagram_tab.sub_checkbox.isChecked()
        sub_lang = self.instagram_tab.sub_lang_combo.currentData()
        sub_model = self.instagram_tab.sub_model_combo.currentData()

        self.ig_thread = InstagramDownloadThread(tasks, quality, subs, sub_lang, sub_model, target_w, target_h)
        self.ig_thread.progress_signal.connect(lambda pct, msg: self.update_progress(self.instagram_tab, pct, msg))
        self.ig_thread.finished_signal.connect(self.download_finished_ig)
        self.ig_thread.start()

    def download_finished_ig(self, success, message, audio_files):
        self.is_downloading = False
        self.instagram_tab.download_btn.setDisabled(False)
        self.instagram_tab.progress_bar.setValue(100 if success else 0)
        self.instagram_tab.show_info()
        if success:
            self.add_downloaded_audio_to_playlist(audio_files)
            QMessageBox.information(self, "Hoàn tất", message)
            self.instagram_tab.list_widget.clear()
        else:
            QMessageBox.critical(self, "Lỗi", message)

    def start_download_pinterest(self):
        tasks = [self.pinterest_tab.list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in
                 range(self.pinterest_tab.list_widget.count())]
        if not tasks:
            return QMessageBox.warning(self, "Lỗi", "Danh sách tải trống!")

        quality = self.pinterest_tab.quality_combo.currentText()
        target_w, target_h = 1920, 1080
        if len(tasks) > 1 and get_audio_mode_from_quality(quality) is None:
            dialog = AspectRatioDialog("#E60023", self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                target_w, target_h = dialog.get_resolution()
            else:
                return

        self._destroy_player()
        self.is_downloading = True
        self.pinterest_tab.download_btn.setDisabled(True)
        self.pinterest_tab.progress_bar.setValue(0)

        subs = self.pinterest_tab.sub_checkbox.isChecked()
        sub_lang = self.pinterest_tab.sub_lang_combo.currentData()
        sub_model = self.pinterest_tab.sub_model_combo.currentData()

        self.pin_thread = PinterestDownloadThread(tasks, quality, subs, sub_lang, sub_model, target_w, target_h)
        self.pin_thread.progress_signal.connect(lambda pct, msg: self.update_progress(self.pinterest_tab, pct, msg))
        self.pin_thread.finished_signal.connect(self.download_finished_pin)
        self.pin_thread.start()

    def download_finished_pin(self, success, message, audio_files):
        self.is_downloading = False
        self.pinterest_tab.download_btn.setDisabled(False)
        self.pinterest_tab.progress_bar.setValue(100 if success else 0)
        self.pinterest_tab.show_info()
        if success:
            self.add_downloaded_audio_to_playlist(audio_files)
            QMessageBox.information(self, "Hoàn tất", message)
            self.pinterest_tab.list_widget.clear()
        else:
            QMessageBox.critical(self, "Lỗi", message)

    def keyPressEvent(self, event):
        tab = self.get_current_tab()
        active_player = self.audio_player if tab == self.playlist_tab else self.player
        key = event.key()

        if key == Qt.Key.Key_Space:
            if active_player is not None:
                active_player.pause = not active_player.pause
        elif key == Qt.Key.Key_Left:
            if active_player is not None and active_player.time_pos is not None:
                new_pos = max(0, active_player.time_pos - 5)
                active_player.time_pos = new_pos
                if tab == self.playlist_tab and self.current_track_lyrics:
                    self.last_lyric_active_idx = -999
                    self._update_scrolling_lyrics_display(float(new_pos))
        elif key == Qt.Key.Key_Right:
            if active_player is not None and active_player.time_pos is not None and active_player.duration is not None:
                new_pos = min(active_player.duration, active_player.time_pos + 5)
                active_player.time_pos = new_pos
                if tab == self.playlist_tab and self.current_track_lyrics:
                    self.last_lyric_active_idx = -999
                    self._update_scrolling_lyrics_display(float(new_pos))
        elif key == Qt.Key.Key_Up:
            tab.volume_slider.setValue(min(100, tab.volume_slider.value() + 5))
        elif key == Qt.Key.Key_Down:
            tab.volume_slider.setValue(max(0, tab.volume_slider.value() - 5))
        elif key == Qt.Key.Key_M:
            if tab.volume_slider.value() > 0:
                self.prev_volume = tab.volume_slider.value()
                tab.volume_slider.setValue(0)
            else:
                tab.volume_slider.setValue(getattr(self, 'prev_volume', 100))
        else:
            super().keyPressEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainApp()
    window.show()
    sys.exit(app.exec())