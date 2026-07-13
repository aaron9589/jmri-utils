# trainstat_parser.py
#
# Pure parser for the CATS TrainStat TCP protocol. No JMRI imports, no I/O.
# Wire format and behavior: see PLAN.md sections 1 and 3. Interface contract:
# see ITERATIONS.md. Target Jython/Python 2.7.

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
