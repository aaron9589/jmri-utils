# SpeedLimiter.py -- cap all WiThrottle client throttles at a max speed step.
#
# Watches the JMRI WiThrottle server for connected devices, attaches a
# listener to every throttle they acquire, and instantly forces any speed
# above the limit back down to the limit.
#
# Run from Scripting > Run Script, or add to JMRI startup actions.
# Uses reflection to reach the WiThrottle server's package-private fields,
# so it works whether or not respectJavaAccessibility is set.

import java
import java.lang
import java.util
import java.beans
import java.awt.event
import javax.swing
import jmri

# WiThrottle clients send speed as steps 0-126; cap at this step.
MAX_SPEED_STEP = 40
LIMIT = MAX_SPEED_STEP / 126.0
# tolerance so a command station quantizing LIMIT to a nearby step
# doesn't re-trigger the clamp forever
EPSILON = 0.5 / 126.0

# throttles we've already hooked; weak keys so released throttles get dropped
_seen = java.util.WeakHashMap()


class SpeedClamp(java.beans.PropertyChangeListener):
    def propertyChange(self, event):
        # newValue < 0 is emergency stop; leave it alone
        if event.propertyName == 'SpeedSetting' and event.newValue > LIMIT + EPSILON:
            event.source.setSpeedSetting(LIMIT)


_clamp = SpeedClamp()


def _get(obj, name):
    # read a package-private field via reflection, walking up superclasses
    # (e.g. MultiThrottleController inherits 'throttle' from ThrottleController)
    cls = obj.getClass()
    while cls is not None:
        try:
            field = cls.getDeclaredField(name)
        except java.lang.NoSuchFieldException:
            cls = cls.getSuperclass()
            continue
        field.setAccessible(True)
        return field.get(obj)
    return None


def _hook(throttle):
    if throttle is None or _seen.containsKey(throttle):
        return
    _seen.put(throttle, True)
    throttle.addPropertyChangeListener(_clamp)
    if throttle.getSpeedSetting() > LIMIT + EPSILON:
        throttle.setSpeedSetting(LIMIT)
    print "SpeedLimiter: capped %s at step %d" % (throttle.getLocoAddress(), MAX_SPEED_STEP)


class Scanner(java.awt.event.ActionListener):
    def actionPerformed(self, event):
        server = jmri.InstanceManager.getNullableDefault(jmri.jmrit.withrottle.DeviceManager)
        if server is None:
            return  # WiThrottle server not started yet; keep polling
        try:
            for device in server.getDeviceList():
                # modern clients (Engine Driver, WiThrottle app) use MultiThrottle
                mts = _get(device, 'multiThrottles')
                if mts is not None:
                    for mt in mts.values():
                        tcs = _get(mt, 'throttles')
                        if tcs is None:
                            continue
                        for tc in tcs.values():
                            _hook(_get(tc, 'throttle'))
                # legacy single-throttle protocol
                for tc in (_get(device, 'throttleController'),
                           _get(device, 'secondThrottleController')):
                    if tc is not None:
                        _hook(_get(tc, 'throttle'))
        except java.util.ConcurrentModificationException:
            pass  # device list changed mid-scan; next tick catches it


# ponytail: 1s discovery poll instead of DeviceListener wiring -- clamping
# itself is instant via PropertyChangeListener, the poll only finds new
# throttles. Switch to addDeviceListener if 1s attach latency ever matters.
timer = javax.swing.Timer(1000, Scanner())
timer.start()
print "SpeedLimiter: running, max speed step %d/126" % MAX_SPEED_STEP
