"""HTTP request tool - fetch URLs with GET/POST, zero dependencies (urllib).

Useful for calling REST APIs, fetching web pages, and testing endpoints
without requiring requests or httpx to be installed.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from .base import Tool

_MAX_RESPONSE = 10_000  # chars


class HttpTool(Tool):
    name = "http"
    description = (
        "Send an HTTP request (GET or POST) and return the response body. "
        "Supports custom headers, query params, and JSON body. "
        "Response is truncated to 10k characters."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to request",
            },
            "method": {
                "type": "string",
                "enum": ["GET", "POST"],
                "description": "HTTP method (default: GET)",
            },
            "headers": {
                "type": "object",
                "description": "Optional HTTP headers as key-value pairs",
            },
            "params": {
                "type": "object",
                "description": "Optional URL query parameters as key-value pairs",
            },
            "body": {
                "type": "string",
                "description": "Optional request body (JSON string) for POST requests",
            },
        },
        "required": ["url"],
    }

    def execute(
        self,
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        params: dict | None = None,
        body: str | None = None,
    ) -> str:
        # append query params
        if params:
            url = url + "?" + urllib.parse.urlencode(params)

        data: bytes | None = None
        if body:
            data = body.encode("utf-8")

        req = urllib.request.Request(url, data=data, method=method.upper())

        # default headers
        req.add_header("User-Agent", "NanoCoder/1.0")
        if data:
            req.add_header("Content-Type", "application/json")

        if headers:
            for k, v in headers.items():
                req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read()
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")

                # pretty-print JSON
                if "application/json" in content_type:
                    try:
                        text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
                    except json.JSONDecodeError:
                        pass

                if len(text) > _MAX_RESPONSE:
                    text = text[:_MAX_RESPONSE] + f"\n\n... (truncated, {len(text)} chars total)"

                return f"[HTTP {status}]\n{text}"

        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            return f"[HTTP {e.code} {e.reason}]\n{body_text}"
        except urllib.error.URLError as e:
            return f"[URL Error] {e.reason}"
        except Exception as e:
            return f"[Error] {e}"
