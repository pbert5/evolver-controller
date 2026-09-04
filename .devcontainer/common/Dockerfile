FROM mcr.microsoft.com/vscode/devcontainers/python:1-3.12-bookworm
ARG UV_VERSION=0.8.14
ARG RTK_VERSION=v0.47.0
ARG DEBIAN_FRONTEND=noninteractive
USER root
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash btop ca-certificates curl fd-find fzf git gh jq gnupg openssh-client postgresql-client ripgrep tmux yq zsh zsh-autosuggestions zsh-syntax-highlighting build-essential \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://deb.griffo.io/EA0F721D231FDD3A0A17B9AC7808B4DD62C41256.asc | gpg --dearmor --yes -o /etc/apt/keyrings/deb.griffo.io.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/deb.griffo.io.gpg] https://deb.griffo.io/apt bookworm main" > /etc/apt/sources.list.d/deb.griffo.io.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends lazygit \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && ln -sf /usr/bin/batcat /usr/local/bin/bat \
    && curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx \
    && curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | PATH=/root/.local/bin:$PATH RTK_VERSION=${RTK_VERSION} sh \
    && install -m 0755 /root/.local/bin/rtk /usr/local/bin/rtk \
    && install -d -m 0755 /opt/codex \
    && curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_HOME=/opt/codex CODEX_INSTALL_DIR=/usr/local/bin CODEX_NON_INTERACTIVE=1 sh \
    && codex --version \
    && mkdir -p /opt/meta-ball/bin /workspaces \
    && chown -R vscode:vscode /opt/meta-ball /workspaces
COPY scripts/ /opt/meta-ball/bin/
RUN chmod +x /opt/meta-ball/bin/* \
    && for script in /opt/meta-ball/bin/*; do ln -sf "$script" "/usr/local/bin/$(basename "$script")"; done \
    && chown -R vscode:vscode /opt/meta-ball
COPY dotfiles/.zshrc dotfiles/.tmux.conf /tmp/
RUN install -o vscode -g vscode -m 0644 /tmp/.zshrc /home/vscode/.zshrc \
    && install -o vscode -g vscode -m 0644 /tmp/.tmux.conf /home/vscode/.tmux.conf \
    && rm -rf /tmp/.zshrc /tmp/.tmux.conf
USER vscode
ENV PATH="/home/vscode/.local/bin:/opt/meta-ball/bin:${PATH}" UV_LINK_MODE=copy
