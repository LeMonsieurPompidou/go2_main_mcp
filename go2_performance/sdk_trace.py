"""Record SDK request/reply results without altering or retrying the request."""

from __future__ import annotations

import json
import math
import time


def recorded_client(client_class, record, feedback, *, clock=time.monotonic):
    """Wrap the installed SDK's _Call hook; keep its (code, data) unchanged."""
    class RecordedClient(client_class):
        def _Call(self, api_id, parameter):
            started = clock()
            event = {"event": "sdk_call", "api_id": api_id, "request": parameter,
                     "started_monotonic_s": started}
            try:
                code, data = super()._Call(api_id, parameter)
                event.update(code=code, response=data)
                return code, data
            except Exception as exc:
                event.update(exception=f"{type(exc).__name__}: {exc}")
                raise
            finally:
                event["duration_s"] = clock() - started
                reading = feedback.snapshot()
                if reading is not None:
                    event["robot"] = {
                        "telemetry_age_s": clock() - reading.timestamp,
                        "pitch_deg": math.degrees(reading.pitch),
                        "mode": reading.mode, "error_code": reading.error_code,
                    }
                record(event)

    return RecordedClient()


def jsonl_recorder(stream):
    def record(event):
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()
    return record
