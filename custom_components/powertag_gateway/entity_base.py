import logging
from enum import Enum

from homeassistant.helpers.entity import Entity, DeviceInfo

from .const import GATEWAY_DOMAIN, TAG_DOMAIN
from .schneider_modbus import SchneiderModbus, Phase, LineVoltage, PhaseSequence, ProductType

_LOGGER = logging.getLogger(__name__)


def gateway_device_info(client: SchneiderModbus, presentation_url: str) -> DeviceInfo:
    return DeviceInfo(
        configuration_url=presentation_url,
        identifiers={(GATEWAY_DOMAIN, client.serial_number())},
        hw_version=client.hardware_version(),
        sw_version=client.firmware_version(),
        manufacturer=client.manufacturer(),
        model=client.product_code(),
        name=client.name(),
        serial_number=client.serial_number()
    )


def tag_device_info(client: SchneiderModbus, modbus_index: int, presentation_url: str,
                    gateway_identification: tuple[str, str]) -> DeviceInfo:
    is_unreachable = client.tag_radio_lqi_gateway(modbus_index) is None
    serial_number = client.tag_serial_number(modbus_index)

    kwargs = {
        'configuration_url': presentation_url,
        'via_device': gateway_identification,
        'identifiers': {(TAG_DOMAIN, serial_number)},
        'serial_number': serial_number,
        'hw_version': client.tag_hardware_revision(modbus_index),
        'sw_version': client.tag_firmware_revision(modbus_index),
        'manufacturer': client.tag_vendor_name(modbus_index),
        'model': client.tag_product_model(modbus_index),
        'name': client.tag_name(modbus_index)
    }
    if not is_unreachable:
        kwargs['suggested_area'] = client.tag_usage(modbus_index).name

    if not is_unreachable and logging.DEBUG >= _LOGGER.level:
        position = client.tag_position(modbus_index)
        power_supply_type = client.tag_power_supply_type(modbus_index)
        rated_current = client.tag_rated_current(modbus_index)
        rated_voltage = client.tag_rated_voltage(modbus_index)
        circuit_diagnostic = client.tag_circuit_diagnostic(modbus_index)
        circuit = client.tag_circuit(modbus_index)
        product_code = client.tag_product_code(modbus_index)
        phase_sequence = client.tag_phase_sequence(modbus_index)
        family = client.tag_product_family(modbus_index)

        _LOGGER.debug(f"Found new device: name {kwargs['name']}, circuit {circuit}, rated voltage {rated_voltage}, "
                      f"rated current {rated_current}, position {position}, phase_sequence {phase_sequence}, "
                      f"family {family}, model {kwargs['model']}, product_code {product_code}, "
                      f" power_supply_type {power_supply_type}, circuit_diagnostic {circuit_diagnostic}, "
                      f"S/N {kwargs['serial_number']}")

    return DeviceInfo(kwargs)


def phase_sequence_to_phases(phase_sequence: PhaseSequence) -> [Phase]:
    return {
        PhaseSequence.A: [Phase.A],
        PhaseSequence.B: [Phase.B],
        PhaseSequence.C: [Phase.C],
        PhaseSequence.ABC: [Phase.A, Phase.B, Phase.C],
        PhaseSequence.ACB: [Phase.A, Phase.C, Phase.B],
        PhaseSequence.BAC: [Phase.B, Phase.A, Phase.C],
        PhaseSequence.BCA: [Phase.B, Phase.C, Phase.A],
        PhaseSequence.CAB: [Phase.C, Phase.A, Phase.B],
        PhaseSequence.CBA: [Phase.C, Phase.B, Phase.A],
        PhaseSequence.INVALID: []
    }[phase_sequence]


class FeatureClass(Enum):
    A1 = [ProductType.A9MEM1520, ProductType.A9MEM1521, ProductType.A9MEM1522, ProductType.A9MEM1541,
          ProductType.A9MEM1542]
    A2 = [ProductType.A9MEM1540, ProductType.A9MEM1543]
    P1 = [ProductType.A9MEM1561, ProductType.A9MEM1562, ProductType.A9MEM1563, ProductType.A9MEM1571,
          ProductType.A9MEM1572]
    F1 = [ProductType.A9MEM1560, ProductType.A9MEM1570]
    F2 = [ProductType.A9MEM1573]
    F3 = [ProductType.A9MEM1564, ProductType.A9MEM1574]
    FL = [ProductType.A9MEM1580]
    MV = [ProductType.LV434020]
    M1 = [ProductType.LV434021]
    M2 = [ProductType.LV434022]
    M3 = [ProductType.LV434023]
    R1 = [ProductType.A9MEM1590, ProductType.A9MEM1591, ProductType.A9MEM1592, ProductType.A9MEM1593]


def is_powertag(product_type: ProductType):
    return product_type not in [ProductType.SMT10020, ProductType.A9XMWRD, ProductType.A9XMC2D3, ProductType.A9XMC1D3]


def has_neutral(product_type: ProductType) -> bool:
    feature_class = [fc for fc in FeatureClass if product_type in fc.value][0]
    return feature_class not in [FeatureClass.A2, FeatureClass.F2, FeatureClass.M2]


def is_m(product_type: ProductType) -> bool:
    feature_class = [fc for fc in FeatureClass if product_type in fc.value][0]
    return feature_class in [FeatureClass.M1, FeatureClass.M2, FeatureClass.M3, FeatureClass.MV]


def is_r(product_type: ProductType) -> bool:
    feature_class = [fc for fc in FeatureClass if product_type in fc.value][0]
    return feature_class in [FeatureClass.FL, FeatureClass.R1]


def phase_sequence_to_line_voltages(phase_sequence: PhaseSequence, neutral: bool) -> [LineVoltage]:
    if phase_sequence is PhaseSequence.INVALID:
        return []
    elif phase_sequence in [PhaseSequence.A, PhaseSequence.B, PhaseSequence.C]:
        if not neutral:
            return []
        return {
            PhaseSequence.A: [LineVoltage.A_N],
            PhaseSequence.B: [LineVoltage.B_N],
            PhaseSequence.C: [LineVoltage.C_N]
        }[phase_sequence]
    else:
        return [LineVoltage.A_N, LineVoltage.B_N, LineVoltage.C_N] if neutral \
            else [LineVoltage.A_B, LineVoltage.B_C, LineVoltage.C_A]


class GatewayEntity(Entity):
    def __init__(self, client: SchneiderModbus, tag_device: DeviceInfo, sensor_name: str):
        self._client = client

        self._attr_device_info = tag_device
        self._attr_name = f"{tag_device['name']} {sensor_name}"

        serial = client.serial_number()
        self._attr_unique_id = f"{TAG_DOMAIN}{serial}{sensor_name}"


class PowerTagEntity(Entity):
    def __init__(self, client: SchneiderModbus, modbus_index: int, tag_device: DeviceInfo, entity_name: str):
        self._client = client
        self._modbus_index = modbus_index

        self._attr_device_info = tag_device
        self._attr_name = f"{tag_device['name']} {entity_name}"

        serial = client.tag_serial_number(modbus_index)
        self._attr_unique_id = f"{TAG_DOMAIN}{serial}{entity_name}"
