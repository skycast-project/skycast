"""Сущности-датчики SKYCAST."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SkycastCoordinator
from . import SkycastConfigEntry


def _day_value(data: dict, idx: int, kind: str):
    """Значение дневного прогноза: idx 0..4, kind max/min/pop."""
    days = (data.get("weather") or {}).get("days") or []
    if idx >= len(days):
        return None
    day = days[idx] or {}
    return day.get("tmax" if kind == "max" else "tmin" if kind == "min" else "pop")


@dataclass(frozen=True, kw_only=True)
class SkycastSensor(SensorEntityDescription):
    value: Callable[[dict], float | int | None]
    attrs: Callable[[dict], dict] | None = None


def _w(data: dict) -> dict:
    return data.get("weather") or {}


DESCRIPTIONS: tuple[SkycastSensor, ...] = (
    SkycastSensor(
        key="temp", name="Температура улицы", native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: _w(d).get("temp")),
    SkycastSensor(
        key="feels", name="Ощущается", native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: _w(d).get("feels")),
    SkycastSensor(
        key="humidity", name="Влажность улицы", native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY, state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: _w(d).get("humidity")),
    SkycastSensor(
        key="pressure", name="Давление", native_unit_of_measurement="мм рт. ст.",
        device_class=SensorDeviceClass.PRESSURE, state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: _w(d).get("pressure_mmhg")),
    SkycastSensor(
        key="wind", name="Ветер", native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        device_class=SensorDeviceClass.WIND_SPEED, state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: _w(d).get("wind_ms")),
    SkycastSensor(
        key="wind_dir", name="Направление ветра", native_unit_of_measurement="°",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: _w(d).get("wind_deg")),
    SkycastSensor(
        key="clouds", name="Облачность", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: _w(d).get("clouds")),
    SkycastSensor(
        key="pop", name="Вероятность осадков", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: _w(d).get("pop_now")),
    SkycastSensor(
        key="condition", name="Состояние", icon="mdi:weather-partly-cloudy",
        value=lambda d: _w(d).get("desc")),
)

HOME_DESCRIPTIONS: tuple[SkycastSensor, ...] = (
    SkycastSensor(
        key="home_temp", name="Температура дома", native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: ((d.get("sensors") or {}).get("home") or {}).get("temp")),
    SkycastSensor(
        key="home_humidity", name="Влажность дома", native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY, state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: ((d.get("sensors") or {}).get("home") or {}).get("humidity")),
    SkycastSensor(
        key="home_pressure", name="Давление дома", native_unit_of_measurement=UnitOfPressure.HPA,
        device_class=SensorDeviceClass.PRESSURE, state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: ((d.get("sensors") or {}).get("home") or {}).get("pressure_hpa")),
)


def _bus(data: dict) -> list[dict]:
    return (data.get("bus") or [])


def _bus_live(data: dict) -> list[dict]:
    items = [b for b in _bus(data) if isinstance(b.get("min"), (int, float)) and b["min"] >= 0]
    return sorted(items, key=lambda b: b["min"])


def _bus_nearest(data: dict) -> dict | None:
    items = _bus_live(data)
    return items[0] if items else None


def _bus_next_time(data: dict):
    b = _bus_nearest(data)
    nxt = (b or {}).get("next") or []
    return nxt[1] if len(nxt) > 1 else (nxt[0] if nxt else None)


def _bus_attrs(data: dict) -> dict:
    items = _bus_live(data)
    return {
        "stops": data.get("bus_stops") or [],
        "routes": [
            f'{b.get("num")} → {b.get("dest")}: через {b.get("min")} мин ({b.get("at")})'
            for b in items
        ],
        "count": len(items),
    }


BUS_DESCRIPTIONS: tuple[SkycastSensor, ...] = (
    SkycastSensor(
        key="bus_min", name="Транспорт: через", native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION, icon="mdi:bus-clock",
        value=lambda d: (_bus_nearest(d) or {}).get("min"), attrs=_bus_attrs),
    SkycastSensor(
        key="bus_route", name="Транспорт: маршрут", icon="mdi:bus",
        value=lambda d: (_bus_nearest(d) or {}).get("num")),
    SkycastSensor(
        key="bus_dest", name="Транспорт: направление", icon="mdi:map-marker-path",
        value=lambda d: (_bus_nearest(d) or {}).get("dest")),
    SkycastSensor(
        key="bus_stop", name="Транспорт: остановка", icon="mdi:bus-stop",
        value=lambda d: (_bus_nearest(d) or {}).get("stop")),
    SkycastSensor(
        key="bus_at", name="Транспорт: время", icon="mdi:clock-outline",
        value=lambda d: (_bus_nearest(d) or {}).get("at")),
    SkycastSensor(
        key="bus_next", name="Транспорт: следующий", icon="mdi:clock-fast",
        value=_bus_next_time),
    SkycastSensor(
        key="bus_count", name="Транспорт: рейсов в пути", icon="mdi:bus-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: len(_bus_live(d))),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SkycastConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    device = DeviceInfo(
        identifiers={(DOMAIN, coordinator.host)},
        name=coordinator.station_name,
        manufacturer="DIY",
        model="ESP32-S3 Sunton 7 inch",
        configuration_url=coordinator.base_url,
    )

    entities: list[SkycastEntity] = [
        SkycastEntity(coordinator, d, device) for d in DESCRIPTIONS + HOME_DESCRIPTIONS + BUS_DESCRIPTIONS
    ]

    for item in ((coordinator.data or {}).get("sensors") or {}).get("list") or []:
        sid = item.get("id")
        if not sid:
            continue
        label = item.get("label") or sid
        entities.append(SkycastEntity(
            coordinator,
            SkycastSensor(
                key=f"{sid}_temp", name=f"{label}: температура",
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                device_class=SensorDeviceClass.TEMPERATURE,
                state_class=SensorStateClass.MEASUREMENT,
                value=(lambda k: lambda d: next(
                    (i.get("temp") for i in ((d.get("sensors") or {}).get("list") or []) if i.get("id") == k),
                    None))(sid)),
            device))
        entities.append(SkycastEntity(
            coordinator,
            SkycastSensor(
                key=f"{sid}_humidity", name=f"{label}: влажность",
                native_unit_of_measurement=PERCENTAGE,
                device_class=SensorDeviceClass.HUMIDITY,
                state_class=SensorStateClass.MEASUREMENT,
                value=(lambda k: lambda d: next(
                    (i.get("humidity") for i in ((d.get("sensors") or {}).get("list") or []) if i.get("id") == k),
                    None))(sid)),
            device))

    # прогноз на 5 дней: макс/мин/осадки по каждому дню
    for i in range(5):
        for kind, name, unit, cls in (
            ("max", "макс", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
            ("min", "мин", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
            ("pop", "осадки", PERCENTAGE, None),
        ):
            entities.append(SkycastEntity(
                coordinator,
                SkycastSensor(
                    key=f"day{i}_{kind}",
                    name=f"Прогноз {i + 1}: {name}",
                    native_unit_of_measurement=unit,
                    device_class=cls,
                    state_class=SensorStateClass.MEASUREMENT,
                    value=(lambda idx, k: lambda d: _day_value(d, idx, k))(i, kind),
                ),
                device))

    async_add_entities(entities)


class SkycastEntity(CoordinatorEntity[SkycastCoordinator], SensorEntity):
    """Одна сущность станции."""

    _attr_has_entity_name = False

    def __init__(self, coordinator: SkycastCoordinator, description: SkycastSensor, device: DeviceInfo) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{coordinator.host}_{description.key}"
        self._attr_device_info = device

    @property
    def native_value(self):
        try:
            return self.entity_description.value(self.coordinator.data or {})
        except Exception:  # noqa: BLE001
            return None

    @property
    def extra_state_attributes(self):
        if not self.entity_description.attrs:
            return None
        try:
            return self.entity_description.attrs(self.coordinator.data or {})
        except Exception:  # noqa: BLE001
            return None
