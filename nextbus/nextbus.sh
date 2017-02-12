#!/bin/bash

IP_ADDR=$(ifconfig eth0 | grep "inet addr" | awk '{ print $2 }' | cut -d : -f 2)

curl http://etcd:2379/v2/keys/services/nextbus/servers/$HOSTNAME \
  -d value='{"host":"'$IP_ADDR'", "port": 5000}' -d ttl=90 -X PUT

