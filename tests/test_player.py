import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import subprocess
import pytest
from player import Video


@pytest.fixture(scope='session', autouse=True)
def qt_app():
    from PySide6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([])
    yield application
    import gc
    gc.collect()
    application.processEvents()


@pytest.fixture(scope='module')
def movie(tmp_path_factory):
    path = tmp_path_factory.mktemp('media') / 'test.mov'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=160x120:rate=30:duration=2', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', str(path)], check=True)
    return path


def test_frame_steps_and_seek(movie):
    video = Video(movie)
    try:
        assert video.position == pytest.approx(0)
        assert not video.previous()
        for _ in range(7):
            assert video.next()
        assert video.position == pytest.approx(7 / 30)
        assert video.previous()
        assert video.position == pytest.approx(6 / 30)
        assert video.next()
        assert video.position == pytest.approx(7 / 30)
        video.seek(1)
        assert video.position == pytest.approx(1)
        changed, ended = video.advance(1.5)
        assert changed and not ended
        assert video.position == pytest.approx(1.5)
        assert video.advance(3)[1]
        assert not video.next()
    finally:
        video.close()


def test_two_panel_controls(movie):
    from PySide6.QtWidgets import QApplication
    from app import Window
    app = QApplication.instance() or QApplication([])
    window = Window()
    try:
        for panel in window.panels:
            panel.video = Video(movie)
            panel.render()
        window.step_all(1)
        assert all(p.video.position == pytest.approx(1 / 30) for p in window.panels)
        window.panels[0].step(1)
        assert window.panels[0].video.position == pytest.approx(2 / 30)
        assert window.panels[1].video.position == pytest.approx(1 / 30)
        window.play_all()
        assert window.panels[0].started == window.panels[1].started
        for p in window.panels:
            p.tick(p.started + .5)
        assert all(p.video.position > .4 for p in window.panels)
        window.pause_all()
        assert not any(p.playing for p in window.panels)
        window.rewind()
        assert all(p.video.position == pytest.approx(0) for p in window.panels)
    finally:
        window.close()
        import shiboken6
        shiboken6.delete(window)


@pytest.mark.parametrize('angle', [90, -90, 180, 0])
def test_hevc_rotated_mov(tmp_path, movie, angle):
    encoded = tmp_path / 'hevc.mov'
    rotated = tmp_path / 'portrait.mov'
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(movie), '-c:v', 'libx265',
                    '-x265-params', 'pools=1:frame-threads=1:log-level=error',
                    '-tag:v', 'hvc1', str(encoded)], check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-display_rotation:v:0', str(angle), '-i', str(encoded),
                    '-c', 'copy', str(rotated)], check=True)
    video = Video(rotated)
    try:
        import numpy as np
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QImage
        from app import Panel
        app = QApplication.instance() or QApplication([])
        panel = Panel('rotation')
        panel.video = video
        panel.render()
        image = panel.pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
        actual = np.frombuffer(bytes(image.bits()), dtype=np.uint8).reshape(
            image.height(), image.bytesPerLine())[:, :image.width() * 3].reshape(
                image.height(), image.width(), 3)
        reference = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(rotated),
            '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
            capture_output=True, check=True).stdout
        expected = np.frombuffer(reference, dtype=np.uint8).reshape(actual.shape)
        assert np.abs(actual.astype(float) - expected.astype(float)).mean() < 3
        import shiboken6
        shiboken6.delete(panel)
        assert video.current.to_ndarray(format='rgb24').shape == (120, 160, 3)
        video.next()
        assert video.previous()
        assert video.position == pytest.approx(0)
    finally:
        video.close()
