"""Tests for entry setup and service targeting."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.estfeed import _async_register_services, async_setup_entry
from custom_components.estfeed.api import EstfeedAuthError
from custom_components.estfeed.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, DOMAIN


@pytest.mark.parametrize("service", ["backfill_history", "set_cumulative_reset_at"])
@pytest.mark.parametrize("target", [None, "first", "missing", ""])
async def test_service_targets_only_selected_loaded_entries(hass, service, target):
    first, second = MagicMock(), MagicMock()
    for coordinator in (first, second):
        coordinator.async_initial_backfill = AsyncMock()
        coordinator.async_set_cumulative_reset_at = AsyncMock()
    hass.data[DOMAIN] = {"first": first, "second": second}
    _async_register_services(hass)
    data = {"reset_at": "2026-05-18T12:00:00+00:00"} if service == "set_cumulative_reset_at" else {}
    if target is not None:
        data["entry_id"] = target
    if target in ("missing", ""):
        with pytest.raises(ServiceValidationError, match="not loaded"):
            await hass.services.async_call(DOMAIN, service, data, blocking=True)
    else:
        await hass.services.async_call(DOMAIN, service, data, blocking=True)
    method = (
        "async_initial_backfill"
        if service == "backfill_history"
        else "async_set_cumulative_reset_at"
    )
    assert getattr(first, method).await_count == (1 if target in (None, "first") else 0)
    assert getattr(second, method).await_count == (1 if target is None else 0)


async def test_reset_action_interprets_naive_timestamp_in_local_timezone(hass):
    coordinator = MagicMock()
    coordinator.async_set_cumulative_reset_at = AsyncMock()
    hass.data[DOMAIN] = {"first": coordinator}
    _async_register_services(hass)
    with patch.object(dt_util, "DEFAULT_TIME_ZONE", ZoneInfo("Europe/Tallinn")):
        await hass.services.async_call(
            DOMAIN,
            "set_cumulative_reset_at",
            {"reset_at": "2026-05-18T12:00:00", "entry_id": "first"},
            blocking=True,
        )
    coordinator.async_set_cumulative_reset_at.assert_awaited_once_with(
        datetime(2026, 5, 18, 9, tzinfo=UTC)
    )


async def test_setup_rejected_credentials_trigger_auth_failure(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_CLIENT_ID: "cid", CONF_CLIENT_SECRET: "secret"}
    )
    with (
        patch(
            "custom_components.estfeed.EstfeedClient.list_metering_points",
            new=AsyncMock(side_effect=EstfeedAuthError("Rejected key")),
        ),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await async_setup_entry(hass, entry)
