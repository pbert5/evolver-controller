# Meta BAL additions to the base devcontainer Zsh setup.
# The base image owns the prompt, completion, and Oh My Zsh initialization;
# this fragment only adds repository-specific tools and the safe Navi widget.

setopt HIST_IGNORE_DUPS SHARE_HISTORY
bindkey '^R' history-incremental-pattern-search-backward
alias ll='ls -alF'
alias la='ls -A'

if (( $+commands[fzf] )); then
  source <(fzf --zsh 2>/dev/null || true)
fi
if (( $+commands[zoxide] )); then
  eval "$(zoxide init zsh)"
fi

export EDITOR="${EDITOR:-vim}"
export NAVI_PATH="${NAVI_PATH:-/workspaces/meta_bal/docs/navi/generated}"
if [[ -r /workspaces/meta_bal/tools/navi-widget.zsh ]]; then
  source /workspaces/meta_bal/tools/navi-widget.zsh
fi
