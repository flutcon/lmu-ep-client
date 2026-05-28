from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lmu_ep_client.detector import TickData
from lmu_ep_client.poller import (
    AmbiguousMatchError,
    JsonSink,
    PlayerSelector,
    POLL_INTERVAL,
    SessionRunner,
    SharedMemoryReader,
    TrackingApiSink,
    WAIT_RETRY_INTERVAL,
)


def _bytes(value: str, length: int = 64) -> bytes:
    return value.encode("utf-8")[:length].ljust(length, b"\x00")


def _wheel() -> SimpleNamespace:
    return SimpleNamespace(
        mWear=0.75,
        mCompoundIndex=2,
        mCompoundType=1,
        mFlat=False,
        mDetached=False,
    )


def _shared_memory_info(*, control: int = 0, fuel_fraction: int = 128) -> SimpleNamespace:
    scoring_info = SimpleNamespace(
        mNumVehicles=1,
        mGamePhase=5,
        mSession=10,
        mTrackName=_bytes("Le Mans"),
        mCurrentET=123.4,
        mLapDist=5000.0,
    )
    vehicle_scoring = SimpleNamespace(
        mID=42,
        mDriverName=_bytes("Alex"),
        mVehicleName=_bytes("Porsche Penske #6"),
        mVehicleClass=_bytes("Hypercar"),
        mPitState=0,
        mTotalLaps=7,
        mLapDist=1234.5,
        mLastLapTime=124.318,
        mFuelFraction=fuel_fraction,
        mFinishStatus=0,
        mPitGroup=_bytes("Penske"),
        mControl=control,
        mIsPlayer=True,
    )
    vehicle_telemetry = SimpleNamespace(
        mID=42,
        mVehicleModel=_bytes("Porsche 963", 30),
        mFuel=61.0,
        mFuelCapacity=100.0,
        mVirtualEnergy=0.42,
        mDentSeverity=[0, 1, 0, 0, 0, 0, 0, 0],
        mLocalVel=SimpleNamespace(x=3.0, y=4.0, z=0.0),
        mWheels=[_wheel(), _wheel(), _wheel(), _wheel()],
    )
    return SimpleNamespace(
        LMUData=SimpleNamespace(
            scoring=SimpleNamespace(
                scoringInfo=scoring_info,
                vehScoringInfo=[vehicle_scoring],
            ),
            telemetry=SimpleNamespace(telemInfo=[vehicle_telemetry]),
        ),
        close=lambda: None,
    )


def _tick(**overrides) -> TickData:
    data = dict(
        game_phase=5,
        session_type=10,
        track="Le Mans",
        elapsed=1.0,
        driver="Alex",
        vehicle="Porsche Penske #6",
        vehicle_model="Porsche 963",
        vehicle_class="Hypercar",
        pit_state=0,
        total_laps=0,
        lap_distance=0.0,
        track_length=5000.0,
        last_lap_time=124.318,
        fuel=100.0,
        fuel_capacity=100.0,
        virtual_energy=100.0,
        wheels=[
            {"wear": 1.0, "compound_index": 0, "compound_type": 2, "flat": False, "detached": False}
            for _ in range(4)
        ],
        dent_severity=[0] * 8,
        finish_status=0,
        speed=0.0,
        team="Penske",
        control=0,
    )
    data.update(overrides)
    return TickData(**data)


def test_player_selector_reports_ambiguous_team_matches():
    first = SimpleNamespace(mID=41, mVehicleName=_bytes("Porsche Penske #5"), mDriverName=_bytes("A"), mIsPlayer=False)
    second = SimpleNamespace(mID=42, mVehicleName=_bytes("Porsche Penske #6"), mDriverName=_bytes("B"), mIsPlayer=False)
    info = SimpleNamespace(
        LMUData=SimpleNamespace(
            scoring=SimpleNamespace(
                scoringInfo=SimpleNamespace(mNumVehicles=2),
                vehScoringInfo=[first, second],
            )
        )
    )

    with pytest.raises(AmbiguousMatchError) as exc:
        PlayerSelector(team_name="Penske").select(info)

    assert "slot 41" in str(exc.value)
    assert "slot 42" in str(exc.value)


def test_shared_memory_reader_uses_networked_fuel_fraction_for_remote_control():
    info = _shared_memory_info(control=2, fuel_fraction=64)
    reader = SharedMemoryReader(sim_info_factory=lambda: info)

    assert reader.connect() is True
    tick = reader.read_tick(42)

    assert tick is not None
    assert tick.fuel == pytest.approx((64 / 255.0) * 100.0)
    assert tick.speed == pytest.approx(5.0)
    assert tick.vehicle_model == "Porsche 963"
    assert tick.last_lap_time == 124.318
    assert tick.lap_distance == 1234.5
    assert tick.track_length == 5000.0


class _Reader:
    def __init__(self, *, connected: bool = True, ticks: list[TickData] | None = None) -> None:
        self.connected = connected
        self.ticks = ticks or []
        self.closed = False
        self.read_player_ids: list[int] = []

    def connect(self) -> bool:
        return self.connected

    def read_tick(self, player_id: int) -> TickData | None:
        self.read_player_ids.append(player_id)
        return self.ticks.pop(0) if self.ticks else None

    def close(self) -> None:
        self.closed = True


class _Selector:
    def __init__(self, player_id: int | None) -> None:
        self.player_id = player_id

    def select(self, info) -> int | None:
        return self.player_id

    def waiting_message(self) -> str | None:
        return "Waiting for fake player..."


class _Sink:
    def __init__(self) -> None:
        self.events: list[set[str]] = []
        self.periodic_calls = 0
        self.shutdown_called = False

    def on_events(self, events: set[str], tick: TickData, detector) -> None:
        self.events.append(set(events))

    def periodic(self, detector) -> None:
        self.periodic_calls += 1

    def on_shutdown(self, detector, last_tick: TickData | None) -> None:
        self.shutdown_called = True


def test_session_runner_step_waits_when_shared_memory_is_unavailable():
    logs: list[str] = []
    runner = SessionRunner(
        reader=_Reader(connected=False),
        selector=_Selector(player_id=42),
        sinks=[],
        log=logs.append,
    )

    assert runner.step() == WAIT_RETRY_INTERVAL
    assert logs == ["LMU not detected. Retrying..."]


def test_session_runner_step_processes_detector_events_without_sleeping():
    sink = _Sink()
    logs: list[str] = []
    reader = _Reader(ticks=[_tick()])
    runner = SessionRunner(
        reader=reader,
        selector=_Selector(player_id=42),
        sinks=[sink],
        log=logs.append,
    )

    assert runner.step() == POLL_INTERVAL

    assert reader.read_player_ids == [42]
    assert sink.events == [{"session_start"}]
    assert sink.periodic_calls == 1
    assert "Player car identified (slot ID 42)" in logs
    assert any("Session detected: Le Mans" in msg for msg in logs)


def test_session_runner_run_injects_sleep_and_closes_reader_on_shutdown():
    sleeps: list[float] = []
    sink = _Sink()
    reader = _Reader(ticks=[_tick()])

    class StopAfterOneSleep:
        def is_set(self) -> bool:
            return bool(sleeps)

    runner = SessionRunner(
        reader=reader,
        selector=_Selector(player_id=42),
        sinks=[sink],
        sleep=sleeps.append,
        log=lambda msg: None,
    )

    runner.run(stop_event=StopAfterOneSleep())

    assert sleeps == [POLL_INTERVAL]
    assert sink.shutdown_called is True
    assert reader.closed is True


def test_json_sink_flushes_session_end(tmp_path: Path):
    sink = JsonSink(output_dir=tmp_path, monotonic=lambda: 0.0)
    reader = _Reader(ticks=[_tick(), _tick(game_phase=8, elapsed=10.0, total_laps=3, fuel=70.0)])
    runner = SessionRunner(
        reader=reader,
        selector=_Selector(player_id=42),
        sinks=[sink],
        sleep=lambda seconds: None,
        log=lambda msg: None,
    )

    runner.step()
    runner.step()

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1


def test_tracking_api_sink_ends_session_on_normal_session_end():
    publisher = MagicMock()
    sink = TrackingApiSink(publisher)

    sink.on_events({"session_end"}, _tick(driver="Alex", finish_status=2, elapsed=42.5), SimpleNamespace())

    publisher.driver_stopped.assert_called_once_with("Alex", meta={"finish_status": "dnf"}, et_seconds=42.5)
    publisher.end_session.assert_called_once_with()


def test_tracking_api_sink_ends_active_session_on_shutdown():
    publisher = MagicMock()
    sink = TrackingApiSink(publisher)

    sink.on_shutdown(SimpleNamespace(session=object()), _tick(driver="Alex"))

    publisher.end_session.assert_called_once_with()


def test_tracking_api_sink_attaches_local_snapshot_to_box_and_departure_events():
    publisher = MagicMock()
    sink = TrackingApiSink(publisher)
    tick = _tick(
        fuel=72.345,
        virtual_energy=54.321,
        wheels=[
            {"wear": 0.81234, "compound_index": 0, "compound_type": 2, "flat": False, "detached": False},
            {"wear": 0.79876, "compound_index": 0, "compound_type": 2, "flat": False, "detached": False},
            {"wear": 0.84567, "compound_index": 0, "compound_type": 2, "flat": False, "detached": False},
            {"wear": 0.82345, "compound_index": 0, "compound_type": 2, "flat": False, "detached": False},
        ],
        control=0,
    )

    sink.on_events({"pit_at_box", "pit_departed"}, tick, SimpleNamespace())

    expected_meta = {
        "fuel_litres": 72.34,
        "energy_percent": 54.32,
        "tyre_wear": {
            "FL": 0.8123,
            "FR": 0.7988,
            "RL": 0.8457,
            "RR": 0.8235,
        },
    }
    publisher.pit_at_box.assert_called_once_with(
        meta=expected_meta, et_seconds=1.0, lmu_driver_name="Alex"
    )
    publisher.pit_departed.assert_called_once_with(
        meta=expected_meta, et_seconds=1.0, lmu_driver_name="Alex"
    )


def test_tracking_api_sink_omits_snapshot_when_remote_driver_controls_car():
    publisher = MagicMock()
    sink = TrackingApiSink(publisher)
    tick = _tick(control=2)

    sink.on_events({"pit_at_box", "pit_departed"}, tick, SimpleNamespace())

    publisher.pit_at_box.assert_called_once_with(
        meta=None, et_seconds=1.0, lmu_driver_name="Alex"
    )
    publisher.pit_departed.assert_called_once_with(
        meta=None, et_seconds=1.0, lmu_driver_name="Alex"
    )


def test_tracking_api_sink_emits_lap_completed_with_local_practice_telemetry():
    publisher = MagicMock()
    publisher.resolve_driver.return_value = "m1"
    publisher.is_practice = True
    sink = TrackingApiSink(publisher)
    tick = _tick(
        driver="Alex",
        last_lap_time=124.318,
        fuel=48.456,
        virtual_energy=73.234,
        wheels=[
            {"wear": 0.9244, "compound_index": 0, "compound_type": 2, "flat": False, "detached": False},
            {"wear": 0.9171, "compound_index": 0, "compound_type": 2, "flat": False, "detached": False},
            {"wear": 0.8704, "compound_index": 0, "compound_type": 2, "flat": False, "detached": False},
            {"wear": 0.8655, "compound_index": 0, "compound_type": 2, "flat": False, "detached": False},
        ],
        control=0,
    )

    sink.on_events({"lap_completed"}, tick, SimpleNamespace())

    publisher.lap_completed.assert_called_once_with(
        lap_time_seconds=124.318,
        tyre_wear={"fl": 92.44, "fr": 91.71, "rl": 87.04, "rr": 86.55},
        energy_pct=73.23,
        fuel_litres=48.46,
        team_member_id="m1",
        et_seconds=1.0,
    )


def test_tracking_api_sink_uses_elapsed_delta_when_last_lap_time_is_unavailable():
    publisher = MagicMock()
    publisher.resolve_driver.return_value = "m1"
    publisher.is_practice = True
    sink = TrackingApiSink(publisher)

    sink.on_events({"session_start"}, _tick(elapsed=10.0, total_laps=0), SimpleNamespace())
    tick = _tick(
        elapsed=135.4321,
        total_laps=1,
        last_lap_time=0.0,
        fuel=48.456,
        virtual_energy=73.234,
        control=0,
    )

    sink.on_events({"lap_completed"}, tick, SimpleNamespace())

    publisher.lap_completed.assert_called_once()
    assert publisher.lap_completed.call_args.kwargs["lap_time_seconds"] == 125.432


def test_tracking_api_sink_skips_lap_completed_when_remote_driver_controls_car():
    publisher = MagicMock()
    publisher.is_practice = True
    sink = TrackingApiSink(publisher)

    sink.on_events({"lap_completed"}, _tick(control=2), SimpleNamespace())

    publisher.lap_completed.assert_not_called()
