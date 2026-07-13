# trainstat_mqtt.py
#
# JMRI-loadable Jython entry script: bridges the CATS TrainStat TCP feed to
# MQTT. All parsing lives in trainstat_parser.py; this file only owns the
# socket, MQTT client, and thread lifecycle. See PLAN.md sections 3
# "Architecture" / "JMRI integration".
#
# Load via Panels -> Run Script, or list in Preferences -> Start Up for
# auto-start. Call stop() before removing/replacing the script.
#
# Uses the Paho MQTT client bundled with JMRI directly (rather than a JMRI
# MQTT connection profile) for explicit per-publish retain control.

import sys
import threading

# Directory containing trainstat_parser.py. JMRI's Jython engine runs
# scripts via eval(), not execfile(), so there is no __file__ to derive this
# from -- set it to match wherever you placed both files.
SCRIPT_DIR = "/home/operations/documents/git repo"

if SCRIPT_DIR and SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

import trainstat_parser

from java.net import Socket, InetSocketAddress
from java.io import BufferedReader, InputStreamReader, IOException
from java.lang import System as JSystem

from org.eclipse.paho.client.mqttv3 import MqttClient, MqttConnectOptions, MqttMessage, MqttException
from org.eclipse.paho.client.mqttv3.persist import MemoryPersistence

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
                    for topic, payload, retain in trainstat_parser.parse_line(line, state):
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


start()
