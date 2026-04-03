#!/usr/bin/env bash
set -euo pipefail

deb_dir="${1:-out}"

required_vars=(
  APTLY_API_URL
  APTLY_API_USER
  APTLY_API_PASSWORD
  APTLY_CLIENT_CERT
  APTLY_CLIENT_KEY
  APTLY_CA_CERT
  APTLY_REPO
  APTLY_DISTRIBUTION
  APTLY_COMPONENT
  APTLY_GPG_KEY
)

for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "Missing required variable: ${var}" >&2
    exit 1
  fi
done

for file_var in APTLY_CLIENT_CERT APTLY_CLIENT_KEY APTLY_CA_CERT; do
  if [[ ! -f "${!file_var}" ]]; then
    echo "Missing file for ${file_var}: ${!file_var}" >&2
    exit 1
  fi
done

safe_name_re='^[A-Za-z0-9][A-Za-z0-9._-]*$'
safe_component_re='^[A-Za-z0-9][A-Za-z0-9+._-]*$'
safe_prefix_re='^[A-Za-z0-9][A-Za-z0-9._-]*$'

if [[ ! -d "${deb_dir}" ]]; then
  echo "Deb directory not found: ${deb_dir}" >&2
  exit 1
fi

mapfile -t debs < <(find "${deb_dir}" -maxdepth 1 -type f -name "*.deb" | sort)
if [[ "${#debs[@]}" -eq 0 ]]; then
  echo "No .deb files found in ${deb_dir}" >&2
  exit 1
fi

publish_prefix="${APTLY_PUBLISH_PREFIX:-debian}"
passphrase_file="${APTLY_GPG_PASSPHRASE_FILE:-/run/secrets/gpg_passphrase.txt}"
api_url="${APTLY_API_URL%/}"
timestamp="$(date -u +%Y%m%d%H%M%S)"
pipeline_id="${CI_PIPELINE_ID:-manual}"
upload_dir="ci-${pipeline_id}-${timestamp}"
snapshot="${APTLY_REPO}-${APTLY_DISTRIBUTION}-${pipeline_id}-${timestamp}"
gpg_key="${APTLY_GPG_KEY// /}"

if [[ ! "${APTLY_REPO}" =~ ${safe_name_re} ]]; then
  echo "Invalid APTLY_REPO value: ${APTLY_REPO}" >&2
  exit 1
fi
if [[ ! "${APTLY_DISTRIBUTION}" =~ ${safe_name_re} ]]; then
  echo "Invalid APTLY_DISTRIBUTION value: ${APTLY_DISTRIBUTION}" >&2
  exit 1
fi
if [[ ! "${APTLY_COMPONENT}" =~ ${safe_component_re} ]]; then
  echo "Invalid APTLY_COMPONENT value: ${APTLY_COMPONENT}" >&2
  exit 1
fi
if [[ ! "${publish_prefix}" =~ ${safe_prefix_re} ]]; then
  echo "Invalid APTLY_PUBLISH_PREFIX value: ${publish_prefix}" >&2
  exit 1
fi
if [[ ! "${gpg_key}" =~ ^(0x)?[A-Fa-f0-9]{8,40}$ ]]; then
  echo "Invalid APTLY_GPG_KEY value (use key id/fingerprint): ${APTLY_GPG_KEY}" >&2
  exit 1
fi

curl_common=(
  --silent
  --show-error
  --retry 3
  --retry-delay 2
  --user "${APTLY_API_USER}:${APTLY_API_PASSWORD}"
  --cert "${APTLY_CLIENT_CERT}"
  --key "${APTLY_CLIENT_KEY}"
  --cacert "${APTLY_CA_CERT}"
)

echo "Uploading ${#debs[@]} package(s) to aptly file area '${upload_dir}'..."
for deb in "${debs[@]}"; do
  curl "${curl_common[@]}" \
    --fail \
    -X POST \
    -F "file=@${deb}" \
    "${api_url}/api/files/${upload_dir}" >/dev/null
done

echo "Importing uploaded packages into repo '${APTLY_REPO}'..."
curl "${curl_common[@]}" \
  --fail \
  -X POST \
  "${api_url}/api/repos/${APTLY_REPO}/file/${upload_dir}" >/dev/null

echo "Creating snapshot '${snapshot}'..."
snapshot_payload="$(cat <<JSON
{
  "Name": "${snapshot}",
  "Description": "gitlab pipeline ${pipeline_id}"
}
JSON
)"
curl "${curl_common[@]}" \
  --fail \
  -X POST \
  -H "Content-Type: application/json" \
  --data "${snapshot_payload}" \
  "${api_url}/api/repos/${APTLY_REPO}/snapshots" >/dev/null

echo "Checking if publish endpoint '${publish_prefix}/${APTLY_DISTRIBUTION}' already exists..."
curl "${curl_common[@]}" \
  --fail \
  --output /tmp/publish_list.json \
  "${api_url}/api/publish"

if python3 -c "
import json, sys
data = json.load(open('/tmp/publish_list.json'))
prefix = '${publish_prefix}'.strip('/')
dist = '${APTLY_DISTRIBUTION}'
found = any(
    p.get('Distribution') == dist and p.get('Prefix', '').strip('/') == prefix
    for p in data
)
sys.exit(0 if found else 1)
"; then
  publish_status="200"
else
  publish_status="404"
fi

signing_fragment="$(cat <<JSON
"Signing": {
  "Batch": true,
  "GpgKey": "${gpg_key}",
  "PassphraseFile": "${passphrase_file}"
}
JSON
)"

if [[ "${publish_status}" == "404" ]]; then
  echo "No publish found yet. Creating initial publish..."
  publish_payload="$(cat <<JSON
{
  "SourceKind": "snapshot",
  "Sources": [
    {
      "Name": "${snapshot}",
      "Component": "${APTLY_COMPONENT}"
    }
  ],
  "Distribution": "${APTLY_DISTRIBUTION}",
  "AcquireByHash": true,
  ${signing_fragment}
}
JSON
)"
  curl "${curl_common[@]}" \
    --fail \
    -X POST \
    -H "Content-Type: application/json" \
    --data "${publish_payload}" \
    "${api_url}/api/publish/${publish_prefix}" >/dev/null

elif [[ "${publish_status}" == "200" ]]; then
  echo "Publish found. Switching to new snapshot..."
  switch_payload="$(cat <<JSON
{
  "Snapshots": [
    {
      "Name": "${snapshot}",
      "Component": "${APTLY_COMPONENT}"
    }
  ],
  "AcquireByHash": true,
  ${signing_fragment}
}
JSON
)"
  curl "${curl_common[@]}" \
    --fail \
    -X PUT \
    -H "Content-Type: application/json" \
    --data "${switch_payload}" \
    "${api_url}/api/publish/${publish_prefix}/${APTLY_DISTRIBUTION}" >/dev/null

else
  echo "Unexpected publish check status: HTTP ${publish_status}" >&2
  cat /tmp/publish_list.json >&2 || true
  exit 1
fi

echo "Publish completed."
echo "Snapshot: ${snapshot}"
echo "Distribution: ${APTLY_DISTRIBUTION}"
echo "Component: ${APTLY_COMPONENT}"
echo "Prefix: ${publish_prefix}"
