### Fixed

- **CA-Issuer: mit `--compromised` ersetzte Zwischenzertifikate bleiben ersetzt:** `rotate-intermediates
  --compromised` und `rotate-root switch --compromised` fuehren sie bis zu ihrem Ablauf in
  `<scope>-compromised.pem`; Start, Rotation, `rotate-root finish` und `status` erkennen sie daran.
- **CA-Issuer: `rotate-root finish` waehlt je Geraetelinie das zuletzt erfasste Zertifikat**, auch wenn zwei in
  derselben Sekunde ausgestellt wurden.
