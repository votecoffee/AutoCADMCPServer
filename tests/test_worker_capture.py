from autocad_mcp.worker_capture import TailBuffer


def test_tail_memory_remains_bounded_and_marks_truncation():
    buffer = TailBuffer(8)
    for data in [b"abc", b"def", b"gh", b"ijkl", b"m" * 100_000]:
        buffer.feed(data)
        assert len(buffer.data) <= 8
    assert buffer.value() == b"m" * 8 and buffer.truncated
    assert buffer.total == 100_012


def test_exact_limit_is_not_truncated_and_decoding_is_explicit():
    buffer = TailBuffer(4)
    buffer.feed(b"text")
    assert not buffer.truncated and buffer.value("utf-8") == "text"
