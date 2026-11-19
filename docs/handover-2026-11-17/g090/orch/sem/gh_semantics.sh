#!/bin/zsh
# What gh and httpie do with the spellings the review names. Read-only: every GraphQL call asks for the
# viewer's own login or id and prints only the names of the fields that came back; nothing is written.
# usage: zsh gh_semantics.sh
echo "gh: $(gh --version | head -n 1)"
echo
echo "== 1. the endpoint written as a path or a full address: does a query still go to the GraphQL API?"
echo "graphql:                        $(gh api graphql -f query='{viewer{login}}' --jq '.data.viewer|keys|join(",")' 2>&1 | head -n 1)"
echo "/graphql:                       $(gh api /graphql -f query='{viewer{login}}' --jq '.data.viewer|keys|join(",")' 2>&1 | head -n 1)"
echo "graphql/:                       $(gh api graphql/ -f query='{viewer{login}}' --jq '.data.viewer|keys|join(",")' 2>&1 | head -n 1)"
echo "https://api.github.com/graphql: $(gh api https://api.github.com/graphql -f query='{viewer{login}}' --jq '.data.viewer|keys|join(",")' 2>&1 | head -n 1)"
echo "--method POST /graphql:         $(gh api --method POST /graphql -f query='{viewer{login}}' --jq '.data.viewer|keys|join(",")' 2>&1 | head -n 1)"
echo
echo "== 2. two query fields: which one is sent? (first asks for id, second for login)"
echo "-f query (id) -f query (login): $(gh api graphql -f query='{viewer{id}}' -f query='{viewer{login}}' --jq '.data.viewer|keys|join(",")' 2>&1 | head -n 1)"
echo
echo "== 3. -h behind gh pr merge: help, or an error? (no number given, nothing can be merged)"
gh pr merge -h 2>&1 | head -n 2
echo
echo "== 4. httpie: a method word in small letters (offline: the request is printed, not sent)"
http --offline put https://api.github.com/repos/o/r/pulls/3/merge 2>&1 | head -n 1
http --offline https://api.github.com/graphql query:='"x"' 2>&1 | grep -E '^(POST|GET|\{)' | head -n 2
echo
echo "== 5. curl manual on -T"
man curl 2>/dev/null | col -b | grep -n -i -E 'PUT (command|will be used|is used)' | head -n 3
