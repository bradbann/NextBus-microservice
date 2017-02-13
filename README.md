# NextBus
This is a RESTful wrapper around NextBus Public XML Feed, that adds a couple of features on top of it:
 - return JSON or XML responses (the original service only returns XML)
 - Provides an endpoint that returns the total queries for each endpoint: `/nextbus/total_queries/<endpoint>`
 - Provides an endpoint that returns the slow queries: `/nextbus/slow_queries`
 - Provides an endpoint that allows the user to explore all the rounts that don't operate at a certain hour: `/nextbus/notRunning?hour=<hour>`

The system is composed of several services in order to provide high availability and in order to be scalable. The main service is called **nextbus** and is
stateless. The result of each query to NextBus Public XML Feed is stored in **redis** for a period of 30 seconds. **nginx** sits on top of two **nextbus** 
services and acts as a load balancer. The **nextbus** service informs **etcd** of its existence whenever it's spawned, and also every minute. **confd** watches
**etcd** for changes and adjusts **nginx** configuration accordingly. This means that if a **nextbus** service dies or is spwaned, the configuration of **nginx**
will be changed within 10 seconds (the check interval of confd). All these services are running inside Docker containers:
 - **Nginx** and **confd** run inside one single container.
 - **nextbus** runs inside one single container alogside a service that constantly updates etcd.
 - **etcd** runs inside a single container.
 - **redis** also runs on its own container.

## Dependencies
In order to run the application, you need to have **Docker** and **docker-compose** installed in your system. You can confirm this by typing the following in a terminal:
```
$ docker --version
Docker version 1.13.1, build 092cba3
$ docker-compose --version
docker-compose version 1.10.1, build b252738
```

Optionally, you should have **GNU Make** available:
```
$ make --version
GNU Make 4.1
Built for x86_64-pc-linux-gnu
Copyright (C) 1988-2014 Free Software Foundation, Inc.
Licence GPLv3+: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>
This is free software: you are free to change and redistribute it.
There is NO WARRANTY, to the extent permitted by law.
```

If you don't, then you'll have to run the `docker-compose` commands manually.

## How to run
In order to put the system up and running, you just need to do the following:
```
$ make run
```

This will invoke the command `docker-compose up` and create 5 containers:
 - 1 container with **nginx**
 - 2 containers with **nextbus**
 - 1 container with **etcd**
 - 1 container with **redis**

In order to use the system, you can use `curl` or your browser and hit `http://127.0.0.1/nextbus/agencyList`, for example.

## Scalability
Because the **nextbus** microservice is stateless, we can scale the system by just launching new containers. The only issue would be to let **nginx** know that
there are new containers for it to balance the incoming traffic. Fortunatelly, this can be solved using **etcd** and **confd** together. Here's how these two components
solve the service discoverability issue:
 1. **etcd** is used as key/value store by **nextbus**.
 2. When a new container with **nextbus** is launched, it stores its *host* and *port* information in **etcd** under `/services/nextbus/servers/<hostname>`, where `hostname` is the container's hostname. This is accomplished by the **nextbus.sh** script, which is also invoked as a cron job every minute. This key in **etcd** expires after 90 seconds, which is why **nextbus.sh** must also run as a cron job. The reason for having a TTL on the key is that we want to make sure that if a container dies, **nginx** will stop forwarding traffic to the dead container.
 3. **nginx** is launched together with **confd**. **confd** is responsible for monitoring **etcd** for changes every 10 seconds. Whenever it detects a change, it updates **nginx** configuration accordingly, using a template. The new configuration is checked for errors, before being reloaded. If there are any errors, the old configuration is kept.

### etcd + nextbus
In order to make itself discoverable, a **nextbus** service just needs to perform a simple *curl* to **etcd** as follows:

```bash
#!/bin/bash

IP_ADDR=$(ifconfig eth0 | grep "inet addr" | awk '{ print $2 }' | cut -d : -f 2)

curl http://etcd:2379/v2/keys/services/nextbus/servers/$HOSTNAME \
  -d value='{"host":"'$IP_ADDR'", "port": 5000}' -d ttl=90 -X PUT
```

Nothing special here. The only thing to take into consideration is the TTL for the key. Since we don't want **nginx** to forward traffic to dead containers, we must make sure that each container makes itself announced periodically, using a cron job (there are other ways):

```bash
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

* * * * * /src/nextbus.sh >> /var/log/cron.log 2>&1
#
```

### nginx + confd
**confd** is the piece of the puzzle responsible for monitoring changes in **etcd**. This means that whenever a **nextbus** container is launched, **confd** will be aware of its existance. Here's how that happens:

```bash
#!/bin/bash
set -eo pipefail

ETCD=http://etcd:2379

echo "[nginx] booting container. ETCD: $ETCD"

# Try to make initial configuration every 5 seconds until successful
until confd -onetime -node $ETCD -config-file /etc/confd/conf.d/nginx.toml; do
	echo "[nginx] waiting for confd to create initial nginx configuration"
	sleep 5
done

# Put a continual polling `confd` process into the background to watch
# for changes every 10 seconds
confd -interval 10 -node $ETCD -config-file /etc/confd/conf.d/nginx.toml &
echo "[nginx] confd is now monitoring etcd for changes..."

# Start the Nginx service using the generated config
echo "[nginx] starting nginx service..."
service nginx start
```

This script *confd-watch* tries to create an initial configuration for **nginx**, and it will keep on trying until it succeeds. This means that if the container with **nginx** and **confd** is launched before **nextbus**, this will be in a loop until the first service makes itself announced. The file *nginx.toml* plays an important role as well:

```
[template]
src = "nginx.conf.tmpl"
dest = "/etc/nginx/nginx.conf"
owner = "nginx"
mode = "0644"
keys = [
    "/services",
]
check_cmd = "/usr/sbin/nginx -t -c {{.src}}"
reload_cmd = "/usr/sbin/service nginx reload"
```

The *check_cmd* directive is a way of **confd** to use the **nginx** configuration check to verify if a configuration file is valid, before reloading it. If the file is valid, it will be assumed as the new configuration file and **nginx** will reload it, with no downtime. The new configuration file is built from a template file called *nginx.conf.tmpl*:

```
daemon off;
worker_processes 4;

events { worker_connections 1024; }

http {
	upstream nextbus-app {
		least_conn;
		{{ $servers := getvs ( printf "/services/nextbus/servers/*" ) }}
		{{ if $servers }}
		{{ range $server := $servers }}
		{{ $data := json $server }}
		server {{ $data.host }}:{{ $data.port }} weight=10 max_fails=3 fail_timeout=30s;
		{{ end }}
		{{ end }}
	}

	server {
		listen 80;

		location / {
			proxy_pass http://nextbus-app;
			proxy_http_version 1.1;
			proxy_set_header Upgrade $http_upgrade;
			proxy_set_header Connection 'upgrade';
			proxy_set_header Host $host;
			proxy_cache_bypass $http_upgrade;
		}
	}
}
```

Only the *upstream* block is affected by changes in **etcd**. Here's what's happening in that section:
 1. **confd** lists everything in **etcd** under the key /services/nextbus/servers.
 2. If **nextbus** containers previously made themselves discoverable, then `{{ if $servers }}` succeeds and two servers will be added to the *upstream* block.
 3. If no container made itself discoverable or it they died, then their old keys in **etcd** would have expired after 90 seconds, cause the *if* block to not be entered and the *upstream* section wouldn't have any server. Since this is an invalid **nginx** configuration, the *check_cmd* in *nginx.toml* would fail.
