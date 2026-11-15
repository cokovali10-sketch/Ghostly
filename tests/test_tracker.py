"""Unit tests for the pure parsing helpers in ghostly.core.tracker."""

from ghostly.core.tracker import Tracker


def test_parse_user_agent_chrome_windows():
    parsed = Tracker.parse_user_agent(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    assert parsed["browser"] == "Chrome"
    assert parsed["os"] == "Windows"
    assert parsed["device_type"] == "desktop"


def test_parse_user_agent_safari_macos():
    parsed = Tracker.parse_user_agent(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    )
    assert parsed["browser"] == "Safari"
    assert parsed["os"] == "macOS"


def test_parse_user_agent_iphone_is_mobile():
    parsed = Tracker.parse_user_agent(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
    assert parsed["device_type"] == "mobile"
    assert parsed["os"] == "iOS"


def test_parse_user_agent_firefox_android_is_mobile():
    parsed = Tracker.parse_user_agent(
        "Mozilla/5.0 (Android 13; Mobile; rv:120.0) Gecko/120.0 Firefox/120.0"
    )
    assert parsed["browser"] == "Firefox"
    assert parsed["device_type"] == "mobile"


def test_parse_user_agent_unknown_is_other_desktop():
    parsed = Tracker.parse_user_agent("some-random-crawler/1.0")
    assert parsed["browser"] == "Other"
    assert parsed["os"] == "Other"
    assert parsed["device_type"] == "desktop"


def test_detect_country_from_prefix():
    assert Tracker.detect_country("8.8.8.8") == "US"
    assert Tracker.detect_country("250.1.1.1") == "CA"


def test_detect_country_ipv6_is_not_mapped():
    # The bundled prefix table covers IPv4 only.
    assert Tracker.detect_country("2001:db8::1") == "Unknown"


def test_detect_country_unmapped_prefix():
    assert Tracker.detect_country("203.0.113.7") == "AU"
