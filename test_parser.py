# test_parser.py
#
# Assert-based transcript test for trainstat_parser.parse_line.
# Runs under plain python2 or jython, no frameworks:
#   python2 test_parser.py
#   jython test_parser.py

from trainstat_mqtt import parse_line


def check(label, line, state, expected):
    got = parse_line(line, state)
    assert got == expected, (
        "%s\n  line: %r\n  expected: %r\n  got: %r" % (label, line, expected, got)
    )


def test_transcript():
    state = {}

    # Greeting, correct version.
    check("greeting v4", "TrainStat\tVersion\t4\tCATS\t3.02", state, [])
    assert 'warnings' not in state

    # Greeting, unexpected version -> warns, still no publishes.
    check("greeting v5", "TrainStat\tVersion\t5\tCATS\t3.02", state, [])
    assert state['warnings'] == ["unexpected TrainStat version: 5"]

    # Store dump: format-descriptor and non-TRAINDATA records are ignored.
    check("format descriptor", 'Added\t8:30:00 PM*\tTRAINFORMAT\tFIELD_KEY="TRAIN_SYMBOL"', state, [])
    check("job dump record", 'Added\t8:30:00 PM*\tJOBDATA\tJOB_NAME="Local1"', state, [])
    check("crew dump record", 'Added\t8:30:00 PM*\tCREWDATA\tCREW_NAME="Aaron S"', state, [])

    # Store dump: TRAINDATA Added record refreshes consist/crew topics.
    check(
        "dump TRAINDATA",
        'Added\t8:30:00 PM*\tTRAINDATA\tTRAIN_SYMBOL="1905"\tENGINE="603(F)"\tCREW=""\tEDIT_STATUS="UNCHANGED"',
        state,
        [
            ("trains/train/1905/consist", "603(F)", True),
            ("trains/train/1905/crew", "", True),
        ],
    )

    # Move with coordinates, fast-clock timestamp (*); no prior location -> no clear.
    check(
        "move with coords, fast clock",
        'Move:\t8:35:52 PM*\t"1905"\t"Springville"\tto\t"Cedar Rapids"\t"(3,4):N"',
        state,
        [("trains/location/Cedar Rapids", "1905", True)],
    )

    # Move without coordinates, real-clock timestamp (space); prior location present -> clear.
    check(
        "move without coords, real clock",
        'Move:\t8:36:10 PM \t"1905"\t"Cedar Rapids"\tto\t"Marion"',
        state,
        [
            ("trains/location/Cedar Rapids", "", True),
            ("trains/location/Marion", "1905", True),
        ],
    )

    # Assign a crew.
    check(
        "assign",
        'Assign:\t8:40:00 PM*\t"Aaron S"\trunning\t"1905"',
        state,
        [("trains/crew/Aaron_S", "1905", True)],
    )

    # Assign-nothing: crew goes off duty.
    check(
        "assign nothing",
        'Assign:\t8:55:00 PM*\t"Aaron S"\trunning\t"nothing"',
        state,
        [("trains/crew/Aaron_S", "", True)],
    )

    # Changed with CREW only.
    check(
        "changed crew",
        'Changed\t9:00:00 PM*\tTRAINDATA\tTRAIN_SYMBOL="1905"\tCREW="Aaron S"\tONDUTY="20:42"',
        state,
        [
            ("trains/train/1905/crew", "Aaron S", True),
            ("trains/crew/Aaron_S", "1905", True),
        ],
    )

    # Changed with ENGINE only.
    check(
        "changed engine",
        'Changed\t9:05:00 PM*\tTRAINDATA\tTRAIN_SYMBOL="1905"\tENGINE="603(F) + 2203(R)"\tEDIT_STATUS="CHANGED"',
        state,
        [("trains/train/1905/consist", "603(F) + 2203(R)", True)],
    )

    # Changed with both CREW and ENGINE; reassigning crew clears the old crew topic.
    check(
        "changed both",
        'Changed\t9:10:00 PM*\tTRAINDATA\tTRAIN_SYMBOL="1905"\tENGINE="603(F)"\tCREW="Pat L"',
        state,
        [
            ("trains/train/1905/consist", "603(F)", True),
            ("trains/train/1905/crew", "Pat L", True),
            ("trains/crew/Aaron_S", "", True),
            ("trains/crew/Pat_L", "1905", True),
        ],
    )

    # Terminated: clears consist, crew, and location.
    check(
        "terminated",
        'Terminated:\t9:30:00 PM*\t"1905"\tTERMINATED\t"(3,4)"\ttrue\tlabel exists',
        state,
        [
            ("trains/train/1905/consist", "", True),
            ("trains/train/1905/crew", "", True),
            ("trains/location/Marion", "", True),
            ("trains/crew/Pat_L", "", True),
        ],
    )

    # Seed a second train, then tie it down.
    check(
        "move for tiedown train",
        'Move:\t9:00:00 PM \t"1142"\t"unknown"\tto\t"Blairstown"',
        state,
        [("trains/location/Blairstown", "1142", True)],
    )
    check(
        "tied down",
        'TiedDown:\t9:35:00 PM \t"1142"\tTIED_DOWN\t"(1,2)"\tfalse\tlabel lost',
        state,
        [
            ("trains/train/1142/consist", "", True),
            ("trains/train/1142/crew", "", True),
            ("trains/location/Blairstown", "", True),
        ],
    )

    # Seed a third train, then delete its TRAINDATA record.
    check(
        "move for deleted train",
        'Move:\t9:38:00 PM \t"77"\t"unknown"\tto\t"Anamosa"',
        state,
        [("trains/location/Anamosa", "77", True)],
    )
    check(
        "deleted traindata",
        'Deleted\t9:40:00 PM \tTRAINDATA\tTRAIN_SYMBOL="77"',
        state,
        [
            ("trains/train/77/consist", "", True),
            ("trains/train/77/crew", "", True),
            ("trains/location/Anamosa", "", True),
        ],
    )

    # Rerun is a no-op.
    check("rerun", 'Rerun:\t9:41:00 PM \t"77"', state, [])

    # Disconnect flags the harness to reconnect, publishes nothing.
    check("disconnect", "Disconnect", state, [])
    assert state['disconnect'] is True
    del state['disconnect']

    # Garbage lines never raise and never publish.
    check("garbage no tabs", "this is not a valid TrainStat line", state, [])
    check("garbage unknown tag", "Foo:\tbar\tbaz", state, [])


def test_location_map_guard():
    """A stale departure for train A must not clear a station now held by train B."""
    state = {}

    # A moves in to X.
    check("A to X", 'Move:\t1:00:00 PM*\t"A1"\t"Start"\tto\t"X"', state,
          [("trains/location/X", "A1", True)])

    # A moves on to Y -- this legitimately clears X.
    check("A to Y", 'Move:\t1:05:00 PM*\t"A1"\t"X"\tto\t"Y"', state,
          [("trains/location/X", "", True), ("trains/location/Y", "A1", True)])

    # B moves in to X.
    check("B to X", 'Move:\t1:06:00 PM*\t"B1"\t"Start2"\tto\t"X"', state,
          [("trains/location/X", "B1", True)])

    # A stale replay of "A departs X arrives Y" must not clear X (B is there now),
    # because the location map no longer attributes X to A.
    check("stale A departure replay", 'Move:\t1:05:00 PM*\t"A1"\t"X"\tto\t"Y"', state,
          [("trains/location/Y", "A1", True)])


if __name__ == '__main__':
    test_transcript()
    test_location_map_guard()
    print("test_parser.py: OK")
