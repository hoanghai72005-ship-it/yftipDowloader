# 🎬 yftipDownloader — Tải Video Đa Nền Tảng, Tách Nhạc AI & Tạo Phụ Đề Tự Động

**yftipDownloader** là ứng dụng Desktop GUI xây dựng bằng Python và PyQt6, hỗ trợ tải video/audio từ **YouTube**, **Facebook**, **TikTok**, **Instagram**, **Pinterest**, tách nhạc Beat/Vocal bằng AI, tự động tạo phụ đề `.srt` và phát nhạc kèm lời bài hát (Lyrics) theo thời gian thực.

## ✨ Tính năng nổi bật

* **Tải Video & Âm thanh đa nền tảng** (YouTube, Facebook, TikTok No Watermark, Instagram, Pinterest)
* **Xem trước trực tiếp (Live Preview)** ngay trên ứng dụng
* **Cắt & Gộp nhiều đoạn video** theo mốc thời gian tùy chọn (chuẩn hóa khung hình 16:9 hoặc 9:16)
* **Tách Nhạc Beat & Giọng Hát (AI Stem Separation & DSP)** 
* **Tạo Phụ Đề AI (`.srt`) tự động** (Việt / Anh) 
* **Trình Phát Nhạc Playlist & Hiển thị Lyrics Karaoke chạy theo thời gian thực**

## 📂 Cấu trúc thư mục dự án

Đảm bảo giữ nguyên cấu trúc thư mục như dưới đây để ứng dụng nạp đúng thư viện động và công cụ xử lý:

| Đường dẫn file / thư mục | Mô tả vai trò trong hệ thống |
| :--- | :--- |
| [`main.py`](https://github.com/hoanghai72005-ship-it/yftipDowloader/blob/main/main.py) | Điểm khởi chạy chính (`MainApp`), quản lý luồng tải đa nền tảng (`QThread`), điều khiển trình phát MPV và logic Playlist |
| [`gui.py`](https://github.com/hoanghai72005-ship-it/yftipDowloader/blob/main/gui.py) | Giao diện người dùng `ModernUI` ([PyQt6](https://pypi.org/project/PyQt6/)), định nghĩa 6 tab chức năng, thanh trượt `JumpSlider` và hộp thoại chọn tỷ lệ khung hình |
| [`ai_sub.py`](https://github.com/hoanghai72005-ship-it/yftipDowloader/blob/main/ai_sub.py) | Engine nhận diện giọng nói AI ([Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) / [OpenAI Whisper](https://github.com/openai/whisper)), tách nhạc [Demucs](https://github.com/facebookresearch/demucs) / DSP và căn chỉnh phụ đề `.srt` |
| [`sub_rules.py`](https://github.com/hoanghai72005-ship-it/yftipDowloader/blob/main/sub_rules.py) | Từ điển quy tắc lọc câu rác (hallucination), từ nối bị treo cuối câu và bộ sửa lỗi cụm từ đồng âm tiếng Việt |
| mpv-1.dll | Thư viện liên kết động `libmpv` cho Windows để nhúng trình phát video/audio trực tiếp vào giao diện |
| [`bin/`](https://github.com/hoanghai72005-ship-it/yftipDowloader/tree/main/bin) | Chứa bộ công cụ ffmpeg.exe, ffplay.exe và ffprobe.exe dùng để cắt, gộp, chuyển đổi định dạng và lọc âm thanh |
| [`ic/`](https://github.com/hoanghai72005-ship-it/yftipDowloader/tree/main/ic) | Chứa icon ứng dụng logo.ico và biểu tượng các nền tảng youtube.png, facebook.png, tik-tok.png, instagram.png, pinterest.png |
| `music/` | Thư mục tự động khởi tạo khi chạy app để lưu các file âm thanh (`.mp3`), phụ đề (`.srt`) và cấu hình `playlist.json` |

## ⚙️ Yêu cầu hệ thống

* **Hệ điều hành**: Windows 10 / Windows 11 (64-bit) — được tối ưu sẵn với mpv-1.dll và bộ thực thi bin/ffmpeg.exe đi kèm trong thư mục dự án.
* **Python**: Phiên bản **Python 3.10 – 3.12** (64-bit).
* **Phần cứng khuyến nghị**:
  * **CPU**: Đa nhân (ứng dụng tự động tối ưu số luồng `int8` trên CPU qua [CTranslate2](https://github.com/opennmt/ctranslate2) nếu không có card đồ họa rời).
  * **GPU (Tùy chọn)**: Card đồ họa NVIDIA hỗ trợ CUDA 12 (`cublas64_12.dll` / `cudnn`) để tăng tốc giải mã Whisper `float16` và tách nhạc bằng [Demucs](https://github.com/facebookresearch/demucs).
* **Kết nối mạng**: Cần Internet để tải video/audio, tra cứu lời bài hát và tải trọng số mô hình AI trong lần chạy đầu tiên.

## 🚀 Hướng dẫn cài đặt và chạy ứng dụng

### Bước 1: Tải mã nguồn và tài nguyên
1. Tải toàn bộ thư mục về máy.
2. Giải nén (nếu tải dưới dạng `.zip`) và kiểm tra chắc chắn rằng file mpv-1.dll nằm cùng cấp với main.py, đồng thời bên trong thư mục bin/ có đầy đủ `ffmpeg.exe`, `ffplay.exe`, `ffprobe.exe`.

### Bước 2: Cài đặt các thư viện bắt buộc
Cài đặt các gói thư viện cốt lõi để chạy giao diện ([PyQt6](https://pypi.org/project/PyQt6/)), trình phát ([python-mpv](https://pypi.org/project/python-mpv/)), trình tải ([yt-dlp](https://github.com/yt-dlp/yt-dlp)), kết nối HTTP ([Requests](https://pypi.org/project/requests/)) và nhận diện phụ đề AI ([Faster-Whisper](https://github.com/SYSTRAN/faster-whisper)):

```bash
pip install PyQt6 python-mpv yt-dlp requests faster-whisper ctranslate2
```

### Bước 3: Cài đặt thư viện nâng cao (Tùy chọn)
* **Tách nhạc Beat/Vocal chất lượng cao bằng AI ([Demucs](https://github.com/facebookresearch/demucs))**:
  Nếu muốn tách giọng hát và nhạc nền bằng mạng nơ-ron `htdemucs` (thay vì bộ lọc tần số FFmpeg DSP mặc định), hãy cài thêm:
  ```bash
  pip install demucs
  ```
* **Tăng tốc GPU NVIDIA (CUDA 12)**:
  Nếu máy có GPU NVIDIA, bạn có thể cài đặt các gói runtime CUDA cho [CTranslate2](https://github.com/opennmt/ctranslate2) (ứng dụng sẽ tự động nhận diện thư mục `nvidia/cublas/bin` và `nvidia/cudnn/bin`):
  ```bash
  pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
  ```
* **Cấu hình Gemini API để hiệu đính phụ đề thông minh (Tùy chọn)**:
  Nếu muốn kích hoạt bước đánh giá ngữ nghĩa cuối cùng bằng [Gemini 2.5 Flash](https://aistudio.google.com/docs/models/gemini-2.5-flash), thiết lập biến môi trường trước khi chạy:
  ```powershell
  # Trên PowerShell:
  $env:GEMINI_API_KEY="AIzaSy_YOUR_API_KEY_HERE"

  # Trên CMD:
  set GEMINI_API_KEY=AIzaSy_YOUR_API_KEY_HERE
  ```

### Bước 4: Khởi chạy ứng dụng
Sau khi hoàn tất cài đặt, chạy lệnh sau để mở giao diện **yftipDownloader**:

```bash
python main.py
```

## 💡 Hướng dẫn sử dụng nhanh

### 1. Tải Video / Tách Nhạc & Tạo Phụ Đề
1. Chọn tab nền tảng tương ứng (**YouTube**, **Facebook**, **TikTok**, **Instagram**, hoặc **Pinterest**).
2. Dán đường dẫn video vào ô nhập link:
   * Nhấn **Tải Preview** nếu muốn xem trước nội dung và xác định mốc thời gian cần cắt.
   * Nhập thời gian bắt đầu (`Từ`, ví dụ `00:10`) và kết thúc (`Đến`, ví dụ `01:45`) nếu chỉ muốn cắt một đoạn. Bỏ trống nếu muốn tải toàn bộ video.
3. Chọn chế độ xuất ở hộp chọn chất lượng:
   * Chọn độ phân giải (`1080p`, `4K`, `Tốt nhất`...) để tải file video `.mp4` (lưu tại thư mục gốc đang chạy ứng dụng).
   * Chọn `🎵 Âm thanh`, `🎹 Beat`, hoặc `🎤 Giọng hát` để trích xuất file `.mp3` (tự động lưu vào thư mục `music/` và thêm vào Playlist).
4. Nếu cần tạo phụ đề `.srt`, đánh dấu vào ô **Phụ đề (.srt)**, chọn ngôn ngữ (`Việt + Anh`, `Tiếng Việt`, `Tiếng Anh`) và cấp độ mô hình (`Tiêu chuẩn` hoặc `Siêu chuẩn`).
5. Nhấn **Thêm Link vào danh sách** (có thể thêm nhiều link để tải và gộp nối tiếp), sau đó nhấn nút **BẮT ĐẦU TẢI**.

### 2. Nghe Nhạc & Xem Lyrics trên tab Playlist
1. Chuyển sang tab **🎧 Playlist Nhạc**.
2. Nhấp đúp vào một bài hát trong danh sách hoặc chọn bài và nhấn **▶ Phát**.
3. Nếu bài hát có file phụ đề `.srt` tương ứng trong thư mục `music/`, khung điều khiển sẽ tự động hiển thị lời bài hát cuộn 5 dòng theo giai điệu.

### 3. Phím tắt điều khiển nhanh
Khi đang xem Preview hoặc nghe nhạc trong tab Playlist, bạn có thể dùng các phím tắt sau:

| Phím tắt | Chức năng điều khiển |
| :--- | :--- |
| `Space` | Phát / Tạm dừng (Play / Pause) |
| `←` / `→` | Tua lùi / Tua tiến 5 giây |
| `↑` / `↓` | Tăng / Giảm âm lượng 5% |
| `M` | Tắt tiếng / Bật lại âm lượng trước đó (Mute / Unmute) |

## 🛠️ Xử lý sự cố thường gặp (Troubleshooting)

* **Lỗi `OSError: Cannot find libmpv` hoặc không mở được giao diện**:
  Kiểm tra xem file mpv-1.dll đã nằm đúng trong cùng thư mục với main.py chưa, và đảm bảo bạn đang dùng Python 64-bit.
* **Thông báo `LỖI: Không tìm thấy thư mục FFmpeg!`**:
  Đảm bảo thư mục bin/ nằm cùng cấp với main.py và bên trong có file ffmpeg.exe.
* **Tải phụ đề lần đầu mất nhiều thời gian ở mức 15%**:
  Trong lần đầu tiên sử dụng tính năng tạo phụ đề AI, [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) sẽ tự động tải mô hình `medium` (~1.5 GB) hoặc `large-v2` (~3 GB) từ Hugging Face về bộ nhớ đệm của máy. Các lần chạy tiếp theo sẽ nạp trực tiếp từ ổ cứng và diễn ra nhanh chóng.
* **Không tải được một số video YouTube mới**:
  Cập nhật thư viện [yt-dlp](https://github.com/yt-dlp/yt-dlp) lên bản mới nhất bằng lệnh `pip install -U yt-dlp`.