from lmu_ep_client.detector import StintDetector, TickData


def _make_tick(
    *,
    game_phase: int = 5,
    session_type: int = 5,
    track: str = "Monza",
    elapsed: float = 0.0,
    driver: str = "Player",
    vehicle: str = "Porsche 963",
    vehicle_model: str = "Porsche 963",
    vehicle_class: str = "Hypercar",
    pit_state: int = 0,
    total_laps: int = 0,
    fuel: float = 110.0,
    fuel_capacity: float = 110.0,
    virtual_energy: float = 100.0,
    wheels: list | None = None,
    dent_severity: list | None = None,
) -> TickData:
    if wheels is None:
        wheels = [
            {"wear": 1.0, "compound_type": 2, "flat": False, "detached": False}
            for _ in range(4)
        ]
    if dent_severity is None:
        dent_severity = [0] * 8
    return TickData(
        game_phase=game_phase,
        session_type=session_type,
        track=track,
        elapsed=elapsed,
        driver=driver,
        vehicle=vehicle,
        vehicle_model=vehicle_model,
        vehicle_class=vehicle_class,
        pit_state=pit_state,
        total_laps=total_laps,
        fuel=fuel,
        fuel_capacity=fuel_capacity,
        virtual_energy=virtual_energy,
        wheels=wheels,
        dent_severity=dent_severity,
    )


def test_session_start_detected():
    det = StintDetector()
    events = det.update(_make_tick(game_phase=5, elapsed=10.0))
    assert "session_start" in events
    assert det.session is not None
    assert det.session.track == "Monza"


def test_session_start_uses_vehicle_model():
    det = StintDetector()
    det.update(_make_tick(
        game_phase=5,
        vehicle="Team Entry Name",
        vehicle_model="Aston Martin Vantage AMR LMGT3",
    ))
    assert det.session.vehicle == "Aston Martin Vantage AMR LMGT3"


def test_no_session_in_garage():
    det = StintDetector()
    events = det.update(_make_tick(game_phase=0))
    assert "session_start" not in events
    assert det.session is None


def test_full_pit_cycle():
    det = StintDetector()

    # Start session
    det.update(_make_tick(game_phase=5, elapsed=0.0, total_laps=0))

    # Drive some laps
    det.update(_make_tick(elapsed=300.0, total_laps=5))

    # Enter pit
    events = det.update(_make_tick(elapsed=600.0, pit_state=2, total_laps=10, fuel=50.0, virtual_energy=40.0))
    assert "pit_enter" in events

    # Pit stopped
    det.update(_make_tick(elapsed=612.0, pit_state=3, total_laps=10, fuel=50.0, virtual_energy=40.0))

    # Pit exiting
    fresh_wheels = [
        {"wear": 1.0, "compound_type": 0, "flat": False, "detached": False}
        for _ in range(4)
    ]
    det.update(_make_tick(
        elapsed=635.0,
        pit_state=4,
        total_laps=10,
        fuel=110.0,
        virtual_energy=100.0,
        wheels=fresh_wheels,
    ))

    # Back on track — this is when the stint finalizes
    events = det.update(_make_tick(
        elapsed=640.0,
        pit_state=0,
        total_laps=10,
        fuel=110.0,
        virtual_energy=100.0,
        wheels=fresh_wheels,
    ))
    assert "pit_exit" in events
    assert len(det.stints) == 1

    stint = det.stints[0]
    assert stint.stint_number == 1
    assert stint.start_lap == 0
    assert stint.end_lap == 10
    assert stint.fuel.start_litres == 110.0
    assert stint.fuel.end_litres == 50.0

    pit = stint.pit_stop
    assert pit is not None
    assert pit.pit_enter_elapsed == 600.0
    assert pit.pit_stand_elapsed == 612.0
    assert pit.fuel_added_litres == 60.0
    assert pit.energy_added_percent == 60.0
    assert pit.driver_change is False

    # All tires changed (Hard -> Soft, wear reset)
    for pos in ["FL", "FR", "RL", "RR"]:
        assert pit.tyres[pos].changed is True
        assert pit.tyres[pos].old_compound == "Hard"
        assert pit.tyres[pos].new_compound == "Soft"


def test_pit_cycle_without_exiting_state():
    """LMU may skip the EXITING(4) state entirely — going straight from STOPPED(3) to NONE(0)."""
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0))

    # Enter pit
    det.update(_make_tick(elapsed=600.0, pit_state=2, total_laps=10, fuel=50.0))
    # Stopped
    det.update(_make_tick(elapsed=612.0, pit_state=3, total_laps=10, fuel=50.0))
    # Jump straight to on track (no state 4)
    events = det.update(_make_tick(elapsed=635.0, pit_state=0, total_laps=10, fuel=110.0))

    assert "pit_exit" in events
    assert len(det.stints) == 1
    assert det.stints[0].pit_stop is not None


def test_driver_change_detection():
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0, driver="Driver A"))

    # Enter pit as Driver A
    det.update(_make_tick(elapsed=600.0, pit_state=2, total_laps=10, fuel=50.0, driver="Driver A"))
    det.update(_make_tick(elapsed=612.0, pit_state=3, total_laps=10, fuel=50.0, driver="Driver A"))

    # Back on track as Driver B (skip EXITING state)
    events = det.update(_make_tick(elapsed=640.0, pit_state=0, total_laps=10, fuel=110.0, driver="Driver B"))

    assert "pit_exit" in events
    assert len(det.stints) == 1
    pit = det.stints[0].pit_stop
    assert pit is not None
    assert pit.driver_change is True
    assert pit.new_driver == "Driver B"


def test_repair_detection():
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0))

    # Enter pit with damage
    det.update(_make_tick(elapsed=600.0, pit_state=2, total_laps=10, fuel=50.0, dent_severity=[0, 2, 1, 0, 0, 0, 0, 0]))
    det.update(_make_tick(elapsed=612.0, pit_state=3, total_laps=10, fuel=50.0, dent_severity=[0, 2, 1, 0, 0, 0, 0, 0]))

    # Exit pit with damage repaired
    det.update(_make_tick(elapsed=650.0, pit_state=0, total_laps=10, fuel=110.0, dent_severity=[0, 0, 0, 0, 0, 0, 0, 0]))

    pit = det.stints[0].pit_stop
    assert pit is not None
    assert pit.repair_flag is True


def test_no_repair_when_no_damage_change():
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0))
    det.update(_make_tick(elapsed=600.0, pit_state=2, total_laps=10, fuel=50.0))
    det.update(_make_tick(elapsed=612.0, pit_state=3, total_laps=10, fuel=50.0))
    det.update(_make_tick(elapsed=635.0, pit_state=0, total_laps=10, fuel=110.0))

    pit = det.stints[0].pit_stop
    assert pit is not None
    assert pit.repair_flag is False


def test_session_end():
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0, total_laps=0))
    det.update(_make_tick(elapsed=600.0, total_laps=10, fuel=50.0, virtual_energy=40.0))

    events = det.update(_make_tick(game_phase=8, elapsed=610.0, total_laps=10, fuel=50.0, virtual_energy=40.0))
    assert "session_end" in events
    assert len(det.stints) == 1
    assert det.stints[0].pit_stop is None
    assert det.stints[0].end_lap == 10
    assert det.session is not None
    assert det.session.end_time != ""


def test_session_end_on_return_to_garage():
    """Practice/qualifying: quitting back to garage should end the session."""
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0, total_laps=0))
    det.update(_make_tick(elapsed=300.0, total_laps=5, fuel=80.0))

    events = det.update(_make_tick(game_phase=0, elapsed=310.0, total_laps=5, fuel=80.0))
    assert "session_end" in events
    assert len(det.stints) == 1


def test_finalize_on_shutdown():
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0, total_laps=0))
    tick = _make_tick(elapsed=600.0, total_laps=10, fuel=50.0, virtual_energy=40.0)
    det.update(tick)

    det.finalize_on_shutdown(tick)
    assert len(det.stints) == 1
    assert det.stints[0].end_lap == 10
    assert det.session.end_time != ""


def test_tire_not_changed_when_wear_similar():
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0))

    worn_wheels = [
        {"wear": 0.5, "compound_type": 2, "flat": False, "detached": False}
        for _ in range(4)
    ]
    det.update(_make_tick(elapsed=600.0, pit_state=2, total_laps=10, fuel=50.0, wheels=worn_wheels))
    det.update(_make_tick(elapsed=612.0, pit_state=3, total_laps=10, fuel=50.0, wheels=worn_wheels))

    # Back on track with same wear (no tire change, just fuel)
    det.update(_make_tick(elapsed=625.0, pit_state=0, total_laps=10, fuel=110.0, wheels=worn_wheels))

    pit = det.stints[0].pit_stop
    for pos in ["FL", "FR", "RL", "RR"]:
        assert pit.tyres[pos].changed is False
        assert pit.tyres[pos].old_wear == 0.5
        assert pit.tyres[pos].new_compound is None


def test_session_starts_in_pits_defers_stint():
    """Practice sessions start in the garage/pits — stint should only begin when car leaves pits."""
    det = StintDetector()

    # Session starts while car is in pit (pit_state=3 = STOPPED)
    events = det.update(_make_tick(game_phase=5, elapsed=0.0, pit_state=3))
    assert "session_start" in events
    assert det._current_stint_start is None  # stint deferred

    # Car leaves pits
    events = det.update(_make_tick(elapsed=10.0, pit_state=0, total_laps=0, fuel=110.0))
    assert "pit_exit" in events
    assert det._current_stint_start is not None  # stint started now

    # Drive some laps
    det.update(_make_tick(elapsed=300.0, total_laps=5, fuel=80.0))

    # End session
    events = det.update(_make_tick(game_phase=8, elapsed=600.0, total_laps=10, fuel=50.0))
    assert "session_end" in events
    assert len(det.stints) == 1
    assert det.stints[0].stint_number == 1
    assert det.stints[0].start_lap == 0
    assert det.stints[0].end_lap == 10
    assert det.stints[0].fuel.start_litres == 110.0
    assert det.stints[0].fuel.end_litres == 50.0


def test_session_starts_in_pits_full_pit_cycle():
    """Session starts in pits, car goes out, comes back for a pit stop, goes out again."""
    det = StintDetector()

    # Session starts in pits
    det.update(_make_tick(game_phase=5, elapsed=0.0, pit_state=3))

    # Leave pits
    det.update(_make_tick(elapsed=10.0, pit_state=0, total_laps=0, fuel=110.0))

    # Drive laps
    det.update(_make_tick(elapsed=300.0, total_laps=5, fuel=80.0))

    # Pit entry
    events = det.update(_make_tick(elapsed=600.0, pit_state=2, total_laps=10, fuel=50.0))
    assert "pit_enter" in events

    # Pit stopped
    det.update(_make_tick(elapsed=612.0, pit_state=3, total_laps=10, fuel=50.0))

    # Back on track
    events = det.update(_make_tick(elapsed=640.0, pit_state=0, total_laps=10, fuel=110.0))
    assert "pit_exit" in events
    assert len(det.stints) == 1
    assert det.stints[0].stint_number == 1
    assert det.stints[0].fuel.start_litres == 110.0
    assert det.stints[0].fuel.end_litres == 50.0
    assert det.stints[0].pit_stop is not None
    assert det.stints[0].pit_stop.fuel_added_litres == 60.0

    # End session
    events = det.update(_make_tick(game_phase=8, elapsed=900.0, total_laps=15, fuel=70.0))
    assert "session_end" in events
    assert len(det.stints) == 2
    assert det.stints[1].stint_number == 2
