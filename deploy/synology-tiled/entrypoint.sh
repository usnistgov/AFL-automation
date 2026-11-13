#!/bin/sh
set -eu

secret_file=/run/secrets/tiled_api_key
template=/opt/tiled/config.yml.template
runtime_config=/tmp/tiled-config.yml

if [ ! -r "$secret_file" ]; then
    echo "Tiled API key secret is missing or unreadable: $secret_file" >&2
    exit 1
fi

api_key=$(tr -d '\r\n' < "$secret_file")
case "$api_key" in
    *[!0-9a-fA-F]*|'')
        echo "Tiled API key must be a non-empty hexadecimal string" >&2
        exit 1
        ;;
esac

if [ "${#api_key}" -lt 64 ]; then
    echo "Tiled API key must contain at least 64 hexadecimal characters" >&2
    exit 1
fi

cp "$template" "$runtime_config"
chmod 0600 "$runtime_config"

export TILED_SINGLE_USER_API_KEY="$api_key"
exec tiled serve config "$runtime_config"
