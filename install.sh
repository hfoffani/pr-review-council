#!/usr/bin/env bash
set -euo pipefail

min_uv_version="0.1.28"
repo_url="${PRC_REPO_URL:-https://github.com/hfoffani/pr-review-council.git}"
install_ref="${PRC_INSTALL_REF:-}"
assume_yes="${PRC_YES:-}"
tool_spec="git+${repo_url}"

if [[ -n "${install_ref}" ]]; then
  tool_spec="${tool_spec}@${install_ref}"
fi

say() {
  printf 'prc installer: %s\n' "$1"
}

die() {
  printf 'prc installer: %s\n' "$1" >&2
  exit 1
}

version_ge() {
  local have="$1"
  local need="$2"
  local have_part need_part
  local -a have_parts need_parts
  local i
  local IFS=.

  read -r -a have_parts <<<"${have}"
  read -r -a need_parts <<<"${need}"

  for i in 0 1 2; do
    have_part="${have_parts[$i]:-0}"
    need_part="${need_parts[$i]:-0}"

    if ((10#${have_part} > 10#${need_part})); then
      return 0
    fi

    if ((10#${have_part} < 10#${need_part})); then
      return 1
    fi
  done

  return 0
}

check_uv() {
  local uv_version

  if ! command -v uv >/dev/null 2>&1; then
    die "uv is required. Install it from https://docs.astral.sh/uv/."
  fi

  uv_version="$(uv --version | awk '{print $2}')"
  say "found uv ${uv_version}"

  if ! version_ge "${uv_version}" "${min_uv_version}"; then
    die "uv ${min_uv_version} or newer is required for 'uv tool install'."
  fi
}

confirm_install() {
  local answer

  if [[ "${assume_yes}" == "1" || "${assume_yes}" == "true" || "${assume_yes}" == "yes" ]]; then
    return
  fi

  say "this will install or upgrade the 'prc' command from ${tool_spec}"

  if [[ -r /dev/tty ]]; then
    printf 'Proceed? [y/N] ' >/dev/tty
    read -r answer </dev/tty
  else
    die "confirmation requires a terminal; set PRC_YES=1 to install non-interactively."
  fi

  case "${answer}" in
    y|Y|yes|YES)
      ;;
    *)
      die "installation cancelled"
      ;;
  esac
}

verify_prc() {
  local tool_bin

  if command -v prc >/dev/null 2>&1; then
    prc --help >/dev/null
    say "installed successfully: $(command -v prc)"
    return
  fi

  say "installed, but 'prc' is not on PATH in this shell yet."
  tool_bin="$(uv tool dir --bin 2>/dev/null || true)"
  if [[ -n "${tool_bin}" ]]; then
    say "uv installed tool executables into: ${tool_bin}"
  fi
  say "Run 'uv tool update-shell' or open a new terminal, then try 'prc --help'."
}

install_with_uv() {
  say "running: uv tool install --upgrade ${tool_spec}"
  uv tool install --upgrade "${tool_spec}"
}

main() {
  say "source: ${tool_spec}"
  check_uv
  confirm_install
  install_with_uv
  verify_prc
}

main "$@"
