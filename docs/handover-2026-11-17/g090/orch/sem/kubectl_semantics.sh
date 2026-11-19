#!/bin/zsh
# What `kubectl config view` prints with --flatten, --raw and neither, for a made-up kubeconfig written here.
# The token in it is the text NOT-A-SECRET; KUBECONFIG points at this file only, so no real config is read
# and no cluster is called (config view is a local command).
# usage: zsh kubectl_semantics.sh <scratch folder>
D="$1"
[ -n "$D" ] || { echo "usage: zsh kubectl_semantics.sh <scratch folder>"; exit 2; }
mkdir -p "$D"
print -r -- 'apiVersion: v1
kind: Config
clusters:
- name: c
  cluster:
    server: https://example.invalid
users:
- name: u
  user:
    token: NOT-A-SECRET
contexts:
- name: x
  context:
    cluster: c
    user: u
current-context: x' > "$D/kubeconfig.yaml"
echo "kubectl: $(kubectl version --client 2>/dev/null | head -n 1)"
for form in "" "--raw" "--flatten" "--minify" "-o json"; do
  echo "config view $form -> token line: $(KUBECONFIG="$D/kubeconfig.yaml" kubectl config view ${=form} 2>&1 | grep -i -E 'token' | tr -d ' ' | head -n 1)"
done
