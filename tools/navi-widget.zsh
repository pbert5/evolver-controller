# Optional Navi integration for repository development shells.
# This file is sourced by the container dotfiles, not executed directly.

if (( $+commands[navi] )); then
  _meta_ball_navi_accept_line() {
    if [[ -z "${BUFFER//[[:space:]]/}" ]]; then
      local selected
      selected=$(navi --print 2>/dev/tty) || return 0
      if [[ -n "$selected" ]]; then
        LBUFFER=$selected
        RBUFFER=""
        zle redisplay
      fi
      return 0
    fi
    zle .accept-line
  }

  zle -N meta-ball-navi-accept-line _meta_ball_navi_accept_line
  bindkey -M emacs '^M' meta-ball-navi-accept-line
  bindkey -M viins '^M' meta-ball-navi-accept-line
fi
