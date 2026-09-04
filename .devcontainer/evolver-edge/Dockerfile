FROM mcr.microsoft.com/vscode/devcontainers/python:1-3.12-bookworm
ARG UV_VERSION=0.8.14
ARG RTK_VERSION=v0.47.0
USER root
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl fd-find fzf git gh jq ripgrep tmux zsh zsh-autosuggestions \
    zsh-syntax-highlighting build-essential && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx \
    && curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | PATH=/root/.local/bin:$PATH RTK_VERSION=${RTK_VERSION} sh \
    && install -m 0755 /root/.local/bin/rtk /usr/local/bin/rtk
COPY scripts/ /opt/meta-ball-edge/bin/
RUN chmod +x /opt/meta-ball-edge/bin/* && for script in /opt/meta-ball-edge/bin/*; do ln -sf "$script" "/usr/local/bin/$(basename "$script")"; done
COPY dotfiles/.zshrc dotfiles/.tmux.conf /tmp/
RUN install -o vscode -g vscode -m 0644 /tmp/.zshrc /home/vscode/.zshrc && install -o vscode -g vscode -m 0644 /tmp/.tmux.conf /home/vscode/.tmux.conf
RUN mkdir -p /home/vscode/.cache/uv && chown -R vscode:vscode /home/vscode/.cache
USER vscode
ENV PATH="/home/vscode/.local/bin:/opt/meta-ball-edge/bin:${PATH}" UV_LINK_MODE=copy
