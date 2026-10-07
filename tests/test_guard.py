"""The hosting guard: login check, request budget, short cache (no network, no web framework)."""
import base64
import unittest

from tvdata.guard import Cache, RateLimit, credentials_ok


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Login(unittest.TestCase):
    def test_accepts_the_right_pair(self):
        self.assertTrue(credentials_ok(basic("tvdata", "s3cret:with:colons"), "tvdata", "s3cret:with:colons"))
        self.assertTrue(credentials_ok(basic("tvdata", "s3cret").replace("Basic", "basic"), "tvdata", "s3cret"))

    def test_rejects_everything_else(self):
        for header in (None, "", "Basic", "Bearer abc", "Basic not-base64!", basic("tvdata", "wrong"),
                       basic("other", "s3cret"), basic("tvdata", ""), "Basic " + base64.b64encode(b"tvdatas3cret").decode(),
                       "Basic " + base64.b64encode(b"\xff\xfe:s3cret").decode()):
            self.assertFalse(credentials_ok(header, "tvdata", "s3cret"), header)


class Budget(unittest.TestCase):
    def test_refuses_past_the_limit_then_recovers(self):
        clock = Clock()
        limit = RateLimit(3, clock)
        self.assertEqual([limit.allow() for _ in range(5)], [True, True, True, False, False])
        clock.now += 59
        self.assertFalse(limit.allow())
        clock.now += 1  # the first three calls are now a minute old
        self.assertEqual([limit.allow() for _ in range(4)], [True, True, True, False])


class ShortCache(unittest.TestCase):
    def test_hit_until_expiry(self):
        clock = Clock()
        cache = Cache(clock=clock)
        self.assertEqual(cache.get("k"), (False, None))
        cache.put("k", {"bars": 1}, ttl=60)
        self.assertEqual(cache.get("k"), (True, {"bars": 1}))
        clock.now += 60
        self.assertEqual(cache.get("k"), (False, None))

    def test_a_cached_none_is_still_a_hit(self):
        cache = Cache(clock=Clock())
        cache.put("k", None, ttl=60)
        self.assertEqual(cache.get("k"), (True, None))

    def test_stays_within_its_size(self):
        clock = Clock()
        cache = Cache(max_entries=3, clock=clock)
        cache.put("old", 1, ttl=10)
        cache.put("a", 2, ttl=600)
        cache.put("b", 3, ttl=600)
        clock.now += 20  # "old" has expired and goes first
        cache.put("c", 4, ttl=600)
        self.assertEqual([cache.get(k)[0] for k in ("old", "a", "b", "c")], [False, True, True, True])
        cache.put("d", 5, ttl=600)  # nothing stale left: the oldest entry makes room
        self.assertEqual([cache.get(k)[0] for k in ("a", "b", "c", "d")], [False, True, True, True])


if __name__ == "__main__":
    unittest.main()
