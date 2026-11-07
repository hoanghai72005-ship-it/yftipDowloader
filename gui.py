import os
import sys
import html
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLineEdit, QPushButton, QLabel, QProgressBar, QGroupBox, QSlider, QFrame, QComboBox,
                             QCheckBox, QTabWidget, QMessageBox, QListWidget, QListWidgetItem, QDialog, QRadioButton,
                             QButtonGroup)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon


AUDIO_CHOICE_FULL = "🎵 Âm thanh"
AUDIO_CHOICE_BEAT = "🎹 Beat"
AUDIO_CHOICE_VOCAL = "🎤 Giọng hát"


class JumpSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            val = int((event.position().x() / self.width()) * self.maximum())
            self.setValue(val)
            self.sliderMoved.emit(val)
        super().mousePressEvent(event)


class AspectRatioDialog(QDialog):
    def __init__(self, theme_color, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tùy chỉnh khung hình gộp Video")
        self.setFixedSize(250, 200)

        self.setStyleSheet(f"""
            QDialog {{ background-color: #f4f6f9; font-family: "Segoe UI", Arial; }}
            QLabel {{ font-size: 15px; font-weight: bold; color: #333; margin-bottom: 10px; }}
            QRadioButton {{ font-size: 14px; font-weight: bold; color: #444; padding: 5px; }}
            QRadioButton::indicator {{ width: 18px; height: 18px; }}
            QRadioButton::indicator:checked {{ background-color: {theme_color}; border: 2px solid #333; border-radius: 9px; }}
            QPushButton {{
                background-color: {theme_color};
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
                font-size: 14px;
                margin-top: 15px;
            }}
            QPushButton:hover {{ opacity: 0.8; }}
        """)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Chọn tỷ lệ khung hình chung:"))

        self.bg = QButtonGroup(self)

        self.rb_horizontal = QRadioButton("Ngang (16:9) - 1920x1080")
        self.rb_vertical = QRadioButton("Dọc (9:16) - 1080x1920")

        self.rb_horizontal.setChecked(True)

        self.bg.addButton(self.rb_horizontal, 1)
        self.bg.addButton(self.rb_vertical, 2)

        layout.addWidget(self.rb_horizontal)
        layout.addWidget(self.rb_vertical)

        self.btn_confirm = QPushButton("XÁC NHẬN")
        self.btn_confirm.clicked.connect(self.accept)
        layout.addWidget(self.btn_confirm)

    def get_resolution(self):
        if self.bg.checkedId() == 1:
            return 1920, 1080
        else:
            return 1080, 1920


def _create_sub_lang_combo() -> QComboBox:
    combo = QComboBox()
    combo.addItem("Việt + Anh", "auto")
    combo.addItem("🇻🇳 Tiếng Việt", "vi")
    combo.addItem("🇬🇧 Tiếng Anh", "en")
    combo.setToolTip("Chọn ngôn ngữ cho phụ đề (.srt)")
    return combo


def _create_sub_model_combo() -> QComboBox:
    combo = QComboBox()
    combo.addItem("Tiêu chuẩn", "standard")
    combo.addItem("Siêu chuẩn", "ultra")
    combo.setToolTip(
        "• Tiêu chuẩn: Giải mã bằng mô hình Medium ổn định (~70-80%).\n"
        "• Siêu chuẩn: Tách riêng Giọng hát + Large-v2 + Đối chiếu phụ đề nền tảng & chuẩn hóa câu (~90%+)."
    )
    return combo


class YouTubeTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QLabel { font-size: 14px; font-weight: bold; color: #333; font-family: "Segoe UI", Arial; }
            QLineEdit { padding: 8px; font-size: 14px; border: 1px solid #ccc; border-radius: 5px; }
            QPushButton { background-color: #e62117; color: white; font-weight: bold; padding: 8px; border-radius: 5px; font-size: 13px;}
            QPushButton:hover { background-color: #cc0000; }
            QPushButton:disabled { background-color: #f59a95; }
            QProgressBar { text-align: center; font-weight: bold; border: 1px solid #ccc; border-radius: 5px; height: 20px;}
            QProgressBar::chunk { background-color: #e62117; width: 10px; }
            QGroupBox { font-weight: bold; border: 1px solid #ccc; border-radius: 5px; margin-top: 10px; padding: 10px; font-size: 14px;}
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QSlider::groove:horizontal { border: 1px solid #bbb; background: white; height: 8px; border-radius: 4px; }
            QSlider::sub-page:horizontal { background: #e62117; border-radius: 4px; }
            QSlider::handle:horizontal { background: #cc0000; border: 1px solid #cc0000; width: 14px; margin-top: -3px; margin-bottom: -3px; border-radius: 7px; }
            QComboBox { padding: 5px; font-size: 13px; }
            QListWidget { font-weight: normal; font-size: 13px; color: #333; border: 1px solid #ccc; border-radius: 5px; padding: 5px;}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        top_layout = QHBoxLayout()

        left_group = QGroupBox("Thêm video và cấu hình")
        left_layout = QVBoxLayout()

        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("🔗 Dán link YouTube vào đây...")
        self.load_btn = QPushButton("Tải Preview")
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.load_btn)

        time_layout = QHBoxLayout()
        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("Từ (VD: 00:00)")
        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("Đến (VD: 01:30)")
        time_layout.addWidget(QLabel("Từ:"))
        time_layout.addWidget(self.start_input)
        time_layout.addWidget(QLabel("Đến:"))
        time_layout.addWidget(self.end_input)

        options_layout = QHBoxLayout()
        self.quality_combo = QComboBox()
        self.quality_combo.addItems([
            "1080p (FHD)",
            "2160p (4K)",
            "1440p (2K)",
            "720p (HD)",
            "480p (SD)",
            AUDIO_CHOICE_FULL,
            AUDIO_CHOICE_BEAT,
            AUDIO_CHOICE_VOCAL
        ])
        self.sub_checkbox = QCheckBox("Phụ đề (.srt)")
        self.sub_lang_combo = _create_sub_lang_combo()
        self.sub_model_combo = _create_sub_model_combo()
        options_layout.addWidget(self.quality_combo)
        options_layout.addWidget(self.sub_checkbox)
        options_layout.addWidget(self.sub_lang_combo)
        options_layout.addWidget(self.sub_model_combo)

        self.add_btn = QPushButton("Thêm Link vào danh sách")

        left_layout.addLayout(url_layout)
        left_layout.addLayout(time_layout)
        left_layout.addLayout(options_layout)
        left_layout.addWidget(self.add_btn)
        left_group.setLayout(left_layout)

        right_group = QGroupBox("Danh sách chờ tải")
        right_layout = QVBoxLayout()
        self.list_widget = QListWidget()
        self.remove_btn = QPushButton("Xóa link đã chọn")
        right_layout.addWidget(self.list_widget)
        right_layout.addWidget(self.remove_btn)
        right_group.setLayout(right_layout)

        top_layout.addWidget(left_group, stretch=6)
        top_layout.addWidget(right_group, stretch=4)
        main_layout.addLayout(top_layout)

        self.info_frame = QFrame()
        self.info_frame.setStyleSheet("""
            QFrame { background-color: #fafafa; border: 2px dashed #e62117; border-radius: 12px; }
            QLabel { border: none; background: transparent; }
        """)
        info_layout = QVBoxLayout(self.info_frame)
        title = QLabel("▶️ TẢI VIDEO YOUTUBE")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 900; color: #e62117; margin-top: 15px;")
        desc = QLabel(
            "<p style='line-height: 1.8;'>"
            "✔️ <b>Sẵn sàng tải:</b> Cấu hình Link, thời lượng và ấn thêm vào danh sách.<br>"
            "✔️ <b>Tự động tối ưu:</b> Hỗ trợ tải các đoạn video với độ phân giải cao.<br>"
            "✔️ <b>Phụ đề AI:</b> Nhận diện chuẩn xác từ luồng Vocal đã lọc nhạc nền."
            "</p>"
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        desc.setStyleSheet("font-size: 15px; color: #444;")
        info_layout.addStretch()
        info_layout.addWidget(title)
        info_layout.addWidget(desc)
        info_layout.addStretch()
        main_layout.addWidget(self.info_frame, stretch=1)

        self.preview_container = QWidget()
        preview_vlayout = QVBoxLayout(self.preview_container)
        preview_vlayout.setContentsMargins(0, 0, 0, 0)
        preview_vlayout.setSpacing(8)

        self.video_widget = QFrame()
        self.video_widget.setMinimumHeight(350)
        self.video_widget.setStyleSheet("background-color: black; border-radius: 5px;")
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        preview_vlayout.addWidget(self.video_widget, stretch=1)

        slider_layout = QHBoxLayout()
        self.time_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.time_slider.setRange(0, 0)
        self.time_slider.setDisabled(True)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setFixedWidth(100)
        self.time_label.setStyleSheet("font-family: monospace; font-size: 13px;")
        self.vol_label = QLabel("🔊")
        self.vol_label.setFixedWidth(20)
        self.volume_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(100)
        slider_layout.addWidget(self.time_slider)
        slider_layout.addWidget(self.time_label)
        slider_layout.addWidget(self.vol_label)
        slider_layout.addWidget(self.volume_slider)
        preview_vlayout.addLayout(slider_layout)

        main_layout.addWidget(self.preview_container, stretch=1)
        self.preview_container.hide()

        self.status_label = QLabel("Trạng thái: Sẵn sàng")
        self.status_label.setStyleSheet("color: #666; font-weight: normal;")
        main_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        self.download_btn = QPushButton("BẮT ĐẦU TẢI")
        self.download_btn.setFixedHeight(45)
        main_layout.addWidget(self.download_btn)

    def show_preview(self):
        self.info_frame.hide()
        self.preview_container.show()
        self.video_widget.show()

    def show_info(self):
        self.preview_container.hide()
        self.info_frame.show()


class FacebookTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QLabel { font-size: 14px; font-weight: bold; color: #333; font-family: "Segoe UI", Arial; }
            QLineEdit { padding: 8px; font-size: 14px; border: 1px solid #ccc; border-radius: 5px; }
            QLineEdit:focus { border: 2px solid #1877F2; }
            QPushButton { background-color: #1877F2; color: white; font-weight: bold; padding: 8px; border-radius: 5px; font-size: 13px;}
            QPushButton:hover { background-color: #165eab; }
            QPushButton:disabled { background-color: #8bb3e8; }
            QProgressBar { text-align: center; font-weight: bold; border: 1px solid #ccc; border-radius: 5px; height: 20px; }
            QProgressBar::chunk { background-color: #1877F2; border-radius: 4px; }
            QGroupBox { font-weight: bold; border: 1px solid #ccc; border-radius: 5px; margin-top: 10px; padding: 10px; font-size: 14px;}
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QSlider::groove:horizontal { border: 1px solid #bbb; background: white; height: 8px; border-radius: 4px; }
            QSlider::sub-page:horizontal { background: #1877F2; border-radius: 4px; }
            QSlider::handle:horizontal { background: #165eab; border: 1px solid #165eab; width: 14px; margin-top: -3px; margin-bottom: -3px; border-radius: 7px; }
            QComboBox { padding: 5px; font-size: 13px; }
            QListWidget { font-weight: normal; font-size: 13px; color: #333; border: 1px solid #ccc; border-radius: 5px; padding: 5px;}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        top_layout = QHBoxLayout()

        left_group = QGroupBox("Thêm video và cấu hình")
        left_layout = QVBoxLayout()

        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("🔗 Dán link Facebook vào đây...")
        self.load_btn = QPushButton("Tải Preview")
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.load_btn)

        time_layout = QHBoxLayout()
        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("Từ (VD: 00:00)")
        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("Đến (VD: 01:30)")
        time_layout.addWidget(QLabel("Từ:"))
        time_layout.addWidget(self.start_input)
        time_layout.addWidget(QLabel("Đến:"))
        time_layout.addWidget(self.end_input)

        options_layout = QHBoxLayout()
        self.quality_combo = QComboBox()
        self.quality_combo.addItems([
            "Tốt nhất",
            AUDIO_CHOICE_FULL,
            AUDIO_CHOICE_BEAT,
            AUDIO_CHOICE_VOCAL
        ])
        self.sub_checkbox = QCheckBox("Phụ đề (.srt)")
        self.sub_lang_combo = _create_sub_lang_combo()
        self.sub_model_combo = _create_sub_model_combo()
        options_layout.addWidget(self.quality_combo)
        options_layout.addWidget(self.sub_checkbox)
        options_layout.addWidget(self.sub_lang_combo)
        options_layout.addWidget(self.sub_model_combo)

        self.add_btn = QPushButton("Thêm Link vào danh sách")

        left_layout.addLayout(url_layout)
        left_layout.addLayout(time_layout)
        left_layout.addLayout(options_layout)
        left_layout.addWidget(self.add_btn)
        left_group.setLayout(left_layout)

        right_group = QGroupBox("Danh sách chờ tải")
        right_layout = QVBoxLayout()
        self.list_widget = QListWidget()
        self.remove_btn = QPushButton("Xóa link đã chọn")
        right_layout.addWidget(self.list_widget)
        right_layout.addWidget(self.remove_btn)
        right_group.setLayout(right_layout)

        top_layout.addWidget(left_group, stretch=6)
        top_layout.addWidget(right_group, stretch=4)
        main_layout.addLayout(top_layout)

        self.info_frame = QFrame()
        self.info_frame.setStyleSheet("""
            QFrame { background-color: #f0f2f5; border: 2px dashed #1877F2; border-radius: 12px; }
            QLabel { border: none; background: transparent; }
        """)
        info_layout = QVBoxLayout(self.info_frame)
        title = QLabel("📘 TẢI VIDEO/REEL FACEBOOK")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 900; color: #1877F2; margin-top: 15px;")
        desc = QLabel(
            "<p style='line-height: 1.8;'>"
            "✔️ <b>Hỗ trợ đa dạng:</b> Tải được Video từ bài viết, Facebook Reels và Facebook Watch.<br>"
            "✔️ <b>Tự động tối ưu:</b> Thuật toán tự động tìm và gộp luồng chất lượng cao.<br>"
            "✔️ <b>Tách Beat & Giọng hát:</b> Lưu trực tiếp Âm thanh gốc, Beat hoặc Giọng hát."
            "</p>"
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        desc.setStyleSheet("font-size: 15px; color: #444;")
        info_layout.addStretch()
        info_layout.addWidget(title)
        info_layout.addWidget(desc)
        info_layout.addStretch()
        main_layout.addWidget(self.info_frame, stretch=1)

        self.preview_container = QWidget()
        preview_vlayout = QVBoxLayout(self.preview_container)
        preview_vlayout.setContentsMargins(0, 0, 0, 0)
        preview_vlayout.setSpacing(8)

        self.video_widget = QFrame()
        self.video_widget.setMinimumHeight(350)
        self.video_widget.setStyleSheet("background-color: black; border-radius: 5px;")
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        preview_vlayout.addWidget(self.video_widget, stretch=1)

        slider_layout = QHBoxLayout()
        self.time_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.time_slider.setRange(0, 0)
        self.time_slider.setDisabled(True)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setFixedWidth(100)
        self.time_label.setStyleSheet("font-family: monospace; font-size: 13px;")
        self.vol_label = QLabel("🔊")
        self.vol_label.setFixedWidth(20)
        self.volume_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(100)
        slider_layout.addWidget(self.time_slider)
        slider_layout.addWidget(self.time_label)
        slider_layout.addWidget(self.vol_label)
        slider_layout.addWidget(self.volume_slider)
        preview_vlayout.addLayout(slider_layout)

        main_layout.addWidget(self.preview_container, stretch=1)
        self.preview_container.hide()

        self.status_label = QLabel("Trạng thái: Sẵn sàng")
        self.status_label.setStyleSheet("color: #666; font-weight: normal;")
        main_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        self.download_btn = QPushButton("BẮT ĐẦU TẢI")
        self.download_btn.setFixedHeight(45)
        main_layout.addWidget(self.download_btn)

    def show_preview(self):
        self.info_frame.hide()
        self.preview_container.show()
        self.video_widget.show()

    def show_info(self):
        self.preview_container.hide()
        self.info_frame.show()


class TikTokTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QLabel { font-size: 14px; font-weight: bold; color: #333; font-family: "Segoe UI", Arial;}
            QLineEdit { padding: 8px; font-size: 14px; border: 1px solid #ccc; border-radius: 5px; }
            QLineEdit:focus { border: 2px solid #000000; }
            QPushButton { background-color: #000000; color: white; font-weight: bold; padding: 8px; border-radius: 5px; font-size: 13px;}
            QPushButton:hover { background-color: #333333; }
            QPushButton:disabled { background-color: #888888; }
            QProgressBar { text-align: center; font-weight: bold; border: 1px solid #ccc; border-radius: 5px; height: 20px; color: white;}
            QProgressBar::chunk { background-color: #000000; border-radius: 4px; }
            QGroupBox { font-weight: bold; border: 1px solid #ccc; border-radius: 5px; margin-top: 10px; padding: 10px; font-size: 14px;}
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QSlider::groove:horizontal { border: 1px solid #bbb; background: white; height: 8px; border-radius: 4px; }
            QSlider::sub-page:horizontal { background: #000000; border-radius: 4px; }
            QSlider::handle:horizontal { background: #333333; border: 1px solid #333333; width: 14px; margin-top: -3px; margin-bottom: -3px; border-radius: 7px; }
            QComboBox { padding: 5px; font-size: 13px; }
            QListWidget { font-weight: normal; font-size: 13px; color: #333; border: 1px solid #ccc; border-radius: 5px; padding: 5px;}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        top_layout = QHBoxLayout()

        left_group = QGroupBox("Thêm video và cấu hình")
        left_layout = QVBoxLayout()

        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("🔗 Dán link TikTok vào đây...")
        self.load_btn = QPushButton("Tải Preview")
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.load_btn)

        time_layout = QHBoxLayout()
        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("Từ (VD: 00:00)")
        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("Đến (VD: 01:30)")
        time_layout.addWidget(QLabel("Từ:"))
        time_layout.addWidget(self.start_input)
        time_layout.addWidget(QLabel("Đến:"))
        time_layout.addWidget(self.end_input)

        options_layout = QHBoxLayout()
        self.quality_combo = QComboBox()
        self.quality_combo.addItems([
            "Tốt nhất",
            AUDIO_CHOICE_FULL,
            AUDIO_CHOICE_BEAT,
            AUDIO_CHOICE_VOCAL
        ])
        self.sub_checkbox = QCheckBox("Phụ đề (.srt)")
        self.sub_lang_combo = _create_sub_lang_combo()
        self.sub_model_combo = _create_sub_model_combo()
        options_layout.addWidget(self.quality_combo)
        options_layout.addWidget(self.sub_checkbox)
        options_layout.addWidget(self.sub_lang_combo)
        options_layout.addWidget(self.sub_model_combo)

        self.add_btn = QPushButton("Thêm Link vào danh sách")

        left_layout.addLayout(url_layout)
        left_layout.addLayout(time_layout)
        left_layout.addLayout(options_layout)
        left_layout.addWidget(self.add_btn)
        left_group.setLayout(left_layout)

        right_group = QGroupBox("Danh sách chờ tải")
        right_layout = QVBoxLayout()
        self.list_widget = QListWidget()
        self.remove_btn = QPushButton("Xóa link đã chọn")
        right_layout.addWidget(self.list_widget)
        right_layout.addWidget(self.remove_btn)
        right_group.setLayout(right_layout)

        top_layout.addWidget(left_group, stretch=6)
        top_layout.addWidget(right_group, stretch=4)
        main_layout.addLayout(top_layout)

        self.info_frame = QFrame()
        self.info_frame.setStyleSheet("""
            QFrame { background-color: #fafafa; border: 2px dashed #000000; border-radius: 12px; }
            QLabel { border: none; background: transparent; }
        """)
        info_layout = QVBoxLayout(self.info_frame)
        title = QLabel("🎵 TẢI VIDEO TIKTOK")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 900; color: #000000; margin-top: 15px;")
        desc = QLabel(
            "<p style='line-height: 1.8;'>"
            "✔️ <b>Xóa Watermark:</b> Tự động tìm kiếm luồng video gốc không có logo nền tảng.<br>"
            "✔️ <b>Tốc độ cao:</b> Trải nghiệm tải video trực tiếp với các tính năng tối ưu tốc độ cao.<br>"
            "✔️ <b>Đơn giản hóa:</b> Chỉ cần dán link, phần mềm sẽ tự định dạng chất lượng tốt nhất."
            "</p>"
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        desc.setStyleSheet("font-size: 15px; color: #444;")
        info_layout.addStretch()
        info_layout.addWidget(title)
        info_layout.addWidget(desc)
        info_layout.addStretch()
        main_layout.addWidget(self.info_frame, stretch=1)

        self.preview_container = QWidget()
        preview_vlayout = QVBoxLayout(self.preview_container)
        preview_vlayout.setContentsMargins(0, 0, 0, 0)
        preview_vlayout.setSpacing(8)

        self.video_widget = QFrame()
        self.video_widget.setMinimumHeight(350)
        self.video_widget.setStyleSheet("background-color: black; border-radius: 5px;")
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        preview_vlayout.addWidget(self.video_widget, stretch=1)

        slider_layout = QHBoxLayout()
        self.time_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.time_slider.setRange(0, 0)
        self.time_slider.setDisabled(True)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setFixedWidth(100)
        self.time_label.setStyleSheet("font-family: monospace; font-size: 13px;")
        self.vol_label = QLabel("🔊")
        self.vol_label.setFixedWidth(20)
        self.volume_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(100)
        slider_layout.addWidget(self.time_slider)
        slider_layout.addWidget(self.time_label)
        slider_layout.addWidget(self.vol_label)
        slider_layout.addWidget(self.volume_slider)
        preview_vlayout.addLayout(slider_layout)

        main_layout.addWidget(self.preview_container, stretch=1)
        self.preview_container.hide()

        self.status_label = QLabel("Trạng thái: Sẵn sàng")
        self.status_label.setStyleSheet("color: #666; font-weight: normal;")
        main_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        self.download_btn = QPushButton("BẮT ĐẦU TẢI")
        self.download_btn.setFixedHeight(45)
        main_layout.addWidget(self.download_btn)

    def show_preview(self):
        self.info_frame.hide()
        self.preview_container.show()
        self.video_widget.show()

    def show_info(self):
        self.preview_container.hide()
        self.info_frame.show()


class InstagramTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QLabel { font-size: 14px; font-weight: bold; color: #333; font-family: "Segoe UI", Arial;}
            QLineEdit { padding: 8px; font-size: 14px; border: 1px solid #ccc; border-radius: 5px; }
            QLineEdit:focus { border: 2px solid #833AB4; }
            QPushButton { background-color: #833AB4; color: white; font-weight: bold; padding: 8px; border-radius: 5px; font-size: 13px;}
            QPushButton:hover { background-color: #6a2e91; }
            QPushButton:disabled { background-color: #c89ce3; }
            QProgressBar { text-align: center; font-weight: bold; border: 1px solid #ccc; border-radius: 5px; height: 20px; color: white;}
            QProgressBar::chunk { background-color: #833AB4; border-radius: 4px; }
            QGroupBox { font-weight: bold; border: 1px solid #ccc; border-radius: 5px; margin-top: 10px; padding: 10px; font-size: 14px;}
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QSlider::groove:horizontal { border: 1px solid #bbb; background: white; height: 8px; border-radius: 4px; }
            QSlider::sub-page:horizontal { background: #833AB4; border-radius: 4px; }
            QSlider::handle:horizontal { background: #6a2e91; border: 1px solid #6a2e91; width: 14px; margin-top: -3px; margin-bottom: -3px; border-radius: 7px; }
            QComboBox { padding: 5px; font-size: 13px; }
            QListWidget { font-weight: normal; font-size: 13px; color: #333; border: 1px solid #ccc; border-radius: 5px; padding: 5px;}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        top_layout = QHBoxLayout()

        left_group = QGroupBox("Thêm video và cấu hình")
        left_layout = QVBoxLayout()

        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("🔗 Dán link Instagram vào đây...")
        self.load_btn = QPushButton("Tải Preview")
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.load_btn)

        time_layout = QHBoxLayout()
        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("Từ (VD: 00:00)")
        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("Đến (VD: 01:30)")
        time_layout.addWidget(QLabel("Từ:"))
        time_layout.addWidget(self.start_input)
        time_layout.addWidget(QLabel("Đến:"))
        time_layout.addWidget(self.end_input)

        options_layout = QHBoxLayout()
        self.quality_combo = QComboBox()
        self.quality_combo.addItems([
            "Tốt nhất",
            AUDIO_CHOICE_FULL,
            AUDIO_CHOICE_BEAT,
            AUDIO_CHOICE_VOCAL
        ])
        self.sub_checkbox = QCheckBox("Phụ đề (.srt)")
        self.sub_lang_combo = _create_sub_lang_combo()
        self.sub_model_combo = _create_sub_model_combo()
        options_layout.addWidget(self.quality_combo)
        options_layout.addWidget(self.sub_checkbox)
        options_layout.addWidget(self.sub_lang_combo)
        options_layout.addWidget(self.sub_model_combo)

        self.add_btn = QPushButton("Thêm Link vào danh sách")

        left_layout.addLayout(url_layout)
        left_layout.addLayout(time_layout)
        left_layout.addLayout(options_layout)
        left_layout.addWidget(self.add_btn)
        left_group.setLayout(left_layout)

        right_group = QGroupBox("Danh sách chờ tải")
        right_layout = QVBoxLayout()
        self.list_widget = QListWidget()
        self.remove_btn = QPushButton("Xóa link đã chọn")
        right_layout.addWidget(self.list_widget)
        right_layout.addWidget(self.remove_btn)
        right_group.setLayout(right_layout)

        top_layout.addWidget(left_group, stretch=6)
        top_layout.addWidget(right_group, stretch=4)
        main_layout.addLayout(top_layout)

        self.info_frame = QFrame()
        self.info_frame.setStyleSheet("""
            QFrame { background-color: #fafafa; border: 2px dashed #833AB4; border-radius: 12px; }
            QLabel { border: none; background: transparent; }
        """)
        info_layout = QVBoxLayout(self.info_frame)
        title = QLabel("📸 TẢI VIDEO INSTAGRAM")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 900; color: #833AB4; margin-top: 15px;")
        desc = QLabel(
            "<p style='line-height: 1.8;'>"
            "✔️ <b>Chất lượng cao:</b> Tải video Reels, Bài viết chuẩn chất lượng Full HD.<br>"
            "✔️ <b>Không yêu cầu đăng nhập:</b> Tải trực tiếp thông qua ứng dụng.<br>"
            "✔️ <b>Dễ dàng thực hiện:</b> Chỉ cần dán link, chọn và chờ đợi kết quả."
            "</p>"
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        desc.setStyleSheet("font-size: 15px; color: #444;")
        info_layout.addStretch()
        info_layout.addWidget(title)
        info_layout.addWidget(desc)
        info_layout.addStretch()
        main_layout.addWidget(self.info_frame, stretch=1)

        self.preview_container = QWidget()
        preview_vlayout = QVBoxLayout(self.preview_container)
        preview_vlayout.setContentsMargins(0, 0, 0, 0)
        preview_vlayout.setSpacing(8)

        self.video_widget = QFrame()
        self.video_widget.setMinimumHeight(350)
        self.video_widget.setStyleSheet("background-color: black; border-radius: 5px;")
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        preview_vlayout.addWidget(self.video_widget, stretch=1)

        slider_layout = QHBoxLayout()
        self.time_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.time_slider.setRange(0, 0)
        self.time_slider.setDisabled(True)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setFixedWidth(100)
        self.time_label.setStyleSheet("font-family: monospace; font-size: 13px;")
        self.vol_label = QLabel("🔊")
        self.vol_label.setFixedWidth(20)
        self.volume_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(100)
        slider_layout.addWidget(self.time_slider)
        slider_layout.addWidget(self.time_label)
        slider_layout.addWidget(self.vol_label)
        slider_layout.addWidget(self.volume_slider)
        preview_vlayout.addLayout(slider_layout)

        main_layout.addWidget(self.preview_container, stretch=1)
        self.preview_container.hide()

        self.status_label = QLabel("Trạng thái: Sẵn sàng")
        self.status_label.setStyleSheet("color: #666; font-weight: normal;")
        main_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        self.download_btn = QPushButton("BẮT ĐẦU TẢI")
        self.download_btn.setFixedHeight(45)
        main_layout.addWidget(self.download_btn)

    def show_preview(self):
        self.info_frame.hide()
        self.preview_container.show()
        self.video_widget.show()

    def show_info(self):
        self.preview_container.hide()
        self.info_frame.show()


class PinterestTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QLabel { font-size: 14px; font-weight: bold; color: #333; font-family: "Segoe UI", Arial;}
            QLineEdit { padding: 8px; font-size: 14px; border: 1px solid #ccc; border-radius: 5px; }
            QLineEdit:focus { border: 2px solid #E60023; }
            QPushButton { background-color: #E60023; color: white; font-weight: bold; padding: 8px; border-radius: 5px; font-size: 13px;}
            QPushButton:hover { background-color: #cc001f; }
            QPushButton:disabled { background-color: #f595a4; }
            QProgressBar { text-align: center; font-weight: bold; border: 1px solid #ccc; border-radius: 5px; height: 20px; color: white;}
            QProgressBar::chunk { background-color: #E60023; border-radius: 4px; }
            QGroupBox { font-weight: bold; border: 1px solid #ccc; border-radius: 5px; margin-top: 10px; padding: 10px; font-size: 14px;}
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QSlider::groove:horizontal { border: 1px solid #bbb; background: white; height: 8px; border-radius: 4px; }
            QSlider::sub-page:horizontal { background: #E60023; border-radius: 4px; }
            QSlider::handle:horizontal { background: #cc001f; border: 1px solid #cc001f; width: 14px; margin-top: -3px; margin-bottom: -3px; border-radius: 7px; }
            QComboBox { padding: 5px; font-size: 13px; }
            QListWidget { font-weight: normal; font-size: 13px; color: #333; border: 1px solid #ccc; border-radius: 5px; padding: 5px;}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        top_layout = QHBoxLayout()

        left_group = QGroupBox("Thêm video và cấu hình")
        left_layout = QVBoxLayout()

        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("🔗 Dán link Pinterest vào đây...")
        self.load_btn = QPushButton("Tải Preview")
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.load_btn)

        time_layout = QHBoxLayout()
        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("Từ (VD: 00:00)")
        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("Đến (VD: 01:30)")
        time_layout.addWidget(QLabel("Từ:"))
        time_layout.addWidget(self.start_input)
        time_layout.addWidget(QLabel("Đến:"))
        time_layout.addWidget(self.end_input)

        options_layout = QHBoxLayout()
        self.quality_combo = QComboBox()
        self.quality_combo.addItems([
            "Tốt nhất",
            AUDIO_CHOICE_FULL,
            AUDIO_CHOICE_BEAT,
            AUDIO_CHOICE_VOCAL
        ])
        self.sub_checkbox = QCheckBox("Phụ đề (.srt)")
        self.sub_lang_combo = _create_sub_lang_combo()
        self.sub_model_combo = _create_sub_model_combo()
        options_layout.addWidget(self.quality_combo)
        options_layout.addWidget(self.sub_checkbox)
        options_layout.addWidget(self.sub_lang_combo)
        options_layout.addWidget(self.sub_model_combo)

        self.add_btn = QPushButton("Thêm Link vào danh sách")

        left_layout.addLayout(url_layout)
        left_layout.addLayout(time_layout)
        left_layout.addLayout(options_layout)
        left_layout.addWidget(self.add_btn)
        left_group.setLayout(left_layout)

        right_group = QGroupBox("Danh sách chờ tải")
        right_layout = QVBoxLayout()
        self.list_widget = QListWidget()
        self.remove_btn = QPushButton("Xóa link đã chọn")
        right_layout.addWidget(self.list_widget)
        right_layout.addWidget(self.remove_btn)
        right_group.setLayout(right_layout)

        top_layout.addWidget(left_group, stretch=6)
        top_layout.addWidget(right_group, stretch=4)
        main_layout.addLayout(top_layout)

        self.info_frame = QFrame()
        self.info_frame.setStyleSheet("""
            QFrame { background-color: #fafafa; border: 2px dashed #E60023; border-radius: 12px; }
            QLabel { border: none; background: transparent; }
        """)
        info_layout = QVBoxLayout(self.info_frame)
        title = QLabel("📌 TẢI VIDEO PINTEREST")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 900; color: #E60023; margin-top: 15px;")
        desc = QLabel(
            "<p style='line-height: 1.8;'>"
            "✔️ <b>Lưu trữ sáng tạo:</b> Tải mọi video ý tưởng nhanh chóng.<br>"
            "✔️ <b>Tốc độ tối đa:</b> Hệ thống tối ưu đảm bảo về tốc độ tải.<br>"
            "✔️ <b>Tối ưu không gian:</b> Tối ưu bộ nhớ trong quá trình tải về."
            "</p>"
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        desc.setStyleSheet("font-size: 15px; color: #444;")
        info_layout.addStretch()
        info_layout.addWidget(title)
        info_layout.addWidget(desc)
        info_layout.addStretch()
        main_layout.addWidget(self.info_frame, stretch=1)

        self.preview_container = QWidget()
        preview_vlayout = QVBoxLayout(self.preview_container)
        preview_vlayout.setContentsMargins(0, 0, 0, 0)
        preview_vlayout.setSpacing(8)

        self.video_widget = QFrame()
        self.video_widget.setMinimumHeight(350)
        self.video_widget.setStyleSheet("background-color: black; border-radius: 5px;")
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        preview_vlayout.addWidget(self.video_widget, stretch=1)

        slider_layout = QHBoxLayout()
        self.time_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.time_slider.setRange(0, 0)
        self.time_slider.setDisabled(True)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setFixedWidth(100)
        self.time_label.setStyleSheet("font-family: monospace; font-size: 13px;")
        self.vol_label = QLabel("🔊")
        self.vol_label.setFixedWidth(20)
        self.volume_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(100)
        slider_layout.addWidget(self.time_slider)
        slider_layout.addWidget(self.time_label)
        slider_layout.addWidget(self.vol_label)
        slider_layout.addWidget(self.volume_slider)
        preview_vlayout.addLayout(slider_layout)

        main_layout.addWidget(self.preview_container, stretch=1)
        self.preview_container.hide()

        self.status_label = QLabel("Trạng thái: Sẵn sàng")
        self.status_label.setStyleSheet("color: #666; font-weight: normal;")
        main_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        self.download_btn = QPushButton("BẮT ĐẦU TẢI")
        self.download_btn.setFixedHeight(45)
        main_layout.addWidget(self.download_btn)

    def show_preview(self):
        self.info_frame.hide()
        self.preview_container.show()
        self.video_widget.show()

    def show_info(self):
        self.preview_container.hide()
        self.info_frame.show()


class PlaylistTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QWidget {
                background-color: #f8f9fa;
                color: #111111;
                font-family: "Segoe UI", Arial, sans-serif;
            }
            QGroupBox {
                background-color: #ffffff;
                border: 1.5px solid #111111;
                border-radius: 10px;
                margin-top: 12px;
                padding: 14px;
                font-size: 14px;
                font-weight: bold;
                color: #111111;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 8px;
                background-color: #ffffff;
                color: #111111;
            }
            QLabel {
                font-size: 13px;
                font-weight: 600;
                color: #111111;
                background-color: transparent;
            }
            QPushButton {
                background-color: #ffffff;
                color: #111111;
                border: 1.5px solid #111111;
                font-weight: 700;
                padding: 8px 16px;
                border-radius: 7px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #f1f3f5;
            }
            QPushButton:pressed {
                background-color: #e2e6ea;
            }
            QPushButton:disabled {
                color: #adb5bd;
                border: 1.5px solid #dee2e6;
                background-color: #f8f9fa;
            }
            QSlider::groove:horizontal {
                border: 1px solid #111111;
                background: #e9ecef;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #111111;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 2px solid #111111;
                width: 14px;
                height: 14px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #111111;
            }
            QListWidget {
                font-weight: 500;
                font-size: 13.5px;
                color: #111111;
                border: 1px solid #ced4da;
                border-radius: 8px;
                padding: 6px;
                background-color: #ffffff;
                outline: none;
            }
            QListWidget::item {
                padding: 10px 12px;
                margin-bottom: 4px;
                border: 1px solid #f1f3f5;
                border-radius: 6px;
                background-color: #ffffff;
                color: #111111;
            }
            QListWidget::item:hover {
                background-color: #f8f9fa;
                border: 1px solid #adb5bd;
            }
            QListWidget::item:selected {
                background-color: #f1f3f5;
                color: #000000;
                font-weight: 700;
                border: 1.5px solid #111111;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(14, 8, 14, 12)

        playlist_group = QGroupBox("🎵 THƯ VIỆN PLAYLIST ÂM THANH")
        playlist_layout = QVBoxLayout()
        playlist_layout.setSpacing(8)

        top_bar = QHBoxLayout()
        self.count_label = QLabel("Tổng số bài: 0")
        self.count_label.setStyleSheet("""
            background-color: #ffffff;
            color: #111111;
            border: 1.5px solid #111111;
            border-radius: 14px;
            padding: 5px 14px;
            font-size: 12.5px;
            font-weight: 700;
        """)

        self.add_files_btn = QPushButton("＋ Thêm nhạc từ máy")
        self.refresh_btn = QPushButton("↻ Quét lại thư mục")
        self.remove_track_btn = QPushButton("✕ Xóa bài đã chọn")

        top_bar.addWidget(self.count_label)
        top_bar.addStretch()
        top_bar.addWidget(self.add_files_btn)
        top_bar.addWidget(self.refresh_btn)
        top_bar.addWidget(self.remove_track_btn)

        self.playlist_widget = QListWidget()

        playlist_layout.addLayout(top_bar)
        playlist_layout.addWidget(self.playlist_widget, stretch=1)
        playlist_group.setLayout(playlist_layout)
        main_layout.addWidget(playlist_group, stretch=5)

        player_group = QGroupBox("🎧 BẢNG ĐIỀU KHIỂN PHÁT NHẠC")
        player_layout = QVBoxLayout()
        player_layout.setSpacing(10)

        self.now_playing_card = QFrame()
        self.now_playing_card.setMinimumHeight(140)
        self.now_playing_card.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #111111;
                border-radius: 8px;
                padding: 8px 16px;
            }
        """)
        np_layout = QVBoxLayout(self.now_playing_card)
        np_layout.setContentsMargins(6, 4, 6, 4)

        self.now_playing_label = QLabel("💿 Chưa phát bài nào — Nhấp đúp vào bài hát trong danh sách hoặc nhấn Phát")
        self.now_playing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.now_playing_label.setWordWrap(True)
        self.now_playing_label.setTextFormat(Qt.TextFormat.RichText)
        self.now_playing_label.setStyleSheet("border: none; font-size: 14.5px; font-weight: 700; color: #000000;")
        np_layout.addWidget(self.now_playing_label)
        player_layout.addWidget(self.now_playing_card)

        slider_layout = QHBoxLayout()
        slider_layout.setSpacing(10)
        self.time_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.time_slider.setRange(0, 0)
        self.time_slider.setDisabled(True)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setFixedWidth(105)
        self.time_label.setStyleSheet("font-family: Consolas, monospace; font-size: 13px; font-weight: bold; color: #111111;")

        self.vol_label = QLabel("🔊")
        self.vol_label.setFixedWidth(22)
        self.volume_slider = JumpSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(110)

        slider_layout.addWidget(self.time_slider, stretch=1)
        slider_layout.addWidget(self.time_label)
        slider_layout.addWidget(self.vol_label)
        slider_layout.addWidget(self.volume_slider)
        player_layout.addLayout(slider_layout)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)

        self.prev_btn = QPushButton("⏮ Bài trước")
        self.play_pause_btn = QPushButton("▶ Phát")
        self.play_pause_btn.setMinimumWidth(135)
        self.play_pause_btn.setFixedHeight(38)
        self.next_btn = QPushButton("⏭ Bài tiếp")

        self.loop_btn = QPushButton("🔂 Lặp 1 bài: Tắt")
        self.mode_btn = QPushButton("🔁 Chế độ: Theo thứ tự")

        for b in [self.prev_btn, self.next_btn, self.loop_btn, self.mode_btn]:
            b.setFixedHeight(38)

        controls_layout.addWidget(self.prev_btn)
        controls_layout.addWidget(self.play_pause_btn)
        controls_layout.addWidget(self.next_btn)
        controls_layout.addStretch()
        controls_layout.addWidget(self.loop_btn)
        controls_layout.addWidget(self.mode_btn)

        player_layout.addLayout(controls_layout)
        player_group.setLayout(player_layout)
        main_layout.addWidget(player_group, stretch=4)

        bottom_info_layout = QHBoxLayout()
        self.status_label = QLabel("Trạng thái: Sẵn sàng phát nhạc")
        self.status_label.setStyleSheet("color: #222222; font-weight: 500; font-size: 12.5px;")

        shortcut_hint = QLabel("Phím tắt: [Space] Phát/Dừng  •  [←/→] Tua 5s  •  [↑/↓] Âm lượng  •  [M] Tắt tiếng")
        shortcut_hint.setStyleSheet("color: #555555; font-weight: normal; font-size: 12px;")

        bottom_info_layout.addWidget(self.status_label)
        bottom_info_layout.addStretch()
        bottom_info_layout.addWidget(shortcut_hint)
        main_layout.addLayout(bottom_info_layout)

    def set_track_title_fallback(self, title_text: str):
        safe_title = html.escape(title_text)
        self.now_playing_label.setText(
            f"<div style='text-align: center; font-size: 15px; font-weight: 700; color: #111111;'>"
            f"🎶 Đang phát: {safe_title}"
            f"</div>"
        )

    def render_scrolling_lyrics(self, lines_window: list):
        html_rows = []
        for rel_pos, text in lines_window:
            safe_line = html.escape(text) if text else "&nbsp;"
            if rel_pos == 0:
                html_rows.append(
                    f"<div style='font-size: 17px; font-weight: 800; color: #000000; margin: 5px 0;'>"
                    f"{safe_line}</div>"
                )
            elif abs(rel_pos) == 1:
                html_rows.append(
                    f"<div style='font-size: 13.5px; font-weight: 500; color: #6c757d; margin: 3px 0;'>"
                    f"{safe_line}</div>"
                )
            else:
                html_rows.append(
                    f"<div style='font-size: 12.5px; font-weight: 400; color: #adb5bd; margin: 2px 0;'>"
                    f"{safe_line}</div>"
                )

        full_html = "<div style='text-align: center; line-height: 1.35;'>" + "".join(html_rows) + "</div>"
        self.now_playing_label.setText(full_html)


class ModernUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("yftipDownloader")
        self.resize(940, 780)
        base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(
            os.path.abspath(__file__))
        icon_path = os.path.join(base_dir, 'ic', 'logo.ico')

        self.setWindowIcon(QIcon(icon_path))

        self.setStyleSheet("""
            QMainWindow { background-color: #f4f6f9; }
            QMessageBox { background-color: #f4f6f9; font-family: "Segoe UI", Arial, sans-serif; }
            QMessageBox QLabel { font-weight: bold; font-size: 14px; color: #333; font-family: "Segoe UI", Arial, sans-serif; }
            QMessageBox QPushButton {
                background-color: #FFD700;
                color: #000000;
                font-weight: bold;
                padding: 8px 25px;
                border-radius: 5px;
                font-size: 14px;
                font-family: "Segoe UI", Arial, sans-serif;
            }
            QMessageBox QPushButton:hover { background-color: #e6c200; }
        """)

        self.tabs = QTabWidget()
        self.tabs.setIconSize(QSize(24, 24))
        self.tabs.setStyleSheet("""
            QTabBar::tab { font-size: 14px; font-weight: bold; padding: 10px 18px; margin-right: 2px; font-family: "Segoe UI", Arial; }
            QTabBar::tab:selected { background-color: #e0e0e0; border-top: 3px solid #007bff; }
        """)

        self.setCentralWidget(self.tabs)

        self.youtube_tab = YouTubeTab()
        self.facebook_tab = FacebookTab()
        self.tiktok_tab = TikTokTab()
        self.instagram_tab = InstagramTab()
        self.pinterest_tab = PinterestTab()
        self.playlist_tab = PlaylistTab()

        self.tabs.addTab(self.youtube_tab, QIcon(os.path.join(base_dir, "ic", "youtube.png")), "YouTube")
        self.tabs.addTab(self.facebook_tab, QIcon(os.path.join(base_dir, "ic", "facebook.png")), "Facebook")
        self.tabs.addTab(self.tiktok_tab, QIcon(os.path.join(base_dir, "ic", "tik-tok.png")), "TikTok")
        self.tabs.addTab(self.instagram_tab, QIcon(os.path.join(base_dir, "ic", "instagram.png")), "Instagram")
        self.tabs.addTab(self.pinterest_tab, QIcon(os.path.join(base_dir, "ic", "pinterest.png")), "Pinterest")
        self.tabs.addTab(self.playlist_tab, "🎧 Playlist Nhạc")

        self.url_input = self.youtube_tab.url_input
        self.load_btn = self.youtube_tab.load_btn
        self.video_widget = self.youtube_tab.video_widget
        self.time_slider = self.youtube_tab.time_slider
        self.time_label = self.youtube_tab.time_label
        self.volume_slider = self.youtube_tab.volume_slider
        self.quality_combo = self.youtube_tab.quality_combo
        self.sub_checkbox = self.youtube_tab.sub_checkbox
        self.start_input = self.youtube_tab.start_input
        self.end_input = self.youtube_tab.end_input
        self.status_label = self.youtube_tab.status_label
        self.progress_bar = self.youtube_tab.progress_bar
        self.download_btn = self.youtube_tab.download_btn