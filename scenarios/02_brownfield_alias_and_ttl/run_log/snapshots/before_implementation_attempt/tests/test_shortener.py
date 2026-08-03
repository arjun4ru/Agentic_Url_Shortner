from app.shortener import encode_base62, generate_short_code


def test_encode_base62_zero():
    assert encode_base62(0) == "0"


def test_encode_base62_is_deterministic():
    assert encode_base62(12345) == encode_base62(12345)


def test_generate_short_code_is_unique_for_sequential_counters():
    codes = {generate_short_code(i) for i in range(1000)}
    assert len(codes) == 1000
