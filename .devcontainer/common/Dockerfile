FROM mcr.microsoft.com/vscode/devcontainers/python:1-3.12-bookworm
ARG UV_VERSION=0.8.14
ARG NODE_MAJOR=22
USER root
# Node is installed from the NodeSource major channel so every configuration
# built from this image gets the same supported LTS runtime. The inherited
# base image's Yarn Classic source is not used here; remove that stale source
# before apt updates so its expired signing key cannot block or weaken
# verification of the Debian repositories.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git gh jq yq ripgrep fd-find bat fzf tmux openssh-client zsh postgresql-client build-essential chromium docker.io gnupg \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://deb.griffo.io/EA0F721D231FDD3A0A17B9AC7808B4DD62C41256.asc | gpg --dearmor --yes -o /etc/apt/keyrings/deb.griffo.io.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/deb.griffo.io.gpg] https://deb.griffo.io/apt bookworm main" > /etc/apt/sources.list.d/deb.griffo.io.list \
    && curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends lazygit nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && ln -sf /usr/bin/batcat /usr/local/bin/bat \
    && curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx \
    && npm install --global @openai/codex \
    && curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh \
    && install -m 0755 /root/.local/bin/rtk /usr/local/bin/rtk \
    && mkdir -p /opt/meta-webui/bin /workspaces /opt/meta-webui/node-runtime \
    && chown -R vscode:vscode /opt/meta-webui /workspaces
COPY scripts/ /opt/meta-webui/bin/
RUN chmod +x /opt/meta-webui/bin/* \
    && for script in /opt/meta-webui/bin/*; do ln -sf "$script" "/usr/local/bin/$(basename "$script")"; done
USER vscode
ENV PATH="/home/vscode/.local/bin:/opt/meta-webui/bin:${PATH}" UV_LINK_MODE=copy PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium
