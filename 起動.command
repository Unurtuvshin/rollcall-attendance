#!/bin/zsh
cd "${0:A:h}"
if ! command -v python3 >/dev/null 2>&1; then
  print 'Python 3.11以降をインストールしてください。'
  read '?Enterで閉じる'
  exit 1
fi
python3 server.py
read '?Enterで閉じる'
