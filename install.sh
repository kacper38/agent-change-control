#!/usr/bin/env bash
# Install this setup.
# Usage:
#   ./install.sh                      user scope: agents + skills into ~/.claude (backs up overwrites)
#   ./install.sh --uninstall          remove everything listed in the user-scope manifest
#   ./install.sh --into <repo> [--force] [--forge github|ado]
#                                     repo scope: copy the kit listed in kit.manifest into a task
#                                     repo (AGENTS.md, hooks, guard, skills, agents); idempotent;
#                                     locally modified managed files are kept unless --force;
#                                     --forge picks the @github / @ado manifest entries (default:
#                                     ado when the target's origin is on dev.azure.com or
#                                     *.visualstudio.com, else github); kit-version records it
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

# ---------------------------------------------------------------------------
# Repo scope: install.sh --into <repo> [--force] [--forge github|ado]
# ---------------------------------------------------------------------------
sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }

# origin_forge <dir>: "ado" when the origin remote's host is Azure DevOps, else "github"
# (also for no git, no origin or a local path). Handles https://[user@]host[:port]/... and
# scp-like [user@]host:path, e.g. git@ssh.dev.azure.com:v3/org/project/repo.
origin_forge() {
  local url host
  url="$(git -C "$1" remote get-url origin 2>/dev/null || true)"
  host="${url#*://}"; host="${host%%/*}"; host="${host##*@}"; host="${host%%:*}"; host="${host,,}"
  case "$host" in
    dev.azure.com | ssh.dev.azure.com | *.visualstudio.com) echo ado ;;
    *) echo github ;;
  esac
}

install_into() {
  local target="$1" force="${2:-}" forge="${3:-}" why="--forge"
  [[ -d "$target" ]] || { echo "install.sh: target directory not found: $target" >&2; exit 1; }
  target="$(cd "$target" && pwd)"
  if [[ -z "$forge" ]]; then
    forge="$(origin_forge "$target")"
    why="detected: no Azure DevOps origin"
    [[ "$forge" == "ado" ]] && why="detected: Azure DevOps origin"
  fi
  local hashes="$target/.claude/kit-manifest.sha256"
  local copied=0 kept=0 unchanged=0 inited=0 skipped=0 other=0
  declare -A old_hash=()
  if [[ -f "$hashes" ]]; then
    while read -r h f; do [[ -n "$f" ]] && old_hash["$f"]="$h"; done < "$hashes"
  fi
  local new_hashes=()

  copy_managed() {  # $1 = source path (abs), $2 = destination path relative to target
    local src="$1" rel="$2" dst="$target/$2"
    local src_hash; src_hash="$(sha256 "$src")"
    new_hashes+=("$src_hash  $rel")
    if [[ ! -f "$dst" ]]; then
      mkdir -p "$(dirname "$dst")"; cp "$src" "$dst"; copied=$((copied + 1)); return
    fi
    local dst_hash; dst_hash="$(sha256 "$dst")"
    if [[ "$dst_hash" == "$src_hash" ]]; then unchanged=$((unchanged + 1)); return; fi
    if [[ "${old_hash[$rel]:-}" == "$dst_hash" || -n "$force" ]]; then
      cp "$src" "$dst"; copied=$((copied + 1))
    else
      echo "  kept (modified locally, use --force): $rel"; kept=$((kept + 1))
    fi
  }

  local mode src dst only
  while read -r mode src dst only; do
    [[ -z "$mode" || "$mode" == \#* ]] && continue
    if [[ "$dst" == @* ]]; then  # the forge column right after the source: no destination
      [[ -z "$only" ]] || { echo "install.sh: bad manifest line: $mode $src $dst $only" >&2; exit 1; }
      only="$dst"; dst=""
    fi
    case "$only" in
      "" | "@$forge") ;;
      @github | @ado)
        other=$((other + 1))
        if [[ -e "$target/${dst:-$src}" ]]; then
          echo "  note: ${dst:-$src} is for ${only#@} targets; left in place (this target: $forge)"
        fi
        continue ;;
      *) echo "install.sh: bad manifest line: $mode $src $dst $only" >&2; exit 1 ;;
    esac
    dst="${dst:-$src}"
    case "$mode" in
      init)
        if [[ -e "$target/$dst" ]]; then skipped=$((skipped + 1)); else
          mkdir -p "$target/$(dirname "$dst")"
          if [[ "$src" == "CLAUDE.md" ]]; then printf '@AGENTS.md\n' > "$target/CLAUDE.md"; else cp "$HERE/$src" "$target/$dst"; fi
          inited=$((inited + 1))
        fi ;;
      managed) copy_managed "$HERE/$src" "$dst" ;;
      map)
        while IFS= read -r -d '' f; do
          copy_managed "$f" "$dst/${f#"$HERE/$src/"}"
        done < <(find "$HERE/$src" -type f -print0) ;;
      *) echo "install.sh: bad manifest line: $mode $src $dst" >&2; exit 1 ;;
    esac
  done < "$HERE/kit.manifest"

  mkdir -p "$target/.claude"
  printf '%s\n' "${new_hashes[@]}" | sort -k2 > "$hashes"
  {
    echo "source: $(git -C "$HERE" config --get remote.origin.url 2>/dev/null || echo "$HERE")"
    echo "commit: $(git -C "$HERE" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "installed: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "forge: $forge"
  } > "$target/.claude/kit-version"
  if [[ -f "$target/.githooks/commit-msg" ]] && git -C "$target" rev-parse --git-dir >/dev/null 2>&1; then
    chmod +x "$target"/.githooks/* 2>/dev/null || true
    local hp; hp="$(git -C "$target" config --get core.hooksPath 2>/dev/null || true)"
    local gitdir; gitdir="$(git -C "$target" rev-parse --git-path hooks)"
    [[ "$gitdir" == /* ]] || gitdir="$target/$gitdir"
    local live="" f
    for f in "$gitdir"/*; do [[ -f "$f" && "$f" != *.sample ]] && live+="$(basename "$f") "; done
    if [[ -z "$hp" && -n "$live" ]]; then
      echo "  left core.hooksPath unset: $target has live hooks in .git/hooks ($live); call tools/commit_msg.py from them to keep the gate"
    elif [[ -z "$hp" ]]; then
      git -C "$target" config core.hooksPath .githooks && echo "  git config core.hooksPath .githooks (commit-msg gate active)"
    elif [[ "$hp" != ".githooks" ]]; then
      echo "  left core.hooksPath=$hp alone: call tools/commit_msg.py from your own commit-msg hook to keep the gate"
    fi
  fi
  local changes=$((copied + inited))
  echo "Kit installed into $target — changes: $changes (copied $copied, initialized $inited), unchanged $unchanged, kept $kept, init-only skipped $skipped"
  echo "  forge: $forge ($why); entries for the other forge skipped: $other"
  [[ -f "$target/CLAUDE.md" ]] && ! grep -q '@AGENTS.md' "$target/CLAUDE.md" && \
    echo "  note: $target/CLAUDE.md exists without @AGENTS.md — add the import by hand if you want Claude Code to read AGENTS.md"
  return 0
}

if [[ "${1:-}" == "--into" ]]; then
  usage="usage: ./install.sh --into <repo> [--force] [--forge github|ado]"
  [[ -n "${2:-}" ]] || { echo "$usage" >&2; exit 1; }
  into="$2" force="" forge=""
  shift 2
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --force) force=1; shift ;;
      --forge)
        [[ "${2:-}" == "github" || "${2:-}" == "ado" ]] || { echo "install.sh: --forge takes github or ado" >&2; exit 1; }
        forge="$2"; shift 2 ;;
      *) echo "install.sh: unknown argument: $1" >&2; echo "$usage" >&2; exit 1 ;;
    esac
  done
  install_into "$into" "$force" "$forge"
  exit 0
fi
DEST="${CLAUDE_DIR:-$HOME/.claude}"
MANIFEST="$DEST/agent-change-control.manifest"
LEGACY_MANIFEST="$DEST/claude-platform-setup.manifest"   # written by installs before the 2026-11-01 rename

if [[ "${1:-}" == "--uninstall" ]]; then
  manifests=()
  for m in "$MANIFEST" "$LEGACY_MANIFEST"; do
    [[ -f "$m" ]] && manifests+=("$m")
  done
  if [[ ${#manifests[@]} -eq 0 ]]; then
    echo "No manifest at $MANIFEST — nothing to uninstall." >&2
    exit 1
  fi
  for m in "${manifests[@]}"; do   # both when both exist: everything either install put here goes
    while IFS= read -r f; do
      [[ -z "$f" || "$f" == \#* ]] && continue
      [[ "$f" == /* || "$f" == *..* ]] && { echo "install.sh: skipping unsafe manifest entry: $f" >&2; continue; }
      rm -f "$DEST/$f"
    done < "$m"
    rm -f "$m"
  done
  find "$DEST/skills" "$DEST/agents" -type d -empty -delete 2>/dev/null || true
  echo "Uninstalled. Backups, if any, remain in $DEST/backups/."
  exit 0
fi

mkdir -p "$DEST/agents" "$DEST/skills"

# File list, relative to both $HERE and $DEST
files=()
for a in "$HERE"/agents/*.md; do
  files+=("agents/$(basename "$a")")
done
while IFS= read -r -d '' s; do
  files+=("skills/${s#"$HERE"/skills/}")
done < <(find "$HERE/skills" -type f -print0)

# Back up anything that exists and differs, then copy
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$DEST/backups/agent-change-control-$STAMP"
backed_up=0
for f in "${files[@]}"; do
  if [[ -f "$DEST/$f" ]] && ! cmp -s "$HERE/$f" "$DEST/$f"; then
    mkdir -p "$BACKUP/$(dirname "$f")"
    cp "$DEST/$f" "$BACKUP/$f"
    backed_up=$((backed_up + 1))
  fi
  mkdir -p "$DEST/$(dirname "$f")"
  cp "$HERE/$f" "$DEST/$f"
done

{
  echo "# agent-change-control — installed $(date -u +%Y-%m-%dT%H:%M:%SZ) @ $(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  {
    printf '%s\n' "${files[@]}"
    if [[ -f "$LEGACY_MANIFEST" ]]; then   # keep tracking what the pre-rename install put here
      grep -v '^#' "$LEGACY_MANIFEST" | grep -v -e '^/' -e '\.\.' || true   # never carry an entry outside CLAUDE_DIR
    fi
  } | sort -u
} > "$MANIFEST"
if [[ -f "$LEGACY_MANIFEST" ]]; then
  rm -f "$LEGACY_MANIFEST"   # merged into the manifest just written
fi

echo "Installed ${#files[@]} files to $DEST (manifest: $MANIFEST)"
if [[ $backed_up -gt 0 ]]; then
  echo "Backed up $backed_up differing file(s) to $BACKUP"
fi
echo ""
echo "  agents: $(ls "$HERE/agents" | sed 's/\.md$//' | tr '\n' ' ')"
echo "  skills: $(ls "$HERE/skills" | tr '\n' ' ')"
echo ""
echo "New task: start Claude Code in the task repo and run /task-intake."
echo "Working agreement to copy into the task repo: $HERE/AGENTS.md (plus a CLAUDE.md containing @AGENTS.md)"
