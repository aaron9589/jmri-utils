# trainstat_mqtt.py
#
# JMRI-loadable Jython script: connects to a CATS TrainStat TCP server,
# parses train/crew/location status, and publishes retained MQTT topics.
# Single file so JMRI's Jython engine (which runs scripts via eval(), with
# no __file__ and no reliable way to find a sibling file) never needs to
# resolve a second module on sys.path.
#
# Load via Panels -> Run Script, or list in Preferences -> Start Up for
# auto-start. Call stop() before removing/replacing the script.
#
# Uses the Paho MQTT client bundled with JMRI directly (rather than a JMRI
# MQTT connection profile) for explicit per-publish retain control.

import sys
import threading

CATS_HOST = "192.168.0.110"
CATS_PORT = 54321
MQTT_HOST = "mqtt.example.com"  # set to your broker's host
MQTT_PORT = 1883
CLIENT_ID = "trainstat-bridge"
STATUS_TOPIC = "trains/bridge/status"
RECONNECT_MIN = 2
RECONNECT_MAX = 60
CONNECT_TIMEOUT_MS = 5000
DEBUG = False  # log every raw line and publish; noisy, off by default

_JMRI_AVAILABLE = True
try:
    from java.net import Socket, InetSocketAddress
    from java.io import BufferedReader, InputStreamReader, IOException
    from java.lang import System as JSystem

    from org.eclipse.paho.client.mqttv3 import MqttClient, MqttConnectOptions, MqttMessage, MqttException
    from org.eclipse.paho.client.mqttv3.persist import MemoryPersistence
except ImportError:
    # Running outside JMRI (e.g. test_parser.py under plain python2/jython).
    # Only parse_line is exercised in that case.
    _JMRI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Parser: pure functions, no JMRI/I-O. See PLAN.md sections 1 and 3 for the
# wire format and behavior this implements.

TOPIC_PREFIX = "trains/"

STATUS_VERSION = "4"

TAG_GREETING = "TrainStat"
TAG_ADD = "Added"
TAG_CHANGE = "Changed"
TAG_DELETE = "Deleted"
TAG_MOVE = "Move:"
TAG_ASSIGN = "Assign:"
TAG_TERMINATED = "Terminated:"
TAG_TIEDDOWN = "TiedDown:"
TAG_RERUN = "Rerun:"
TAG_DISCONNECT = "Disconnect"

STORE_TRAINDATA = "TRAINDATA"
NOTHING = "nothing"


def unquote(s):
    """Strips one matched pair of surrounding quotes, if present."""
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _sanitize_topic_name(name):
    out = []
    for ch in name:
        if ch in '+#':
            continue
        out.append('_' if ch.isspace() else ch)
    return ''.join(out)


def _field_pairs(tokens):
    fields = {}
    for tok in tokens:
        if '=' not in tok:
            continue
        tag, _, value = tok.partition('=')
        fields[tag] = unquote(value)
    return fields


def _clear_train(train_id, state):
    """Terminated/TiedDown/Deleted: wipe consist, crew, and location for train_id."""
    results = [
        (TOPIC_PREFIX + "train/" + train_id + "/consist", "", True),
        (TOPIC_PREFIX + "train/" + train_id + "/crew", "", True),
    ]
    locations = state.setdefault('locations', {})
    station = locations.pop(train_id, None)
    if station:
        results.append((TOPIC_PREFIX + "location/" + station, "", True))
    crews = state.setdefault('crews', {})
    crew_name = crews.pop(train_id, None)
    if crew_name:
        results.append((TOPIC_PREFIX + "crew/" + _sanitize_topic_name(crew_name), "", True))
    return results


def _traindata_update(train_id, fields, state):
    results = []
    if 'ENGINE' in fields:
        results.append((TOPIC_PREFIX + "train/" + train_id + "/consist", fields['ENGINE'], True))
    if 'CREW' in fields:
        crew_val = fields['CREW']
        results.append((TOPIC_PREFIX + "train/" + train_id + "/crew", crew_val, True))
        crews = state.setdefault('crews', {})
        if crew_val:
            old = crews.get(train_id)
            if old and old != crew_val:
                results.append((TOPIC_PREFIX + "crew/" + _sanitize_topic_name(old), "", True))
            results.append((TOPIC_PREFIX + "crew/" + _sanitize_topic_name(crew_val), train_id, True))
            crews[train_id] = crew_val
        else:
            old = crews.pop(train_id, None)
            if old:
                results.append((TOPIC_PREFIX + "crew/" + _sanitize_topic_name(old), "", True))
    return results


def _handle_store_record(tag, tokens, state):
    if len(tokens) < 3:
        return []
    store = tokens[2]
    if store != STORE_TRAINDATA:
        return []
    fields = _field_pairs(tokens[3:])
    train_id = fields.get('TRAIN_SYMBOL')
    if not train_id:
        return []
    if tag == TAG_DELETE:
        return _clear_train(train_id, state)
    return _traindata_update(train_id, fields, state)


def _handle_move(tokens, state):
    if len(tokens) < 6:
        return []
    train_id = unquote(tokens[2])
    from_station = unquote(tokens[3])
    to_station = unquote(tokens[5])
    locations = state.setdefault('locations', {})
    results = []
    if locations.get(train_id) == from_station:
        results.append((TOPIC_PREFIX + "location/" + from_station, "", True))
    results.append((TOPIC_PREFIX + "location/" + to_station, train_id, True))
    locations[train_id] = to_station
    return results


def _handle_assign(tokens, state):
    if len(tokens) < 5:
        return []
    crew_name = unquote(tokens[2])
    train_val = unquote(tokens[4])
    topic = TOPIC_PREFIX + "crew/" + _sanitize_topic_name(crew_name)
    if train_val == NOTHING:
        return [(topic, "", True)]
    return [(topic, train_val, True)]


def parse_line(line, state):
    """line: one decoded line from the socket, no trailing CR/LF.
    state: mutable dict, owns 'locations' {train_id: station} and
           anything else the parser needs across lines.
    Returns: list of (topic, payload, retain) tuples. Empty list = ignore.
    Raises nothing: malformed lines return [] (optionally state['warnings']).
    """
    if not line:
        return []
    tokens = line.split('\t')
    tag = tokens[0]

    if tag == TAG_GREETING:
        if len(tokens) >= 3 and tokens[2] != STATUS_VERSION:
            state.setdefault('warnings', []).append(
                "unexpected TrainStat version: " + tokens[2])
        return []

    if tag == TAG_DISCONNECT:
        state['disconnect'] = True
        return []

    if tag in (TAG_ADD, TAG_CHANGE, TAG_DELETE):
        return _handle_store_record(tag, tokens, state)

    if tag == TAG_MOVE:
        return _handle_move(tokens, state)

    if tag == TAG_ASSIGN:
        return _handle_assign(tokens, state)

    if tag in (TAG_TERMINATED, TAG_TIEDDOWN):
        if len(tokens) < 3:
            return []
        return _clear_train(unquote(tokens[2]), state)

    if tag == TAG_RERUN:
        return []

    # OOS:, T&T:, Ended:, and anything else: out of scope, ignore.
    return []


# ---------------------------------------------------------------------------
# JMRI harness: socket, MQTT client, thread lifecycle. Everything below this
# point touches java/Paho and only runs under JMRI.

# The singleton instance is stashed on the `sys` module rather than a plain
# module-level global: JMRI's "Run Script" re-execs this file from scratch
# each time, which would reset ordinary globals and orphan a running thread.
# `sys` is the one object guaranteed to persist across re-execs in the same
# interpreter.
_SINGLETON_ATTR = "_trainstat_mqtt_bridge"


def _log(msg):
    JSystem.out.println("trainstat_mqtt: " + msg)


def _to_bytes(payload):
    # BufferedReader hands us Java Strings, which Jython surfaces as
    # unicode; Paho's MqttMessage wants a byte[].
    if isinstance(payload, unicode):
        return payload.encode("utf-8")
    return payload


def _publish(client, topic, payload, retain):
    msg = MqttMessage(_to_bytes(payload))
    msg.setQos(0)
    msg.setRetained(retain)
    try:
        client.publish(topic, msg)
    except MqttException as e:
        _log("publish failed for %s: %s" % (topic, e))


class _Bridge(object):

    def __init__(self):
        self._lock = threading.Lock()
        self._stop_flag = threading.Event()
        self._thread = None
        self._mqtt = None
        self._socket = None

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        with self._lock:
            self._stop_flag.clear()
            self._mqtt = self._connect_mqtt()
            self._thread = threading.Thread(target=self._reader_loop)
            self._thread.setDaemon(True)
            self._thread.start()
        _log("started")

    def stop(self):
        with self._lock:
            self._stop_flag.set()
            sock = self._socket
        if sock is not None:
            try:
                sock.close()
            except IOException:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(5)
        with self._lock:
            self._thread = None
            mqtt = self._mqtt
            self._mqtt = None
        if mqtt is not None:
            try:
                _publish(mqtt, STATUS_TOPIC, "offline", True)
                mqtt.disconnect()
            except MqttException:
                pass
        _log("stopped")

    def _connect_mqtt(self):
        opts = MqttConnectOptions()
        opts.setCleanSession(True)
        opts.setAutomaticReconnect(True)
        opts.setWill(STATUS_TOPIC, _to_bytes("offline"), 0, True)
        client = MqttClient("tcp://" + MQTT_HOST + ":" + str(MQTT_PORT), CLIENT_ID, MemoryPersistence())
        client.connect(opts)
        _publish(client, STATUS_TOPIC, "online", True)
        return client

    def _reader_loop(self):
        state = {}
        backoff = RECONNECT_MIN
        while not self._stop_flag.is_set():
            sock = None
            reader = None
            try:
                sock = Socket()
                sock.connect(InetSocketAddress(CATS_HOST, CATS_PORT), CONNECT_TIMEOUT_MS)
                self._socket = sock
                reader = BufferedReader(InputStreamReader(sock.getInputStream(), "UTF-8"))
                _log("connected to CATS at %s:%s" % (CATS_HOST, CATS_PORT))
                backoff = RECONNECT_MIN
                state = {}
                while not self._stop_flag.is_set():
                    line = reader.readLine()
                    if line is None:
                        break
                    if DEBUG:
                        _log("recv: %s" % line)
                    for topic, payload, retain in parse_line(line, state):
                        if DEBUG:
                            _log("publish: %s = %r (retain=%s)" % (topic, payload, retain))
                        _publish(self._mqtt, topic, payload, retain)
                    if state.get('disconnect'):
                        break
            except IOException as e:
                _log("socket error: %s" % e)
            except Exception as e:
                _log("reader loop error: %s" % e)
            finally:
                self._socket = None
                for closable in (reader, sock):
                    if closable is not None:
                        try:
                            closable.close()
                        except IOException:
                            pass
            if self._stop_flag.is_set():
                break
            _log("reconnecting in %s s" % backoff)
            self._stop_flag.wait(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX)


def start():
    existing = getattr(sys, _SINGLETON_ATTR, None)
    if existing is not None and existing.is_running():
        _log("already running, ignoring start()")
        return
    bridge = _Bridge()
    bridge.start()
    setattr(sys, _SINGLETON_ATTR, bridge)


def stop():
    bridge = getattr(sys, _SINGLETON_ATTR, None)
    if bridge is not None:
        bridge.stop()
        setattr(sys, _SINGLETON_ATTR, None)


if _JMRI_AVAILABLE:
    start()
