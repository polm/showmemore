#!/bin/bash
# Have your bot post
# If you can get stuck in random loops, remember to use timeout!
set -e

cd $(dirname $0)
export LC_ALL=ja_JP.UTF-8
./laser.py &>> log
