#!/bin/sh
# What HTTPie puts into a request: the method and the body, for each way to hand it a body.
# Nothing is sent: `--offline` builds the request and prints it. The host is a name that cannot resolve.
# usage: sh httpie_body.sh <run folder>      (the folder gets q.json; the output goes to standard output)
RUN="$1"
[ -d "$RUN" ] || { echo "usage: sh httpie_body.sh <run folder>"; exit 2; }
URL=https://example.invalid/graphql
printf '%s' '{"query":"from the file"}' > "$RUN/q.json"

show() {
  # the request line and what follows the empty line (the body), in one line each
  awk 'NR==1 {print "  request: " $0} body && NF {print "  body: " $0} /^[[:space:]]*$/ {body=1}'
}

echo "http $(http --version 2>&1)"
if [ -t 0 ]; then echo "this script's own standard input: a terminal"; else echo "this script's own standard input: no terminal"; fi

echo "1 no item, standard input /dev/null"
http --offline $URL < /dev/null 2>&1 | show
echo "2 no item, standard input q.json"
http --offline $URL < "$RUN/q.json" 2>&1 | show
echo "3 no item, a pipe"
cat "$RUN/q.json" | http --offline $URL 2>&1 | show
echo "4 no item, standard input as this script got it (5 s limit)"
gtimeout 5 http --offline $URL 2>&1 | show
echo "  exit of the pipeline: $?"
echo "5 --raw, --ignore-stdin"
http --offline --ignore-stdin $URL --raw '{"query":"from raw"}' 2>&1 | show
echo "6 --raw=, --ignore-stdin, no method word"
http --offline --ignore-stdin --raw='{"query":"from raw="}' $URL 2>&1 | show
echo "7 --raw with standard input q.json"
http --offline $URL --raw '{"query":"from raw"}' < "$RUN/q.json" 2>&1 | head -n 3 | sed 's/^/  /'
echo "8 @file, --ignore-stdin"
http --offline --ignore-stdin $URL @"$RUN/q.json" 2>&1 | show
echo "9 @file with POST in front"
http --offline --ignore-stdin POST $URL @"$RUN/q.json" 2>&1 | show
echo "10 --ignore-stdin, standard input q.json"
http --offline --ignore-stdin $URL < "$RUN/q.json" 2>&1 | show
echo "11 -I, a pipe"
cat "$RUN/q.json" | http --offline -I $URL 2>&1 | show
echo "12 GET, standard input q.json"
http --offline GET $URL < "$RUN/q.json" 2>&1 | show
echo "13 query= item with standard input q.json"
http --offline POST $URL query='from the item' < "$RUN/q.json" 2>&1 | head -n 3 | sed 's/^/  /'
echo "14 query= item, --ignore-stdin, standard input q.json"
http --offline --ignore-stdin POST $URL query='from the item' < "$RUN/q.json" 2>&1 | show
echo "15 query=@file item"
http --offline --ignore-stdin POST $URL query=@"$RUN/q.json" 2>&1 | show
echo "16 a header item only, --ignore-stdin"
http --offline --ignore-stdin $URL X-Test:1 2>&1 | show
echo "17 https, host without a scheme, a pipe"
cat "$RUN/q.json" | https --offline example.invalid/graphql 2>&1 | show
