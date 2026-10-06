# SPDX-License-Identifier: Apache-2.0
"""Version-one observation envelope, shared by functional and timing readers."""
MAX_TIME = 2**63 - 1


def validate_events(events):
    if not events:
        raise RuntimeError("EMPTY_OBSERVATION_TRACE")
    previous = -1
    for index, event in enumerate(events, 1):
        if (not isinstance(event, dict)
                or type(event.get("index")) is not int or event["index"] != index
                or type(event.get("time_fs")) is not int
                or not 0 <= event["time_fs"] <= MAX_TIME
                or type(event.get("time_ps")) is not int
                or event["time_ps"] != event["time_fs"] // 1000
                or not isinstance(event.get("kind"), str) or not event["kind"].strip()):
            raise RuntimeError("INVALID_OBSERVATION_ENVELOPE")
        if event["time_fs"] < previous:
            raise RuntimeError("OBSERVATION_TIME_ORDER")
        previous = event["time_fs"]
