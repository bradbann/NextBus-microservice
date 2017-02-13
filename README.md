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
 2. When a new container with **nextbus** is launched, it stores its *host* and *port* information in **etcd** under `/services/nextbus/servers/<hostname>`. This is accomplished by the **nextbus.sh** script, which is also invoked as a cron job every minute. This key in **etcd** expires after 90 seconds, which is why **nextbus.sh** must also run as a cron job. The reason for having a TTL on the key is that we want to make sure that if a container dies, **nginx** will stop forwarding traffic to the dead container.
 3. **nginx** is launched together with **confd**. **confd** is responsible for monitoring **etcd** for changes every 10 seconds. Whenever it detects a change, it updates **nginx** configuration accordingly, using a template. The new configuration is checked for errors, before being reloaded. If there are any errors, the old configuration is kept.
