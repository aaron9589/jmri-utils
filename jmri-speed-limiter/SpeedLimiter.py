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

# WiThrottle clients send speed as steps 0-126. Per-loco limit comes from
# the roster entry's Model field (a number 0-126); locos with no roster
# entry or a non-numeric Model get this default. 126 = unlimited.
DEFAULT_MAX_STEP = 40
# tolerance so a command station quantizing the limit to a nearby step
# doesn't re-trigger the clamp forever
EPSILON = 0.5 / 126.0

# throttle -> speed limit (0.0-1.0) for throttles we've hooked; weak keys so
# released throttles get dropped, synchronized because the clamp listener
# can fire off the Swing thread
_hooked = java.util.Collections.synchronizedMap(java.util.WeakHashMap())


def _max_step_for(throttle):
    address = str(throttle.getLocoAddress().getNumber())
    entries = jmri.jmrit.roster.Roster.getDefault().matchingList(
        None, None, address, None, None, None, None)
    if not entries.isEmpty():
        try:
            return min(max(int(entries.get(0).getModel().strip()), 0), 126)
        except (ValueError, AttributeError):
            pass  # empty or non-numeric Model field
    return DEFAULT_MAX_STEP


class SpeedClamp(java.beans.PropertyChangeListener):
    def propertyChange(self, event):
        if event.propertyName != 'SpeedSetting':
            return
        limit = _hooked.get(event.source)
        # newValue < 0 is emergency stop; leave it alone
        if limit is not None and event.newValue > limit + EPSILON:
            event.source.setSpeedSetting(limit)


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
    if throttle is None or _hooked.containsKey(throttle):
        return
    step = _max_step_for(throttle)
    limit = step / 126.0
    _hooked.put(throttle, limit)
    throttle.addPropertyChangeListener(_clamp)
    if throttle.getSpeedSetting() > limit + EPSILON:
        throttle.setSpeedSetting(limit)
    print "SpeedLimiter: capped %s at step %d" % (throttle.getLocoAddress(), step)


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
print "SpeedLimiter: running, per-loco limit from roster Model field, default step %d/126" % DEFAULT_MAX_STEP
