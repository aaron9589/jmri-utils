# jmri-speed-limiter

Caps every WiThrottle client (Engine Driver, WiThrottle app, etc.) at a
maximum speed step. Any throttle pushed above the limit is immediately
forced back to it.

## Setup

1. Per-loco limits: put a number 0-126 in the roster entry's **Model**
   field (DecoderPro > edit entry). `126` = unlimited. Locos with no
   roster entry, or an empty/non-numeric Model field, get the default of
   40 (`DEFAULT_MAX_STEP` in `SpeedLimiter.py`).
2. Run it once per JMRI session: **Scripting > Run Script**, or add it as a
   startup action (**Preferences > Start Up > Add > Run Script**) so it's
   always active.

WiThrottle speed is 0-126 steps regardless of the decoder's speed-step
mode. Roster edits take effect the next time a loco is selected on a
throttle, not while it's already held.

## How it works

- Polls the WiThrottle server's device list once a second and attaches a
  `PropertyChangeListener` to each throttle a client acquires.
- The listener fires on every speed change, so the clamp is instant -- the
  poll only exists to discover new throttles.
- Emergency stop (negative speed) is left untouched.
- The WiThrottle server's throttle lists are package-private, so they're
  read via reflection -- no JMRI settings changes needed.
