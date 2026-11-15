#!/bin/bash
set -euo pipefail

kept=/run/cr-elastic
tokens=/usr/share/elasticsearch/config/service_tokens
umask 077

until [ -s "$kept/elastic-password" ]; do
  sleep 1
done

mkdir -p "$kept/kibana"
if [ -s "$kept/service_tokens" ] && [ -s "$kept/kibana/token" ]; then
  cp "$kept/service_tokens" "$tokens"
else
  rm -f "$tokens"
  /usr/share/elasticsearch/bin/elasticsearch-service-tokens create elastic/kibana cr-kibana \
    | sed -n 's/^SERVICE_TOKEN [^ ]* = //p' > "$kept/kibana/token.new"
  [ -s "$kept/kibana/token.new" ]
  cp "$tokens" "$kept/service_tokens"
  mv "$kept/kibana/token.new" "$kept/kibana/token"
fi

export ELASTIC_PASSWORD_FILE="$kept/elastic-password"
exec /bin/tini -- /usr/local/bin/docker-entrypoint.sh eswrapper
