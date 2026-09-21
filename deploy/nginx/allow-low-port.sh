#!/bin/sh
# Replaces the image's 01-check-low-port.sh.
#
# That script refuses PORT below 1024 because the CRS images moved to an
# unprivileged user and assume such a port cannot be bound. The assumption is
# no longer true here: compose sets net.ipv4.ip_unprivileged_port_start=0 on
# this container, so uid 101 can bind 80.
#
# It is worth the override. The port was the last piece of the lab's plumbing
# showing in the target's name - an attacker dials http://shop.com, not
# http://shop.com:8080 - and every alternative costs a service or runs the WAF
# as root. See docs/DECISIONS.md.
exit 0
