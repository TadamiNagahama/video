import sys
import time
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap, QTransform, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QSlider, QComboBox)
from player import Video


def clock(value):
    minutes, seconds = divmod(max(0, value), 60)
    return f'{int(minutes):02d}:{seconds:06.3f}'


class Panel(QWidget):
    failed = Signal(str)

    def __init__(self, title):
        super().__init__()
        self.video = None
        self.playing = False
        self.speed = 1.0
        self.pixmap = None
        layout = QVBoxLayout(self)
        self.title = QLabel(title)
        layout.addWidget(self.title)
        self.screen = QLabel('MOV ファイルを開いてください')
        self.screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen.setMinimumSize(280, 200)
        self.screen.setStyleSheet('background:#111;color:#ddd')
        layout.addWidget(self.screen, 1)
        self.time = QLabel('00:00.000 / 00:00.000')
        layout.addWidget(self.time)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.sliderPressed.connect(self.pause)
        self.slider.sliderReleased.connect(self.seek_slider)
        layout.addWidget(self.slider)
        buttons = QHBoxLayout()
        for label, action in [('開く', self.open), ('◀ 1コマ', lambda: self.step(-1)),
                              ('再生 / 停止', self.toggle), ('1コマ ▶', lambda: self.step(1))]:
            button = QPushButton(label)
            button.clicked.connect(action)
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def open(self):
        path, _ = QFileDialog.getOpenFileName(self, '動画を選択', '',
                                             '動画 (*.mov *.MOV *.mp4 *.MP4 *.m4v);;すべて (*)')
        if not path:
            return
        self.pause()
        try:
            video = Video(path)
            if self.video:
                self.video.close()
            self.video = video
            self.title.setText(Path(path).name)
            self.render()
        except Exception as exc:
            self.failed.emit(f'動画を開けませんでした。\n{exc}')

    def render(self):
        frame = self.video.current.to_ndarray(format='rgb24')
        height, width, _ = frame.shape
        img = QImage(frame.data, width, height, frame.strides[0], QImage.Format.Format_RGB888).copy()
        self.pixmap = QPixmap.fromImage(img).transformed(QTransform().rotate(self.video.rotation))
        self.fit()
        self.time.setText(f'{clock(self.video.position)} / {clock(self.video.duration)}')
        if not self.slider.isSliderDown():
            self.slider.setValue(int(self.video.position / max(self.video.duration, .001) * 10000))

    def fit(self):
        if self.pixmap:
            self.screen.setPixmap(self.pixmap.scaled(self.screen.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        self.fit()
        super().resizeEvent(event)

    def pause(self):
        self.playing = False

    def play(self, now=None):
        if self.video:
            self.anchor = self.video.position
            self.started = time.monotonic() if now is None else now
            self.playing = True

    def toggle(self):
        self.pause() if self.playing else self.play()

    def step(self, direction):
        self.pause()
        if self.video:
            try:
                self.video.next() if direction > 0 else self.video.previous()
                self.render()
            except Exception as exc:
                self.failed.emit(str(exc))

    def seek_slider(self):
        if self.video:
            try:
                self.video.seek(self.slider.value() / 10000 * self.video.duration)
                self.render()
            except Exception as exc:
                self.failed.emit(str(exc))

    def tick(self, now):
        if self.video and self.playing:
            try:
                changed, ended = self.video.advance(self.anchor + (now - self.started) * self.speed)
                if changed:
                    self.render()
                if ended:
                    self.pause()
            except Exception as exc:
                self.pause()
                self.failed.emit(str(exc))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('動画くらべ — 2画面プレーヤー')
        self.resize(1200, 720)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        tools = QHBoxLayout()
        for text, action in [('両方 再生', self.play_all), ('両方 停止', self.pause_all),
                             ('両方 ◀ 1コマ', lambda: self.step_all(-1)),
                             ('両方 1コマ ▶', lambda: self.step_all(1)),
                             ('両方 先頭へ', self.rewind)]:
            button = QPushButton(text)
            button.clicked.connect(action)
            tools.addWidget(button)
        tools.addWidget(QLabel('速度'))
        speed = QComboBox()
        speed.addItems(['0.25×', '0.5×', '1×', '2×'])
        speed.setCurrentIndex(2)
        speed.currentIndexChanged.connect(self.set_speed)
        tools.addWidget(speed)
        layout.addLayout(tools)
        row = QHBoxLayout()
        self.panels = [Panel('左の動画'), Panel('右の動画')]
        for panel in self.panels:
            panel.failed.connect(lambda message: QMessageBox.warning(self, '動画エラー', message))
            row.addWidget(panel, 1)
        layout.addLayout(row, 1)
        layout.addWidget(QLabel('Space: 両方の再生/停止  |  ← / →: 両方のコマ戻し/送り  |  音声は再生しません'))
        for key, action in [('Space', self.toggle_all), ('Left', lambda: self.step_all(-1)),
                             ('Right', lambda: self.step_all(1))]:
            QShortcut(QKeySequence(key), self, activated=action)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(10)

    def tick(self):
        now = time.monotonic()
        for panel in self.panels:
            panel.tick(now)

    def play_all(self):
        now = time.monotonic()
        for panel in self.panels:
            panel.play(now)

    def pause_all(self):
        for panel in self.panels:
            panel.pause()

    def toggle_all(self):
        self.pause_all() if any(p.playing for p in self.panels) else self.play_all()

    def step_all(self, direction):
        for panel in self.panels:
            panel.step(direction)

    def rewind(self):
        self.pause_all()
        for panel in self.panels:
            if panel.video:
                try:
                    panel.video.seek(0)
                    panel.render()
                except Exception as exc:
                    panel.failed.emit(str(exc))

    def set_speed(self, index):
        for panel in self.panels:
            panel.speed = [.25, .5, 1, 2][index]
            if panel.playing:
                panel.play()

    def closeEvent(self, event):
        for panel in self.panels:
            if panel.video:
                panel.video.close()
        super().closeEvent(event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = Window()
    window.show()
    sys.exit(app.exec())
