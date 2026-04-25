#!/usr/bin/env bash
# Compat alias — forwards to start.sh --foreground so you still get
# the Ctrl-C-to-stop behaviour when running `./run.sh`. For background
# management use ./start.sh + ./stop.sh instead.
exec ./start.sh --foreground "$@"
