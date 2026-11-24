### Changed

- **Server/Monitoring: gemeinsamer Python-Code in `apps/pycommon`:** SSRF-Schutz, Zeit-Helfer, Logging, Engine-Fabrik, Request-Schranken, 422-Handler, Vergleich des internen Schluessels und SMTP-Versand liegen einmal im Paket `ah_common`, das beide Images neben `app/` kopieren; ein Test meldet neue Kopien zwischen den Diensten. Wer einen Dienst von Hand startet, setzt `PYTHONPATH=../pycommon` (DEVELOPMENT.md).
- **Monitoring: DB-Pool per Umgebung, PID im Log:** Das Monitoring liest `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` wie der Server (Vorgabe weiter 10/20, Compose reicht beide durch), und jede Logzeile traegt die PID.
