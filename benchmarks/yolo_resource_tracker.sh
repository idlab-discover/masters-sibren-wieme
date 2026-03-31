#!/bin/bash
# MIT License
# Copyright (c) 2026 Sibren Wieme
# See root LICENSE file for full terms.
PID=$1
OUTPUT_FILE=$2

if [ -z "$PID" ] || [ -z "$OUTPUT_FILE" ]; then
    echo "Usage: $0 <PID> <OUTPUT_FILE>"
    exit 1
fi

echo "timestamp,cpu_percent,mem_kb" > "$OUTPUT_FILE"

while ps -p "$PID" > /dev/null; do
    STATS=$(ps -p "$PID" -o %cpu,rss | tail -n 1)
    CPU=$(echo $STATS | awk '{print $1}')
    MEM=$(echo $STATS | awk '{print $2}')
    TIMESTAMP=$(date +%s)
    if [ ! -z "$CPU" ] && [ ! -z "$MEM" ]; then
        echo "$TIMESTAMP,$CPU,$MEM" >> "$OUTPUT_FILE"
    fi
    sleep 1
done
