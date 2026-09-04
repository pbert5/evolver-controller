autoload -Uz compinit && compinit -d "${ZDOTDIR:-$HOME}/.zcompdump"
source /usr/share/zsh-autosuggestions/zsh-autosuggestions.zsh
source /usr/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh
setopt HIST_IGNORE_DUPS SHARE_HISTORY
bindkey '^R' history-incremental-pattern-search-backward
alias ll='ls -alF'
alias la='ls -A'
command -v fzf >/dev/null && source <(fzf --zsh 2>/dev/null || true)
command -v zoxide >/dev/null && eval "$(zoxide init zsh)"
export EDITOR="${EDITOR:-vim}"
