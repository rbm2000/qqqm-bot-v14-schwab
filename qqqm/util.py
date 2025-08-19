import os, time, json, requests, math
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

def discord(msg: str):
    url = os.getenv("DISCORD_WEBHOOK")
    if not url:
        return False
    try:
        requests.post(url, json={"content": msg[:1900]} , timeout=10)
        return True
    except Exception as e:
        print("Discord error:", e)
        return False

def pct(a, b):
    return 0 if b == 0 else (a - b) / b

def now_ts():
    return datetime.utcnow().isoformat()

def human_money(x):
    return f"${x:,.2f}"


import time
from typing import Optional, Dict
import requests

JOURNAL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "journal.jsonl")
os.makedirs(os.path.dirname(JOURNAL_PATH), exist_ok=True)

def journal(event: Dict):
    # append-only, one json per line
    try:
        with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({**event, "ts": now_ts()}) + "\n")
    except Exception as e:
        print("Journal error:", e)

def http_request(method: str, url: str, *, headers=None, params=None, json_body=None, data=None, auth=None, retries=3, backoff=0.75, timeout=10):
    for i in range(retries + 1):
        try:
            r = requests.request(method, url, headers=headers, params=params, json=json_body, data=data, auth=auth, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.exceptions.HTTPError as e:
            # Don't retry on client-side errors (4xx)
            if 400 <= e.response.status_code < 500:
                raise
            if i == retries:
                raise
        except requests.exceptions.RequestException as e:
            if i == retries:
                raise
        time.sleep(backoff * (2 ** i))


def vol_factor(vix: float, floor: float, target: float, ceiling: float, min_f: float, max_f: float) -> float:
    # below floor => max_f; above ceiling => min_f; interpolate in between
    if vix <= floor: return max_f
    if vix >= ceiling: return min_f
    # linear scale between floor and ceiling
    span = ceiling - floor
    t = (vix - floor) / span
    return max(min_f, max_f - t*(max_f-min_f))

def legs_mid_credit(chain: list, legs: list) -> float | None:
    # legs: [{'type': 'call/put', 'strike': x, 'side': 'short/long'}]; we return total credit (>0 means received)
    sym = 0.0
    for leg in legs:
        matches = [o for o in chain if o['type']==leg['type'] and abs(o['strike']-leg['strike'])<1e-6]
        if not matches:
            return None
        bid = matches[0].get('bid',0) or 0
        ask = matches[0].get('ask',0) or 0
        mid = (ask if bid==0 else bid if ask==0 else (ask+bid)/2)
        # short receives premium (+), long pays (-)
        sym += mid * (1 if leg['side']=='short' else -1)
    # 1 contract assumed; scale by 100
    return sym * 100


import threading, time

class RateLimiter:
    """Simple token-bucket limiter per (scope, window). Thread-safe enough for our low QPS.

    limiter_map = {}  # {(name): RateLimiter}

    """
    def __init__(self, capacity:int, refill:int, per_seconds:float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill = refill
        self.per_seconds = per_seconds
        self.lock = threading.Lock()
        self.last = time.time()

    def acquire(self, n:int=1):
        with self.lock:
            now = time.time()
            elapsed = now - self.last
            if elapsed > 0:
                add = int(elapsed * (self.refill / self.per_seconds))
                if add > 0:
                    self.tokens = min(self.capacity, self.tokens + add)
                    self.last = now
            if self.tokens >= n:
                self.tokens -= n
                return True
            else:
                return False

    def wait(self, n:int=1):
        while True:
            if self.acquire(n):
                return
            time.sleep(max(0.05, self.per_seconds / max(1,self.refill)))

def get_limiter(name:str, capacity:int, refill:int, per_seconds:float) -> RateLimiter:
    lm = RateLimiter.limiter_map
    if name not in lm:
        lm[name] = RateLimiter(capacity, refill, per_seconds)
    return lm[name]

# Add OAuthStore to the file
class OAuthStore:
    _path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "oauth_tokens.json")

    @staticmethod
    def load() -> dict:
        if not os.path.exists(OAuthStore._path):
            return {}
        try:
            with open(OAuthStore._path, "r") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError):
            return {}

    @staticmethod
    def save(tokens: dict):
        os.makedirs(os.path.dirname(OAuthStore._path), exist_ok=True)
        try:
            with open(OAuthStore._path, "w") as f:
                json.dump(tokens, f)
        except IOError:
            pass