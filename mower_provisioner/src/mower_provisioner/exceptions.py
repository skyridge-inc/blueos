"""Custom exceptions for mower_provisioner."""


class MowerProvisionerError(Exception):
    """Base exception for all mower provisioner errors."""


class ConnectionError(MowerProvisionerError):
    """Failed to connect to MAVLink device."""


class HeartbeatTimeout(ConnectionError):
    """No heartbeat received within timeout."""


class ParameterError(MowerProvisionerError):
    """Error during parameter operations."""


class ParameterFetchError(ParameterError):
    """Failed to fetch parameters from device."""


class ParameterWriteError(ParameterError):
    """Failed to write parameter to device."""


class ParamFileError(MowerProvisionerError):
    """Error reading or writing .param files."""
