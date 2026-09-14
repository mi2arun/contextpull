# Drive unit error codes

Codes raised by the drive unit. Distinct from controller codes, which start with WR-22 or WR-23.

## WR-31xx: motor

| Code | Meaning | Action |
|---|---|---|
| WR-3101 | Motor overcurrent | Check for mechanical jam |
| WR-3104 | Encoder signal lost | Inspect encoder cable |
| WR-3107 | Phase imbalance | Measure supply phases |

## WR-32xx: brake

- WR-3201: brake did not release within 500 ms.
- WR-3202: brake wear limit reached; replace pads (part PN-88120).

## Notes

A WR-3101 that follows a WR-2201 within ten seconds is usually a consequence of the surge, not a separate fault.
