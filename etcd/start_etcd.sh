#!/bin/sh
etcd --name etcd                                                      \
  -advertise-client-urls http://127.0.0.1:2379,http://127.0.0.1:4001  \
  -listen-client-urls http://0.0.0.0:2379,http://0.0.0.0:4001         \
  -initial-advertise-peer-urls http://127.0.0.1:2380                  \
  -listen-peer-urls http://0.0.0.0:2380
