# The box (plan step 1.0a): an image in which a session builds with permission checks off. Built only by
# tools/box/box.py, which passes every pin of pins.env as a build argument and tags the image with the git SHA.
# No ARG has a default: a missing pin fails the build.
ARG NODE_IMAGE
ARG UV_IMAGE

FROM ${UV_IMAGE} AS uv

# --- tools: everything that is downloaded, checked and unpacked; nothing of this stage but its results ships ---
FROM ${NODE_IMAGE} AS tools
ARG NODE_VERSION
ARG APT_PINS
ARG PYTHON_39
ARG PYTHON_313
ARG PYTEST_39
ARG PYTEST_313
ARG RUFF
ARG GH
ARG GH_SHA256_ARM64
ARG GH_SHA256_AMD64
ARG CLAUDE_CODE
ARG TARGETARCH
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
COPY --from=uv /uv /usr/local/bin/uv
RUN test "$(node --version)" = "v${NODE_VERSION}" \
 && apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends ${APT_PINS} \
 && rm -rf /var/lib/apt/lists/*
# Two CPython builds from python-build-standalone (relocatable), each with its own pytest; ruff once.
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_NO_CACHE=1
RUN uv python install "${PYTHON_39}" "${PYTHON_313}" \
 && uv venv --python "${PYTHON_39}" /opt/venv/py39 \
 && uv venv --python "${PYTHON_313}" /opt/venv/py313 \
 && uv pip install --python /opt/venv/py39/bin/python "pytest==${PYTEST_39}" \
 && uv pip install --python /opt/venv/py313/bin/python "pytest==${PYTEST_313}" "ruff==${RUFF}"
# gh from its release tarball, checked against the checksum pinned in pins.env (not the release's own list).
RUN case "${TARGETARCH}" in arm64) sum="${GH_SHA256_ARM64}" ;; amd64) sum="${GH_SHA256_AMD64}" ;; \
      *) echo "no gh pin for ${TARGETARCH}" >&2; exit 1 ;; esac \
 && curl -fsSL -o /tmp/gh.tgz "https://github.com/cli/cli/releases/download/v${GH}/gh_${GH}_linux_${TARGETARCH}.tar.gz" \
 && echo "${sum}  /tmp/gh.tgz" | sha256sum -c - \
 && tar -xzf /tmp/gh.tgz -C /tmp \
 && install -m 0755 "/tmp/gh_${GH}_linux_${TARGETARCH}/bin/gh" /usr/local/bin/gh
RUN npm install -g --no-fund --no-audit "@anthropic-ai/claude-code@${CLAUDE_CODE}" \
 && test "$(claude --version | cut -d' ' -f1)" = "${CLAUDE_CODE}"

# --- the box ---
FROM ${NODE_IMAGE}
ARG APT_PINS
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends ${APT_PINS} \
 && rm -rf /var/lib/apt/lists/*
COPY --from=tools /opt/python /opt/python
COPY --from=tools /opt/venv /opt/venv
COPY --from=tools /usr/local/bin/gh /usr/local/bin/gh
COPY --from=tools /usr/local/lib/node_modules/@anthropic-ai /usr/local/lib/node_modules/@anthropic-ai
RUN ln -s ../lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe /usr/local/bin/claude \
 && ln -s /opt/venv/py313/bin/python /usr/local/bin/python3 \
 && ln -s /opt/venv/py313/bin/python /usr/local/bin/python3.13 \
 && ln -s /opt/venv/py39/bin/python /usr/local/bin/python3.9 \
 && ln -s /opt/venv/py313/bin/ruff /usr/local/bin/ruff \
 && install -d -m 0755 -o root -g root /etc/agent-box /etc/claude-code /usr/local/share/agent-box
COPY --chown=root:root --chmod=0755 entrypoint.sh /usr/local/sbin/box-entrypoint
COPY --chown=root:root --chmod=0644 firewall.py marker.py allowlist /usr/local/share/agent-box/
COPY --chown=root:root --chmod=0644 managed-settings.json /etc/claude-code/managed-settings.json
# The CLI must stay at its pin and send no traffic beyond the model API: no updater, no telemetry.
ENV DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    PYTHONDONTWRITEBYTECODE=1
# The marker is written by the entrypoint only after the firewall is set, so it doubles as the health signal.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=1 CMD test -s /etc/agent-box/box.json
WORKDIR /work
# The image starts as root on purpose: the entrypoint sets the firewall, writes the marker and then drops to the
# user `node` (uid 1000) with no capabilities and no-new-privs. Nothing else runs as root.
ENTRYPOINT ["/usr/local/sbin/box-entrypoint"]
CMD ["bash"]
