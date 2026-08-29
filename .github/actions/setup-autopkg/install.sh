#!/usr/bin/env bash

set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "setup-autopkg only supports macOS" >&2
    exit 1
fi

requested_version="${INPUT_VERSION#v}"
if [[ -n "$requested_version" && ! "$requested_version" =~ ^[0-9A-Za-z][0-9A-Za-z._-]*$ ]]; then
    echo "Invalid AutoPkg version: $INPUT_VERSION" >&2
    exit 1
fi

api_url="https://api.github.com/repos/autopkg/autopkg/releases/latest"
if [[ -n "$requested_version" ]]; then
    api_url="https://api.github.com/repos/autopkg/autopkg/releases/tags/v${requested_version}"
fi

temporary_root="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
temporary_dir="$(mktemp -d "$temporary_root/setup-autopkg.XXXXXX")"
cleanup() {
    if [[ -n "${temporary_dir:-}" && -d "$temporary_dir" && "$temporary_dir" == "$temporary_root/setup-autopkg."* ]]; then
        rm -rf "$temporary_dir"
    fi
}
trap cleanup EXIT

api_response="$temporary_dir/release.json"
curl_arguments=(
    --fail
    --location
    --silent
    --show-error
    --header "Accept: application/vnd.github+json"
    --header "X-GitHub-Api-Version: 2022-11-28"
)
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    curl_arguments+=(--header "Authorization: Bearer $GITHUB_TOKEN")
fi
curl "${curl_arguments[@]}" --output "$api_response" "$api_url"

release_tag="$(plutil -extract tag_name raw -o - "$api_response")"
expected_version="${release_tag#v}"
if [[ "$expected_version" =~ ^([0-9]+(\.[0-9]+)+)RC[0-9]+$ ]]; then
    expected_version="${BASH_REMATCH[1]}"
fi
asset_count=0
asset_index=0
asset_name=""
asset_url=""
asset_digest=""
while candidate_name="$(plutil -extract "assets.$asset_index.name" raw -o - "$api_response" 2>/dev/null)"; do
    if [[ "$candidate_name" == *.pkg ]]; then
        asset_count=$((asset_count + 1))
        asset_name="$candidate_name"
        asset_url="$(plutil -extract "assets.$asset_index.browser_download_url" raw -o - "$api_response")"
        asset_digest="$(plutil -extract "assets.$asset_index.digest" raw -o - "$api_response")"
    fi
    asset_index=$((asset_index + 1))
done

if [[ "$asset_count" -ne 1 || "$asset_digest" != sha256:* ]]; then
    echo "$release_tag must publish exactly one .pkg asset with a SHA-256 digest" >&2
    exit 1
fi

installed_version=""
if [[ -x /usr/local/bin/autopkg ]]; then
    installed_version="$(/usr/local/bin/autopkg version)"
fi
if [[ "$installed_version" == "$expected_version" ]]; then
    echo "AutoPkg $installed_version is already installed from $release_tag"
else
    package="$temporary_dir/$asset_name"
    curl --fail --location --silent --show-error --output "$package" "$asset_url"

    expected_digest="${asset_digest#sha256:}"
    actual_digest="$(shasum -a 256 "$package" | awk '{print $1}')"
    if [[ "$actual_digest" != "$expected_digest" ]]; then
        echo "AutoPkg package digest does not match the GitHub release" >&2
        exit 1
    fi

    signature_status=0
    signature="$(pkgutil --check-signature "$package" 2>&1)" || signature_status=$?
    printf '%s\n' "$signature"
    if [[ "$signature_status" -eq 0 && "$signature" == *"Status: signed by a developer certificate issued by Apple for distribution"* ]]; then
        :
    elif [[ "$signature" == *"Status: no signature"* ]]; then
        echo "AutoPkg publishes this release package unsigned; using the verified GitHub release digest"
    else
        echo "AutoPkg package has an unexpected signature status" >&2
        exit 1
    fi

    sudo -n /usr/sbin/installer -pkg "$package" -target /
    installed_version="$(/usr/local/bin/autopkg version)"
    echo "Installed AutoPkg $installed_version from $release_tag"
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf 'release=%s\n' "$release_tag" >>"$GITHUB_OUTPUT"
    printf 'version=%s\n' "$installed_version" >>"$GITHUB_OUTPUT"
fi
