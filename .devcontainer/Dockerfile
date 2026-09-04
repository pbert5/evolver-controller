FROM mcr.microsoft.com/vscode/devcontainers/python:1-3.12-bookworm AS base

# Keep tool versions here: every profile is built from this stage.
ARG UV_VERSION=0.8.14
ARG RTK_VERSION=v0.47.0
ARG NAVI_VERSION=v2.24.0
USER root
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl fd-find fzf git gh ripgrep tmux zsh zsh-autosuggestions zsh-syntax-highlighting build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx \
    && curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | PATH=/root/.local/bin:$PATH RTK_VERSION=${RTK_VERSION} sh \
    && install -m 0755 /root/.local/bin/rtk /usr/local/bin/rtk \
    && curl -fsSL "https://github.com/denisidoro/navi/releases/download/${NAVI_VERSION}/navi-${NAVI_VERSION}-x86_64-unknown-linux-musl.tar.gz" -o /tmp/navi.tar.gz \
    && tar -xzf /tmp/navi.tar.gz -C /usr/local/bin \
    && chmod 0755 /usr/local/bin/navi \
    && rm -f /tmp/navi.tar.gz \
    && install -d -m 0755 /opt/codex \
    && curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_HOME=/opt/codex CODEX_INSTALL_DIR=/usr/local/bin CODEX_NON_INTERACTIVE=1 sh \
    && codex --version \
    && mkdir -p /opt/meta-ball/bin /workspaces \
    && chown -R vscode:vscode /opt/meta-ball /workspaces
COPY .devcontainer/dotfiles/.zshrc .devcontainer/dotfiles/.tmux.conf /tmp/
RUN install -o vscode -g vscode -m 0644 /tmp/.zshrc /home/vscode/.zshrc \
    && install -o vscode -g vscode -m 0644 /tmp/.tmux.conf /home/vscode/.tmux.conf \
    && rm -f /tmp/.zshrc /tmp/.tmux.conf
USER vscode
ENV PATH="/home/vscode/.local/bin:${PATH}" UV_LINK_MODE=copy

FROM base AS server
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends btop gnupg jq openssh-client postgresql-client yq \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://deb.griffo.io/EA0F721D231FDD3A0A17B9AC7808B4DD62C41256.asc | gpg --dearmor --yes -o /etc/apt/keyrings/deb.griffo.io.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/deb.griffo.io.gpg] https://deb.griffo.io/apt bookworm main" > /etc/apt/sources.list.d/deb.griffo.io.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends lazygit \
    && rm -rf /var/lib/apt/lists/*
COPY .devcontainer/server/scripts/ /opt/meta-ball/bin/
RUN chmod +x /opt/meta-ball/bin/* \
    && for script in /opt/meta-ball/bin/*; do ln -sf "$script" "/usr/local/bin/$(basename "$script")"; done \
    && chown -R vscode:vscode /opt/meta-ball
USER vscode
ENV PATH="/home/vscode/.local/bin:/opt/meta-ball/bin:${PATH}"

FROM base AS evolver-edge
USER root
COPY .devcontainer/evolver-edge/scripts/ /opt/meta-ball-edge/bin/
RUN chmod +x /opt/meta-ball-edge/bin/* \
    && for script in /opt/meta-ball-edge/bin/*; do ln -sf "$script" "/usr/local/bin/$(basename "$script")"; done
RUN mkdir -p /home/vscode/.cache/uv && chown -R vscode:vscode /home/vscode/.cache
USER vscode
ENV PATH="/home/vscode/.local/bin:/opt/meta-ball-edge/bin:${PATH}"
