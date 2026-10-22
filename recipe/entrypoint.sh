#!/bin/sh
set -eu
umask 077
test -s /data/shadnet.cfg || {
    echo "Missing /data/shadnet.cfg; run prepare.py first." >&2
    exit 1
}
cp /usr/local/lib/shadnet/shadnet /data/shadnet
chmod 700 /data/shadnet
for file in worlds.cfg scoreboards.cfg; do
    if [ ! -e "/data/$file" ]; then
        cp "/usr/local/lib/shadnet/$file" "/data/$file"
    fi
done
exec /data/shadnet
