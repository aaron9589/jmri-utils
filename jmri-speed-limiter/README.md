# jmri-speed-limiter

Caps every WiThrottle client (Engine Driver, WiThrottle app, etc.) at a
maximum speed step. Any throttle pushed above the limit is immediately
forced back to it.

## Setup

1. Edit `MAX_SPEED_STEP` in `SpeedLimiter.py` if 40 isn't what you want
   (WiThrottle speed is 0-126 regardless of the decoder's speed-step mode).
2. Run it once per JMRI session: **Scripting > Run Script**, or add it as a
   startup action (**Preferences > Start Up > Add > Run Script**) so it's
   always active.

## How it works

- Polls the WiThrottle server's device list once a second and attaches a
  `PropertyChangeListener` to each throttle a client acquires.
- The listener fires on every speed change, so the clamp is instant -- the
  poll only exists to discover new throttles.
- Emergency stop (negative speed) is left untouched.

Requires JMRI's default jython setting `respectJavaAccessibility=false`
(you have it unless you deliberately changed it).
