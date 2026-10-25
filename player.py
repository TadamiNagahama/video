"""Timestamp-aware video decoder. PyAV wheels include FFmpeg codecs."""
import av


class Video:
    def __init__(self, path):
        self.container = av.open(str(path))
        try:
            self.stream = self.container.streams.video[0]
            self.stream.thread_type = 'AUTO'
            self.origin = float((self.stream.start_time or 0) * self.stream.time_base)
            self.duration = (float(self.stream.duration * self.stream.time_base)
                             if self.stream.duration else (self.container.duration or 0) / av.time_base)
            self.rotation = 0
            self.frames = iter(self.container.decode(self.stream))
            self.current = next(self.frames)
            self._read_rotation()
            self.pending = None
        except Exception:
            self.container.close()
            raise

    def _read_rotation(self):
        # Display matrices use counterclockwise angles; Qt uses clockwise angles.
        for side in self.current.side_data:
            if side.type.name == 'DISPLAYMATRIX':
                import struct, math
                matrix = struct.unpack('9i', bytes(side))
                self.rotation = math.degrees(math.atan2(matrix[1], matrix[0]))
        if not self.rotation:
            self.rotation = -float(self.stream.metadata.get('rotate', 0))

    @property
    def position(self):
        return float(self.current.time) - self.origin

    def next(self):
        frame = self.pending if self.pending is not None else next(self.frames, None)
        self.pending = None
        if frame is None:
            return False
        self.current = frame
        return True

    def seek(self, seconds):
        seconds = max(0, seconds)
        target = seconds + self.origin
        self.container.seek(int(target / self.stream.time_base), stream=self.stream, backward=True)
        self.frames = iter(self.container.decode(self.stream))
        self.pending = None
        first = next(self.frames, None)
        if first is None:
            return
        self.current = first
        for frame in self.frames:
            if float(frame.time) > target + 1e-7:
                self.pending = frame
                break
            self.current = frame

    def previous(self):
        target = float(self.current.time)
        if self.position <= 1e-7:
            return False
        # Seek increasingly far back if a sparse timestamp interval requires it.
        distance = 1.0
        while True:
            self.seek(max(0, target - self.origin - distance))
            previous = self.current if float(self.current.time) < target - 1e-7 else None
            while self.next():
                if float(self.current.time) >= target - 1e-7:
                    break
                previous = self.current
            if previous is not None:
                self.seek(float(previous.time) - self.origin)
                return True
            if target - self.origin - distance <= 0:
                return False
            distance *= 2

    def advance(self, seconds):
        changed = False
        while True:
            if self.pending is None:
                self.pending = next(self.frames, None)
            if self.pending is None:
                return changed, True
            if float(self.pending.time) - self.origin > seconds:
                return changed, False
            self.next()
            changed = True

    def close(self):
        self.container.close()
