"""Start the real executable and verify TCP/JSON/static hosting without mocks."""
import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from backend.example_request import example_request
from backend.registry import ROOT
from backend.tests.temp_data import isolated_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    opener = build_opener(ProxyHandler({}))

    def call(path, payload=None, headers=None):
        request = Request(base + path, data=json.dumps(payload).encode("utf-8") if payload is not None else None,
                          headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = opener.open(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            return response.status, response.headers, body

    with isolated_data() as data_dir, tempfile.TemporaryFile() as output:
        process = subprocess.Popen([sys.executable, "-m", "backend", "--port", str(port),
                                    "--registry", "backend/config/registry.example.json", "--serve-frontend", "--data-dir", data_dir],
                                   cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    output.seek(0)
                    raise RuntimeError(output.read().decode("utf-8", errors="replace"))
                try:
                    status, _, body = call("/api/runtime")
                    if status == 200:
                        break
                except (URLError, ConnectionError, TimeoutError):
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Local service did not start within 10 seconds")
            runtime = json.loads(body)["data"]
            assert runtime["modelInterface"]["available"]
            assert runtime["capabilities"]["dataImport"]
            assert runtime['capabilities']['anomalyDetection'] and runtime['capabilities']['offlineDetection']
            assert not runtime['capabilities']['causeDiagnosis'] and runtime['capabilities']['reportPersistence']
            status, _, body = call("/api/models?stationId=station-example-m1-7")
            assert status == 200
            model = json.loads(body)["data"]["items"][0]
            assert model["status"] == "ready"
            status, headers, body = call("/api/model-inferences", example_request())
            assert status == 200, body
            inference_response = json.loads(body)
            data = inference_response["data"]
            assert len(data["points"]) == 60
            assert data["modelSnapshot"]["isDemo"] is True
            assert data["persisted"] is False
            assert headers["x-request-id"] == inference_response["requestId"]
            for path in ("/", "/overview", "/networks", "/detections", "/diagnosis"):
                status, headers, body = call(path, headers={"Accept": "text/html"})
                assert status == 200 and "text/html" in headers["content-type"]
                assert b'id="app"' in body
            status, headers, body = call("/api/missing", headers={"Accept": "text/html"})
            assert status == 404 and json.loads(body)["error"]["code"] == "NOT_FOUND"
            status, _, body = call("/api/diagnoses", {})
            assert status == 503 and json.loads(body)["error"]["code"] == "CAPABILITY_UNAVAILABLE"
            status, _, body = call("/api/model-inferences", example_request(), {"Origin": "https://example.invalid"})
            assert status == 403 and json.loads(body)["error"]["code"] == "ORIGIN_REJECTED"
            status, _, body = call("/api/openapi.json")
            assert status == 200 and "/api/model-inferences" in json.loads(body)["paths"]
            record = {"verifiedAt": datetime.now(timezone.utc).isoformat(), "transport": "real loopback TCP",
                      "input": "60 synthetic 30-minute points; not field validation data",
                      "runtime": runtime, "model": model, "summary": data["summary"],
                      "warnings": data["warnings"], "persisted": data["persisted"],
                      "checks": ["CLI startup", "runtime capabilities", "actual registered model",
                                 "actual inference", "JSON request ID", "all four frontend routes",
                                 "API 404 JSON", "unsupported business capability", "Origin rejection", "OpenAPI"]}
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Real HTTP smoke checks passed (synthetic input, actual model).")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
