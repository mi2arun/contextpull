# Controller error codes

Codes raised by the R-series main controller. All codes are shown on the front panel and logged to `/var/log/rctl.log`.

## WR-22xx: protection events

| Code | Meaning | Action |
|---|---|---|
| WR-2201 | Surge event on mains input | Check supply; claim void if above 250 V |
| WR-2205 | Sensor bus fault | Reseat the sensor harness (procedure P-40) |
| WR-2210 | Thermal cut-out override detected | Service centre only |

## WR-23xx: firmware

- WR-2301: firmware image failed checksum. Re-flash from a verified image.
- WR-2302: firmware downgrade blocked. Set `ALLOW_DOWNGRADE=1` to permit, at your own risk.

## Environment variables

`RCTL_LOG_LEVEL` controls verbosity (`error`, `warn`, `info`, `debug`). `RCTL_WATCHDOG_MS` sets the watchdog period; the default is 5000.
