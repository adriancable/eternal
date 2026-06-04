#!/bin/sh

mount -t proc none /proc
mount -t sysfs none /sys
mount -t devtmpfs devtmpfs /dev

ifconfig lo 127.0.0.1 up

resize
fbcat /etc/banner_small.sixel

echo -ne "\033[1mWelcome to Eternal Linux!\033[0m"
cd /root
