# cats-trainstat-parser

A JMRI Jython script that connects to a [CATS](https://sites.google.com/site/catsoldsite/) TrainStat TCP server, parses train/crew/location status, and publishes retained MQTT topics.

## Files

- `trainstat_parser.py` — pure protocol parser (`parse_line`). No JMRI imports, no I/O.
- `test_parser.py` — assert-based test for the parser. Run with `python2 test_parser.py` or `jython test_parser.py`.
- `trainstat_mqtt.py` — JMRI-loadable entry script. Owns the CATS socket, the MQTT client (Paho, bundled with JMRI), and the reader thread lifecycle. Calls into `trainstat_parser.parse_line` for all parsing.

## Usage

1. Copy `trainstat_parser.py` and `trainstat_mqtt.py` into the same directory JMRI will load scripts from.
2. Edit the config constants at the top of `trainstat_mqtt.py` (`CATS_HOST`, `CATS_PORT`, `MQTT_HOST`, `MQTT_PORT`, etc.) for your layout.
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
