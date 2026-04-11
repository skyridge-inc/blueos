"""Shared fixtures for skynet tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_conn():
    """Create a mock MAVLink connection."""
    conn = MagicMock()
    conn.target_system = 1
    conn.target_component = 1
    conn.mav = MagicMock()
    return conn


@pytest.fixture
def tmp_param_file(tmp_path):
    """Create a temporary .param file with sample data."""
    content = """\
# Sample param file
CRUISE_SPEED,2.5
CRUISE_THROTTLE,50
WP_RADIUS,3
NAVL1_PERIOD,8
"""
    path = tmp_path / "test.param"
    path.write_text(content)
    return path


@pytest.fixture
def tmp_param_file_with_calibration(tmp_path):
    """Create a temporary .param file that includes calibration params."""
    content = """\
CRUISE_SPEED,2.5
INS_ACCOFFS_X,0.123
INS_ACCOFFS_Y,-0.456
SYSID_THISMAV,1
WP_RADIUS,3
"""
    path = tmp_path / "test_cal.param"
    path.write_text(content)
    return path
