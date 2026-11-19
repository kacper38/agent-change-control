#!/bin/zsh
# Second read-only check of gh and httpie spellings. The body file asks for the viewer's id, the visible field
# for the login; only the names of the returned fields are printed. Nothing is written anywhere but $1.
# usage: zsh gh_semantics2.sh <scratch folder>
D="$1"
[ -n "$D" ] || { echo "usage: zsh gh_semantics2.sh <scratch folder>"; exit 2; }
mkdir -p "$D"
print -r -- '{"query":"{viewer{id}}"}' > "$D/q.json"
print -r -- '{viewer{id}}' > "$D/q.graphql"
echo "== 1. a visible query field and a body file: which one is sent? (field asks for login, file for id)"
echo "-f query (login) --input q.json:   $(gh api graphql -f query='{viewer{login}}' --input "$D/q.json" --jq '.data.viewer|keys|join(",")' 2>&1 | head -n 1)"
echo "--input q.json alone:              $(gh api graphql --input "$D/q.json" --jq '.data.viewer|keys|join(",")' 2>&1 | head -n 1)"
echo "-f query (login) -F query=@file:   $(gh api graphql -f query='{viewer{login}}' -F query=@"$D/q.graphql" --jq '.data.viewer|keys|join(",")' 2>&1 | head -n 1)"
echo "-F query=@file alone:              $(gh api graphql -F query=@"$D/q.graphql" --jq '.data.viewer|keys|join(",")' 2>&1 | head -n 1)"
echo
echo "== 2. httpie, offline (the request is printed, not sent)"
http --offline https://api.github.com/graphql 'query:="x"' 2>&1 | grep -E '^(POST|GET|PUT) |^\{' | head -n 2
http --offline https://api.github.com/graphql query=x query=y 2>&1 | grep -E '^(POST|GET|PUT) |^\{' | head -n 2
echo "body from stdin: $(http --offline https://api.github.com/graphql < "$D/q.json" 2>&1 | grep -E '^(POST|GET|PUT) |^\{' | tr '\n' ' ')"
echo
echo "== 3. curl manual on --upload-file"
man curl 2>/dev/null | col -b | grep -n -E -- '-T, --upload-file' | head -n 2
man curl 2>/dev/null | col -b | grep -n -E 'HTTP\(S\) server, the PUT|PUT command' | head -n 3
echo
echo "== 4. kubectl help on resource names and --template (help text only, no cluster call)"
kubectl get --help 2>/dev/null | grep -n -i -E 'case-insensitive|--template=' | head -n 4
kubectl config view --help 2>/dev/null | grep -n -E -- '--(raw|flatten)' | head -n 4
