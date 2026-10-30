### Changed
- Server: request paths in the IP-filter and mTLS-scope logs are escaped, so a forged path cannot inject control characters into the log
- Server: Redis connection errors in the SSE stream and the rate limit log only the error type and in English, never connection details
- Server: an FRP tunnel row with refused extra_config is warned about once per tunnel and key set instead of at every poll
- Server: the OpenAPI document lists the 401, 403, 404 and 429 errors of the webhook trigger routes
