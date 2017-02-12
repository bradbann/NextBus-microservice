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

Also make sure you have **GNU Make** available:
```
$ make --version
GNU Make 4.1
Built for x86_64-pc-linux-gnu
Copyright (C) 1988-2014 Free Software Foundation, Inc.
Licence GPLv3+: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>
This is free software: you are free to change and redistribute it.
There is NO WARRANTY, to the extent permitted by law.
```

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
