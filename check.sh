#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
cmp <(printf 'ASTROZ_SMOKE_OK') smoke_ok.txt
