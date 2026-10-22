"""Private capture pipes with bounded in-memory tails; never the MCP input/output."""

import os
import threading


class TailBuffer:
    def __init__(self, limit):
        self.limit, self.total, self.data = limit, 0, bytearray()
        self.guard = threading.Lock()

    def feed(self, data):
        with self.guard:
            self.total += len(data)
            if len(data) >= self.limit:
                self.data[:] = data[-self.limit :]
            else:
                self.data.extend(data)
                if len(self.data) > self.limit:
                    del self.data[: -self.limit]

    def value(self, encoding=None, errors="strict"):
        with self.guard:
            data = bytes(self.data)
        return data.decode(encoding, errors) if encoding else data

    @property
    def truncated(self):
        return self.total > self.limit


class Captures:
    def __init__(self, limit):
        self.buffers = [TailBuffer(limit), TailBuffer(limit)]
        self.incoming = None
        self.readers, self.writers, self.threads, self.failures = [], [], [], []

    @property
    def streams(self):
        return (self.incoming, *self.writers)

    def _drain(self, stream, buffer):
        try:
            while data := stream.read(16_384):
                buffer.feed(data)
        except OSError:
            self.failures.append(True)
        finally:
            stream.close()

    def __enter__(self):
        try:
            self.incoming = open(os.devnull, "rb")
            for buffer in self.buffers:
                read_fd, write_fd = os.pipe()
                reader, writer = os.fdopen(read_fd, "rb", buffering=0), os.fdopen(write_fd, "wb", buffering=0)
                self.readers.append(reader)
                self.writers.append(writer)
                thread = threading.Thread(
                    target=self._drain, args=(reader, buffer), name="autocad-capture", daemon=True
                )
                thread.start()
                self.threads.append(thread)
            return self
        except BaseException:
            self.finish()
            raise

    def close_parent_writers(self):
        # The child owns its inherited duplicates; the parent must not retain a
        # writer that would hide EOF after the last contained descendant exits.
        for stream in self.writers:
            stream.close()

    def finish(self):
        self.close_parent_writers()
        for thread in self.threads:
            thread.join(timeout=5)
        if self.incoming is not None:
            self.incoming.close()
        if any(thread.is_alive() for thread in self.threads) or self.failures:
            raise RuntimeError("Private diagnostic capture did not close cleanly")
        for stream in self.readers:
            stream.close()

    def __exit__(self, *args):
        self.finish()
