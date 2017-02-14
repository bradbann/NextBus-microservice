# NextBus
This is a RESTful wrapper around NextBus Public XML Feed, that adds a couple of features on top of it:
 - return JSON or XML responses (the original service only returns XML)
 - Provides an endpoint that returns the total queries for each endpoint: `/nextbus/total_queries/<endpoint>`
 - Provides an endpoint that returns the slow queries: `/nextbus/slow_queries`
 - Provides an endpoint that allows the user to explore all the rounts that don't operate at a certain hour: `/nextbus/notRunning?t=<hour>`

The system is composed of several services in order to provide high availability and in order to be scalable. The main service is called **nextbus** and is
stateless. The result of each query to NextBus Public XML Feed is stored in **redis** for a period of 30 seconds. **nginx** sits in front of two **nextbus** 
services and acts as a load balancer. The **nextbus** service informs **etcd** of its existence whenever it's spawned, and also every minute. **confd** watches
**etcd** for changes and adjusts **nginx** configuration accordingly. This means that if a **nextbus** service dies or is spwaned, the configuration of **nginx**
will be changed within 10 seconds (the check interval of confd). All these services are running inside Docker containers:
 - **Nginx** and **confd** run inside one single container. This container also has a script that watches **etcd** every 10 seconds.
 - **nextbus** runs inside one single container with a cron job that constantly updates **etcd**.
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

## How to run
In order to put the system up and running, you just need to do the following:
```
$ docker-compose up
```

If you want to run *docker-compose* in the background, just enter `docker-compose up -d`, instead.

This will invoke the command `docker-compose up` and create 5 containers:
 - 1 container with **nginx**
 - 2 containers with **nextbus**
 - 1 container with **etcd**
 - 1 container with **redis**
 - 1 container with **elasticsearch**
 - 1 container with **populator**

In order to use the API, you can use `curl` or your browser and hit `http://127.0.0.1/nextbus/agencyList`, for example.
To stop, just press CTRL+C, unless you used the `-d` flag. In that case, enter `docker-compose stop`. This will just stop the containers. If you want to remove the containers and the network, enter `docker-compose down`.

## Endpoints
There are several endpoints available, even though most of them redirect to NextBus web service. For those endpoints, please consult the official documentation for available parameters and expected responses. You can find the documentation [here](http://www.nextbus.com/xmlFeedDocs/NextBusXMLFeed.pdf).

```
/nextbus/agencyList
/nextbus/routeList
/nextbus/routeConfig
/nextbus/predictions
/nextbus/predictionsForMultiStops
/nextbus/schedule
/nextbus/messages
/nextbus/vehicleLocation
```

Note that to the default NextBus endpoints, it was added the feature of retrieving the response in either JSON or XML formats. You just need to add a query parameter *format* with the values **json** or **xml**.

### /nextbus/slow_requests
Retrieves a list with all the requests, in a descending order of execution time in milliseconds (**note**: implement limit in this request). Right now, the name of the endpoint has the request ID as a suffix (e.g. agencyList:5).

Example response:
```json
[
    [
        "agencyList:5",
        406.562
    ],
    [
        "agencyList:1",
        404.653
    ],
    [
        "agencyList:6",
        1.396
    ],
    [
        "agencyList:2",
        1.364
    ],
    [
        "agencyList:4",
        0.762
    ],
    [
        "agencyList:3",
        0.476
    ]
]
```

### /nextbus/total_queries/:endpoint
Returns the total number of queries performed to a certain endpoint.

Example response (/nextbus/total_queries/agencyList):
```json
{
    "total_queries": 6
}
```

### /nextbus/notRunning?t=time&page=N

Returns a list of routes that don't operate at a certain time. The parameter *t* should have a format **HHMMSS** and is mandatory. The parameter *page* indicates which page of the results you want to fetch. Each page holds at most 10 results.

Example response (/nextbus/notRunning?t=0200):
```json
{
    "pages": 8,
    "routes": [
        "19",
        "22",
        "24",
        "14",
        "14R",
        "82X",
        "83X",
        "25",
        "29",
        "44"
    ]
}
```

This returns a list of routes that don't operate at 2:00AM. There are 8 pages of results.

**NOTE**: right now this endpoint doesn't return a correct response, since the service **populator** is not building correctly the interval of operation for certain routes. I need to understand better the data that I get from NextBus. This means that most likely you will get routes that actually operate at the given hour, simply because ElasticSearch is not being properly populated.

## Populator
In order to provide the endpoint `/nextbus/notRunning`, a separate service called **populator** is responsible for populating an instance of ElasticSearch at regular intervals of one hour. Every hour, this service fetches all the schedules from all the routes from agency *sf-muni* (for San Francisco) and builds the intervals of operation for each route. Right now, the algorithm is a bit buggy, since I find the data coming from NextBus to be a bit confusing. As a result, certain routes have incorrect start and end hours of service.

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

### Scaling in action
When we first run `make run`, the system starts with two **nextbus** containers. Let's check some logs:

```bash
...

nextbus1_1  | {"action":"set","node":{"key":"/services/nextbus/servers/b2faf3000f81","value":"{\"host\":\"172.18.0.6\", \"port\": 5000}","expiration":"2017-02-13T12:10:28.216283484Z","ttl":90,"modifiedIndex":5,"createdIndex":5}}
redis_1     |  |    `-._   `._    /     _.-'    |     PID: 1
nextbus_1   | {"action":"set","node":{"key":"/services/nextbus/servers/4691a699eff0","value":"{\"host\":\"172.18.0.5\", \"port\": 5000}","expiration":"2017-02-13T12:10:28.177736986Z","ttl":90,"modifiedIndex":4,"createdIndex":4}}

...

nextbus_1   |  * Running on http://0.0.0.0:5000/ (Press CTRL+C to quit)
nextbus_1   |  * Restarting with stat
nextbus1_1  |  * Running on http://0.0.0.0:5000/ (Press CTRL+C to quit)
nextbus1_1  |  * Restarting with stat
nextbus_1   |  * Debugger is active!
nextbus_1   |  * Debugger pin code: 858-943-884
nextbus1_1  |  * Debugger is active!
nextbus1_1  |  * Debugger pin code: 292-293-092
nginx_1     | 2017-02-13T12:09:02Z ceedbb3be52f confd[16]: INFO Backend set to etcd
nginx_1     | 2017-02-13T12:09:02Z ceedbb3be52f confd[16]: INFO Starting confd
nginx_1     | 2017-02-13T12:09:02Z ceedbb3be52f confd[16]: INFO Backend nodes set to http://etcd:2379
nginx_1     | 2017-02-13T12:09:02Z ceedbb3be52f confd[16]: INFO /etc/nginx/nginx.conf has md5sum 907bbf7d1cb3f410d8d6d4474a984b86 should be 810537cac50217494b20fde77ca0a12d
nginx_1     | 2017-02-13T12:09:02Z ceedbb3be52f confd[16]: INFO Target config /etc/nginx/nginx.conf out of sync
nginx_1     | 2017-02-13T12:09:02Z ceedbb3be52f confd[16]: INFO Target config /etc/nginx/nginx.conf has been updated
nginx_1     | [nginx] confd is now monitoring etcd for changes...
nginx_1     | [nginx] starting nginx service...
nginx_1     | 2017-02-13T12:09:02Z ceedbb3be52f confd[44]: INFO Backend set to etcd
nginx_1     | 2017-02-13T12:09:02Z ceedbb3be52f confd[44]: INFO Starting confd
nginx_1     | 2017-02-13T12:09:02Z ceedbb3be52f confd[44]: INFO Backend nodes set to http://etcd:2379
nginx_1     |  * Starting nginx nginx
```

As we can see, the two containers *nextbus_1* and *nextbus1_1* made themselves discoverable by adding a new key/value pair to **etcd**. As soon as **condf** detected these changes, it changed **nginx** configuration. Let's now add a few more **nextbus** containers to the system. Here's how we do it:

```bash
$ docker-compose scale nextbus=4
Creating and starting nextbusmicroservice_nextbus_2 ... done
Creating and starting nextbusmicroservice_nextbus_3 ... done
Creating and starting nextbusmicroservice_nextbus_4 ... done
```

This command basically says that I want the system to be running with 4 containers for the **nextbus** service. Bear in mind that in the *docker-compose.yml* file, one of the services is called *nextbus1*, which is why 3 extra containers were created instead of just 2. Here's the end result:

```bash
nextbus_2   |   % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
nextbus_2   |                                  Dload  Upload   Total   Spent    Left  Speed
100   262  100   214  100    48  43942   9856 --:--:-- --:--:-- --:--:-- 53500
nextbus_2   | {"action":"set","node":{"key":"/services/nextbus/servers/9999ddae5629","value":"{\"host\":\"172.18.0.7\", \"port\": 5000}","expiration":"2017-02-13T12:11:23.59393727Z","ttl":90,"modifiedIndex":8,"createdIndex":8}}
nextbus_2   |  * Starting periodic command scheduler cron
nextbus_2   |    ...done.
nextbus_3   |   % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
nextbus_3   |                                  Dload  Upload   Total   Spent    Left  Speed
100   263  100   215  100    48  44550   9946 --:--:-- --:--:-- --:--:-- 53750
nextbus_3   | {"action":"set","node":{"key":"/services/nextbus/servers/7f4d30fa6ff7","value":"{\"host\":\"172.18.0.8\", \"port\": 5000}","expiration":"2017-02-13T12:11:23.670880393Z","ttl":90,"modifiedIndex":9,"createdIndex":9}}
nextbus_3   |  * Starting periodic command scheduler cron
nextbus_3   |    ...done.
nextbus_4   |   % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
nextbus_4   |                                  Dload  Upload   Total   Spent    Left  Speed
100   265  100   217  100    48  44613   9868 --:--:-- --:--:-- --:--:-- 54250
nextbus_4   | {"action":"set","node":{"key":"/services/nextbus/servers/22f6349546b4","value":"{\"host\":\"172.18.0.9\", \"port\": 5000}","expiration":"2017-02-13T12:11:23.716373903Z","ttl":90,"modifiedIndex":10,"createdIndex":10}}
nextbus_4   |  * Starting periodic command scheduler cron
nextbus_4   |    ...done.
nextbus_2   |  * Running on http://0.0.0.0:5000/ (Press CTRL+C to quit)
nextbus_2   |  * Restarting with stat
nextbus_3   |  * Running on http://0.0.0.0:5000/ (Press CTRL+C to quit)
nextbus_3   |  * Restarting with stat
nextbus_4   |  * Running on http://0.0.0.0:5000/ (Press CTRL+C to quit)
nextbus_4   |  * Restarting with stat
nextbus_2   |  * Debugger is active!
nextbus_2   |  * Debugger pin code: 370-691-256
nextbus_3   |  * Debugger is active!
nextbus_3   |  * Debugger pin code: 102-879-249
nextbus_4   |  * Debugger is active!
nextbus_4   |  * Debugger pin code: 313-640-988
nginx_1     | 2017-02-13T12:10:02Z ceedbb3be52f confd[44]: INFO /etc/nginx/nginx.conf has md5sum 810537cac50217494b20fde77ca0a12d should be 9e502263a7e9e905ede09089d50127b3
nginx_1     | 2017-02-13T12:10:02Z ceedbb3be52f confd[44]: INFO Target config /etc/nginx/nginx.conf out of sync
nginx_1     | 2017-02-13T12:10:02Z ceedbb3be52f confd[44]: INFO Target config /etc/nginx/nginx.conf has been updated
```

Three more containers were launched, each of the containers made itself announced to **etcd** and the configuration of **nginx** was updated accordingly:

```bash
$ docker exec -it ceedbb3be52f /bin/bash
root@ceedbb3be52f:/tmp# cat /etc/nginx/nginx.conf 
daemon off;
worker_processes 4;

events { worker_connections 1024; }

http {
	upstream nextbus-app {
		least_conn;
		
		
		
		
		server 172.18.0.5:5000 weight=10 max_fails=3 fail_timeout=30s;
		
		
		server 172.18.0.6:5000 weight=10 max_fails=3 fail_timeout=30s;
		
		
		server 172.18.0.7:5000 weight=10 max_fails=3 fail_timeout=30s;
		
		
		server 172.18.0.8:5000 weight=10 max_fails=3 fail_timeout=30s;
		
		
		server 172.18.0.9:5000 weight=10 max_fails=3 fail_timeout=30s;
		
		
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

# TODO
 - Fix algorithm from **populator** service.
 - Improve coverage (current coverage: 0%)
 - Integrate with TravisCI
 - Added proper logging to the services **nextbus** and **populator**.

# License
MIT. Click [here](https://github.com/csixteen/NextBus-microservice/blob/master/LICENSE) to see the full text.
