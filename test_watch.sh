#!/bin/sh

uv run ptw . --now --patterns '*.py,*.blesstest.json,*.blesstest.jsonc' # TODO: Also listen to ,.git/index (but only when Aur isn't paying attention)
