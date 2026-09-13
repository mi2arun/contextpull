# Transaction error reference

Codes returned by the payment gateway.

## TX-44xx: issuer declines

| Code | Meaning | Retry |
|---|---|---|
| TX-4401 | Insufficient funds | yes, after 24h |
| TX-4419 | Declined by issuer; retry is not permitted | no |
| TX-4420 | Card reported lost or stolen | no |

## TX-45xx: gateway errors

- TX-4501: gateway timeout. Retry with the same idempotency key.
- TX-4502: gateway unavailable. Retry after the interval in the `Retry-After` header.

## Environment variables

Set `GATEWAY_TIMEOUT_MS` to change the default 30000 ms timeout. Set `GATEWAY_RETRIES` to change the retry count (default 3).
