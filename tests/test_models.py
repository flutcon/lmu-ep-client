from lmu_ep_client.models import (
    EnergyData,
    FuelData,
    PitStop,
    SessionData,
    Stint,
    TireInfo,
)


def test_tire_info_to_dict_changed():
    tire = TireInfo(
        changed=True,
        old_wear=0.72,
        old_compound="Hard",
        new_compound="Soft",
    )
    result = tire.to_dict()
    assert result == {
        "changed": True,
        "old_wear": 0.72,
        "old_compound": "Hard",
        "new_compound": "Soft",
    }


def test_tire_info_to_dict_not_changed():
    tire = TireInfo(
        changed=False,
        old_wear=0.45,
        old_compound="Hard",
        new_compound=None,
    )
    result = tire.to_dict()
    assert result == {
        "changed": False,
        "old_wear": 0.45,
        "old_compound": "Hard",
    }


def test_fuel_data_to_dict():
    fuel = FuelData(
        start_litres=110.0,
        end_litres=12.3,
        capacity=110.0,
    )
    result = fuel.to_dict()
    assert result == {
        "start_litres": 110.0,
        "end_litres": 12.3,
        "litres_used": 97.7,
        "litres_per_lap": None,
        "capacity": 110.0,
    }


def test_fuel_data_with_laps():
    fuel = FuelData(start_litres=110.0, end_litres=12.3, capacity=110.0)
    result = fuel.to_dict(total_laps=28)
    assert result["litres_per_lap"] == round(97.7 / 28, 2)


def test_energy_data_to_dict():
    energy = EnergyData(start_percent=100.0, end_percent=5.2)
    result = energy.to_dict()
    assert result == {
        "start_percent": 100.0,
        "end_percent": 5.2,
        "used_percent": 94.8,
        "percent_per_lap": None,
    }


def test_energy_data_with_laps():
    energy = EnergyData(start_percent=100.0, end_percent=5.2)
    result = energy.to_dict(total_laps=28)
    assert result["percent_per_lap"] == round(94.8 / 28, 2)


def test_pit_stop_to_dict():
    pit = PitStop(
        pit_enter_elapsed=3360.5,
        pit_stand_elapsed=3372.0,
        pit_depart_elapsed=3385.0,
        pit_exit_elapsed=3395.2,
        fuel_added_litres=97.7,
        energy_added_percent=94.8,
        repair_flag=False,
        driver_change=True,
        new_driver="TeammateName",
        tyres={
            "FL": TireInfo(changed=True, old_wear=0.72, old_compound="Hard", new_compound="Hard"),
            "FR": TireInfo(changed=False, old_wear=0.68, old_compound="Hard"),
        },
    )
    result = pit.to_dict()
    assert result["standing_time_seconds"] == round(3385.0 - 3372.0, 1)
    assert result["total_pit_time_seconds"] == round(3395.2 - 3360.5, 1)
    assert result["driver_change"] is True
    assert result["new_driver"] == "TeammateName"
    assert result["tyres"]["FL"]["changed"] is True
    assert result["tyres"]["FR"]["changed"] is False


def test_pit_stop_no_driver_change():
    pit = PitStop(
        pit_enter_elapsed=100.0,
        pit_stand_elapsed=110.0,
        pit_depart_elapsed=118.0,
        pit_exit_elapsed=125.0,
        fuel_added_litres=50.0,
        energy_added_percent=40.0,
        repair_flag=True,
        driver_change=False,
        new_driver=None,
        tyres={},
    )
    result = pit.to_dict()
    assert result["driver_change"] is False
    assert "new_driver" not in result
    assert result["repair_flag"] is True


def test_stint_to_dict_with_pit():
    stint = Stint(
        stint_number=1,
        driver="Player",
        start_lap=1,
        end_lap=29,
        start_time_elapsed=0.0,
        end_time_elapsed=3360.5,
        fuel=FuelData(start_litres=110.0, end_litres=12.3, capacity=110.0),
        energy=EnergyData(start_percent=100.0, end_percent=5.2),
        pit_stop=PitStop(
            pit_enter_elapsed=3360.5,
            pit_stand_elapsed=3372.0,
            pit_depart_elapsed=3385.0,
            pit_exit_elapsed=3395.2,
            fuel_added_litres=97.7,
            energy_added_percent=94.8,
            repair_flag=False,
            driver_change=False,
            new_driver=None,
            tyres={},
        ),
    )
    result = stint.to_dict()
    assert result["stint_number"] == 1
    assert result["total_laps"] == 28
    assert result["stint_duration_seconds"] == 3360.5
    assert result["fuel"]["litres_per_lap"] == round(97.7 / 28, 2)
    assert result["pit_stop"] is not None


def test_stint_to_dict_no_pit():
    stint = Stint(
        stint_number=2,
        driver="Player",
        start_lap=29,
        end_lap=45,
        start_time_elapsed=3395.2,
        end_time_elapsed=5300.0,
        fuel=FuelData(start_litres=110.0, end_litres=30.0, capacity=110.0),
        energy=EnergyData(start_percent=100.0, end_percent=20.0),
        pit_stop=None,
    )
    result = stint.to_dict()
    assert result["total_laps"] == 16
    assert result["pit_stop"] is None


def test_session_data_to_dict():
    session = SessionData(
        track="Le Mans 24h",
        session_type="Race",
        start_time="2026-04-02T18:30:00",
        end_time="2026-04-02T19:30:00",
        vehicle="Porsche 963",
        vehicle_class="Hypercar",
    )
    result = session.to_dict(stints=[])
    assert result["session"]["track"] == "Le Mans 24h"
    assert result["session"]["session_type"] == "Race"
    assert result["stints"] == []
