"""Minimal Delta Exchange REST v2 client (HMAC-SHA256 auth), stdlib only.

Signature = HMAC_SHA256(api_secret, method + timestamp + path + query_string + body)
Headers: api-key, timestamp, signature, User-Agent, Content-Type.
Docs: https://docs.delta.exchange
"""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URLS = {
    "india": "https://api.india.delta.exchange",
    "india-testnet": "https://cdn-ind.testnet.deltaex.org",
    "global": "https://api.delta.exchange",
    "global-testnet": "https://testnet-api.delta.exchange",
}


class DeltaError(Exception):
    pass


def sign(secret, method, timestamp, path, query_string="", body=""):
    msg = method + timestamp + path + query_string + body
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


class DeltaClient:
    def __init__(self, api_key="", api_secret="", env="india", timeout=15, retries=3):
        self.base = BASE_URLS[env]
        self.key, self.secret = api_key, api_secret
        self.timeout, self.retries = timeout, retries

    # ---------------- transport ----------------
    def _request(self, method, path, params=None, body=None, auth=False):
        qs = ("?" + urllib.parse.urlencode(params)) if params else ""
        data = json.dumps(body, separators=(",", ":")) if body is not None else ""
        last = None
        for attempt in range(self.retries):
            headers = {"User-Agent": "trend-breakout-bot/1.0", "Content-Type": "application/json"}
            if auth:
                ts = str(int(time.time()))
                headers.update({"api-key": self.key, "timestamp": ts,
                                "signature": sign(self.secret, method, ts, path, qs, data)})
            req = urllib.request.Request(self.base + path + qs, data=data.encode() if data else None,
                                         headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    payload = json.loads(r.read().decode())
                if not payload.get("success", True):
                    raise DeltaError(payload.get("error"))
                return payload.get("result")
            except urllib.error.HTTPError as e:
                body_txt = e.read().decode(errors="replace")
                if e.code in (429, 500, 502, 503, 504):
                    last = DeltaError(f"{e.code} {body_txt}")
                    time.sleep(2 ** attempt)
                    continue
                raise DeltaError(f"{method} {path} -> {e.code} {body_txt}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                last = e
                time.sleep(2 ** attempt)
        raise DeltaError(f"{method} {path} failed after retries: {last}")

    # ---------------- public ----------------
    def product(self, symbol):
        return self._request("GET", f"/v2/products/{symbol}")

    def candles(self, symbol, resolution, start, end):
        return self._request("GET", "/v2/history/candles",
                             {"resolution": resolution, "symbol": symbol, "start": int(start), "end": int(end)})

    # ---------------- private ----------------
    def balances(self):
        return self._request("GET", "/v2/wallet/balances", auth=True)

    def position(self, product_id):
        return self._request("GET", "/v2/positions", {"product_id": product_id}, auth=True)

    def open_orders(self, product_id):
        return self._request("GET", "/v2/orders", {"product_ids": product_id, "states": "open,pending"}, auth=True)

    def set_leverage(self, product_id, leverage):
        return self._request("POST", f"/v2/products/{product_id}/orders/leverage",
                             body={"leverage": str(leverage)}, auth=True)

    def market_order(self, product_id, side, size, reduce_only=False, client_order_id=None):
        body = {"product_id": product_id, "size": int(size), "side": side, "order_type": "market_order",
                "reduce_only": reduce_only}
        if client_order_id:
            body["client_order_id"] = client_order_id
        return self._request("POST", "/v2/orders", body=body, auth=True)

    def stop_order(self, product_id, side, size, stop_price, client_order_id=None):
        """Reduce-only stop-market order used as the protective / trailing stop."""
        body = {"product_id": product_id, "size": int(size), "side": side, "order_type": "market_order",
                "stop_order_type": "stop_loss_order", "stop_price": str(stop_price), "reduce_only": True}
        if client_order_id:
            body["client_order_id"] = client_order_id
        return self._request("POST", "/v2/orders", body=body, auth=True)

    def edit_stop(self, product_id, order_id, stop_price, size):
        return self._request("PUT", "/v2/orders", body={"id": order_id, "product_id": product_id,
                                                        "stop_price": str(stop_price), "size": int(size)}, auth=True)

    def cancel(self, product_id, order_id):
        return self._request("DELETE", "/v2/orders", body={"id": order_id, "product_id": product_id}, auth=True)
