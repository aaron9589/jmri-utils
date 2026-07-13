# cats-trainstat-parser

A JMRI Jython script that connects to a [CATS](https://sites.google.com/site/catsoldsite/) TrainStat TCP server, parses train/crew/location status, and publishes retained MQTT topics.

## Files

- `trainstat_mqtt.py` — the whole thing, single file. The top section is a pure protocol parser (`parse_line`, no JMRI imports, no I/O); the bottom section is the JMRI harness that owns the CATS socket, the MQTT client (Paho, bundled with JMRI), and the reader thread lifecycle, and calls `parse_line` for all parsing. Single file because JMRI's Jython engine runs scripts via `eval()` — no `__file__`, and no reliable way to resolve a sibling module on `sys.path`.
- `test_parser.py` — assert-based test for `parse_line`. Run with `python2 test_parser.py` or `jython test_parser.py`; works without JMRI since the java/Paho imports in `trainstat_mqtt.py` are guarded and skipped when unavailable.

## Usage

1. Copy `trainstat_mqtt.py` into the directory JMRI will load scripts from.
2. Edit the config constants at the top (`CATS_HOST`, `CATS_PORT`, `MQTT_HOST`, `MQTT_PORT`, etc.) for your layout.
3. Load `trainstat_mqtt.py` via *Panels → Run Script*, or add it to Preferences → Start Up for auto-start.
4. Call `stop()` from the JMRI script console before reloading/removing the script.

Set `DEBUG = True` in `trainstat_mqtt.py` to log every raw line received and every MQTT publish to the JMRI console; leave it `False` for normal operation.

## Topics published

All retained, QoS 0. Empty payload clears a topic.

- `trains/location/<station>` — train ID currently at a station
- `trains/crew/<crew_name>` — train a crew is running (whitespace → `_`, `+`/`#` stripped)
- `trains/train/<id>/consist` — engine(s) on a train
- `trains/train/<id>/crew` — crew currently assigned to a train
- `trains/bridge/status` — `online`/`offline`, set via MQTT last-will
