#!/usr/bin/env bash

set -o errexit
set -o pipefail
set -o nounset

FILE=$1
CHUNK_SIZE=$((1024*1024*1024))
SIZE=$(wc -c $FILE | awk '{print $1}')
CHUNKS=$((($SIZE + $CHUNK_SIZE - 1) / $CHUNK_SIZE))
BLOCK_BASED_SIZE=$(($CHUNKS*$CHUNK_SIZE))

for i in $(seq 1 $CHUNKS); do
  echo "Splitting file into chunks: $i/$CHUNKS" >&2
  EXTENSION=$(printf "%03d" $(($CHUNKS-$i+1)))
  echo "Creating chunk: $i/$CHUNKS" >&2
  dd if=$FILE of=$FILE.$EXTENSION bs=$CHUNK_SIZE count=1 skip=$(($CHUNKS-$i)) 2>/dev/null
  echo "Truncating file to remove chunk: $i/$CHUNKS" >&2
  truncate -s $(($BLOCK_BASED_SIZE - $CHUNK_SIZE * ($i - 1))) $FILE
done

echo "Removing original file" >&2
rm $FILE

for i in $(seq 1 $CHUNKS); do
  echo "Consuming chunk: $i/$CHUNKS" >&2
  EXTENSION=$(printf "%03d" $i)
  cat $FILE.$EXTENSION
  echo "Removing chunk: $i/$CHUNKS" >&2
  rm $FILE.$EXTENSION
done
