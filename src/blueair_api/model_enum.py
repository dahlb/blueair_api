from enum import Enum, StrEnum


class FeatureEnum(StrEnum):
    TEMPERATURE = "Temperature"
    HUMIDITY = "Humidity"
    VOC = "VOC"
    PM1 = "PM1"
    PM10 = "PM10"
    PM25 = "PM25"
    WATER_SHORTAGE = "Water Shortage"
    FILTER_EXPIRED = "Filter Expired"
    CHILD_LOCK = "Child Lock"


class ModelEnum(Enum):
    def __new__(cls, *args, **kwds):
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self,
                 name,
                 supported_features):
        self.model_name = name
        self.supported_features = supported_features

    def supports_feature(self, supported_features) -> bool:
        return supported_features in self.supported_features

    UNKNOWN = "Unknown", [
        FeatureEnum.TEMPERATURE,
        FeatureEnum.HUMIDITY,
        FeatureEnum.WATER_SHORTAGE,
        FeatureEnum.VOC,
        FeatureEnum.PM1,
        FeatureEnum.PM10,
        FeatureEnum.PM25,
        FeatureEnum.FILTER_EXPIRED,
        FeatureEnum.CHILD_LOCK,
    ]
    HUMIDIFIER_H35I = "Blueair Humidifier H35i", [
        FeatureEnum.TEMPERATURE,
        FeatureEnum.HUMIDITY,
        FeatureEnum.WATER_SHORTAGE,
    ]
    PROTECT_7440I = "Blueair Protect 7440i", [
        FeatureEnum.TEMPERATURE,
        FeatureEnum.HUMIDITY,
        FeatureEnum.VOC,
        FeatureEnum.PM1,
        FeatureEnum.PM10,
        FeatureEnum.PM25,
        FeatureEnum.FILTER_EXPIRED,
        FeatureEnum.CHILD_LOCK,
    ]
    PROTECT_7470I = "Blueair Protect 7470i", [
        FeatureEnum.TEMPERATURE,
        FeatureEnum.HUMIDITY,
        FeatureEnum.VOC,
        FeatureEnum.PM1,
        FeatureEnum.PM10,
        FeatureEnum.PM25,
        FeatureEnum.FILTER_EXPIRED,
        FeatureEnum.CHILD_LOCK,
    ]
    MAX_211I = "Blueair Blue Pure 211i Max", [
        FeatureEnum.PM1,
        FeatureEnum.PM10,
        FeatureEnum.PM25,
        FeatureEnum.FILTER_EXPIRED,
        FeatureEnum.CHILD_LOCK,
    ]
    MAX_311I = "Blueair Blue Pure 311i Max", [
        FeatureEnum.PM25,
        FeatureEnum.FILTER_EXPIRED,
        FeatureEnum.CHILD_LOCK,
    ]
    MAX_411I = "Blueair Blue Pure 411i Max", [
        FeatureEnum.PM25,
        FeatureEnum.FILTER_EXPIRED,
        FeatureEnum.CHILD_LOCK,
    ]
    T10I = "T10i ComfortPure 3-in-1 Filter/Heater/Fan", [
        FeatureEnum.TEMPERATURE,
        FeatureEnum.HUMIDITY,
        FeatureEnum.PM25,
        FeatureEnum.FILTER_EXPIRED,
    ]
